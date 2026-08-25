"""Base class for scrapers whose target site fingerprints the TLS/HTTP
handshake itself (Cloudflare Bot Management or similar) and challenges
plain httpx outright, regardless of headers sent at the application
layer - first diagnosed on Vivantis.ro (see its module docstring for the
full investigation: curl succeeded while httpx was served a
`cf-mitigated: challenge` response, on the very first request, from the
same machine at the same moment).

Uses curl_cffi (Chrome TLS-fingerprint impersonation) as the transport
instead of httpx, but keeps the exact same rate-limiting/retry contract
as BaseScraper.request() - same wait-then-retry loop, same fail-fast on
a definitive 4xx (other than 429) instead of wasting retries on an
answer that won't change - so a store scraper built on this behaves
identically to an httpx-based one from every other scraper method's
point of view (search_perfume/fetch_product/parse_product never need to
know or care which transport is underneath).
"""

import asyncio
import logging
import time
from typing import Any

from curl_cffi.requests import AsyncSession, Response
from curl_cffi.requests.exceptions import HTTPError as CurlHTTPError
from curl_cffi.requests.exceptions import RequestException as CurlRequestException

from app.scrapers.base import BaseScraper
from app.scrapers.exceptions import RequestError

logger = logging.getLogger(__name__)


class CurlCffiScraper(BaseScraper):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._curl_session = AsyncSession(
            impersonate="chrome",
            base_url=self.base_url,
            headers={"User-Agent": self._settings.USER_AGENT},
        )

    async def __aexit__(self, *exc_info: object) -> None:
        await self._curl_session.close()
        await super().__aexit__(*exc_info)

    async def request(self, method: str, url: str, **kwargs: Any) -> Response:
        # Locked for the same reason as BaseScraper.request() - a pooled
        # instance (app/scrapers/pool.py) can be reached by two
        # overlapping checks at once.
        async with self._request_lock:
            await self._wait_for_rate_limit()

            last_error: Exception | None = None
            for attempt in range(1, self._settings.MAX_RETRIES + 1):
                try:
                    response = await self._curl_session.request(
                        method, url, timeout=self._settings.REQUEST_TIMEOUT, **kwargs
                    )
                    self._last_request_at = time.monotonic()
                    response.raise_for_status()
                    return response
                except CurlHTTPError as exc:
                    last_error = exc
                    status_code = exc.response.status_code if exc.response is not None else None
                    logger.warning(
                        "%s: HTTP %s on attempt %s/%s for %s",
                        self.store_slug, status_code, attempt, self._settings.MAX_RETRIES, url,
                    )
                    if status_code is not None and 400 <= status_code < 500 and status_code != 429:
                        break
                except CurlRequestException as exc:
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
