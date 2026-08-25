"""Reusable scraper infrastructure: HTTP client, retries, rate limiting,
and the abstract interface every store scraper implements.

Store-specific scrapers only implement search_perfume, fetch_product and
parse_product - HTTP mechanics live here so they are never duplicated per
store (instructions.md section 39).
"""

import asyncio
import logging
import ssl
import time
from abc import ABC, abstractmethod
from typing import Any

import certifi
import httpx

from app.config.settings import Settings, get_settings
from app.schemas.scraping import ScrapedOffer
from app.scrapers.exceptions import RequestError

logger = logging.getLogger(__name__)

# Building an SSL context (loading and parsing certifi's CA bundle) is
# real, measured blocking work - ~0.15-0.2s on this machine - not the
# near-instant config step it looks like. httpx.AsyncClient() builds a
# fresh one on every call by default, which is harmless for one scraper
# but silently serializes multiple scrapers started concurrently (e.g.
# via asyncio.gather in scraping_service): each instance's construction
# is itself a blocking chunk that runs before the event loop can move on
# to the next one, so N stores checked "concurrently" still pay N times
# this cost back-to-back before their actual network I/O can overlap.
# An SSLContext is safe to share and reuse across many unrelated
# connections/clients (that's what it's for) - built once per process.
_SHARED_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


class BaseScraper(ABC):
    store_name: str
    store_slug: str
    base_url: str

    # A store can require a stricter minimum delay than the global
    # REQUEST_DELAY setting (e.g. a robots.txt Crawl-delay directive).
    # The effective delay is always at least this, regardless of the
    # configured REQUEST_DELAY - it only ever makes requests *more*
    # conservative, never less.
    min_request_delay: float = 0.0

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self._settings.REQUEST_TIMEOUT),
            headers={"User-Agent": self._settings.USER_AGENT},
            follow_redirects=True,
            transport=transport,
            verify=_SHARED_SSL_CONTEXT,
        )
        self._last_request_at: float | None = None
        # Guards the whole wait-then-request-then-record cycle below, not
        # just the bookkeeping - a scraper instance can now be pooled and
        # reused across overlapping checks (see app/scrapers/pool.py), so
        # two coroutines can reach request() on the SAME instance at once.
        # Without this, both could read _last_request_at before either
        # updates it and fire immediately, defeating the polite spacing
        # between requests. Serializing the whole method preserves the
        # original single-instance guarantee exactly: the delay is always
        # measured from the previous request's completion to the next
        # request's start, even under concurrent callers.
        self._request_lock = asyncio.Lock()

    @property
    def _effective_request_delay(self) -> float:
        return max(self._settings.REQUEST_DELAY, self.min_request_delay)

    async def __aenter__(self) -> "BaseScraper":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._client.aclose()

    async def _wait_for_rate_limit(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = time.monotonic() - self._last_request_at
        remaining = self._effective_request_delay - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Perform an HTTP request with polite rate limiting and retries.

        Raises RequestError if every attempt fails. A store scraper that
        can positively identify the store as down/blocking (rather than a
        transient failure) should catch RequestError and re-raise
        StoreUnavailable itself.
        """
        async with self._request_lock:
            await self._wait_for_rate_limit()

            last_error: Exception | None = None
            for attempt in range(1, self._settings.MAX_RETRIES + 1):
                try:
                    response = await self._client.request(method, url, **kwargs)
                    self._last_request_at = time.monotonic()
                    response.raise_for_status()
                    return response
                except httpx.HTTPStatusError as exc:
                    last_error = exc
                    logger.warning(
                        "%s: HTTP %s on attempt %s/%s for %s",
                        self.store_slug, exc.response.status_code, attempt, self._settings.MAX_RETRIES, url,
                    )
                    # A 4xx (other than 429, which signals "back off and
                    # try again") is a definitive answer, not a transient
                    # failure - retrying a 404 wastes time (and, on a
                    # store with a real crawl-delay, a lot of it) without
                    # ever changing the outcome. Only retry loop applies
                    # to 5xx/network errors.
                    status_code = exc.response.status_code
                    if 400 <= status_code < 500 and status_code != 429:
                        break
                except httpx.HTTPError as exc:
                    last_error = exc
                    logger.warning(
                        "%s: request error on attempt %s/%s for %s: %s",
                        self.store_slug, attempt, self._settings.MAX_RETRIES, url, exc,
                    )

                if attempt < self._settings.MAX_RETRIES:
                    await asyncio.sleep(self._effective_request_delay * attempt)

            raise RequestError(
                f"{self.store_slug}: request to {url} failed after {self._settings.MAX_RETRIES} attempts"
            ) from last_error

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def discover_offers(self, brand: str, perfume_name: str) -> list[ScrapedOffer]:
        """Orchestrates search -> fetch -> parse for one monitored perfume.

        Each candidate is fetched/parsed independently - one candidate
        failing (a stale URL that now 404s, an unexpected page shape, ...)
        must not discard offers already found from other candidates that
        did succeed.
        """
        offers: list[ScrapedOffer] = []
        candidates = await self.search_perfume(brand, perfume_name)

        for candidate in candidates:
            try:
                raw_product = await self.fetch_product(candidate)
                offers.extend(await self.parse_product(raw_product))
            except Exception:  # noqa: BLE001 - isolate one candidate's failure from the rest
                logger.warning("%s: failed to fetch/parse candidate %r", self.store_slug, candidate, exc_info=True)

        return offers

    @abstractmethod
    async def search_perfume(self, brand: str, perfume_name: str) -> list[Any]:
        """Search the store and return candidate product references (URLs,
        search-result fragments, etc.) - not yet full offers."""

    @abstractmethod
    async def fetch_product(self, candidate: Any) -> Any:
        """Fetch whatever raw data (HTML/JSON) is needed to parse the
        candidate into one or more ScrapedOffer instances."""

    @abstractmethod
    async def parse_product(self, raw_product: Any) -> list[ScrapedOffer]:
        """Parse raw product data into normalized ScrapedOffer instance(s) -
        a single product page can yield multiple offers (one per variant)."""
