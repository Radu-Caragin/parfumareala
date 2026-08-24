"""Tests for BaseScraper HTTP mechanics: retries, rate limiting, error
mapping. Uses httpx.MockTransport so no real network calls are made.
"""

import asyncio
import time

import httpx
import pytest

from app.config.settings import Settings
from app.scrapers.base import BaseScraper
from app.scrapers.exceptions import RequestError


class _DummyScraper(BaseScraper):
    store_name = "Dummy Store"
    store_slug = "dummy"
    base_url = "https://example.test"

    async def search_perfume(self, brand, perfume_name):
        return []

    async def fetch_product(self, candidate):
        return None

    async def parse_product(self, raw_product):
        return []


def _test_settings(**overrides) -> Settings:
    defaults = dict(REQUEST_TIMEOUT=5.0, REQUEST_DELAY=0.0, MAX_RETRIES=3, USER_AGENT="test-agent")
    defaults.update(overrides)
    return Settings(**defaults)


def test_successful_request_returns_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    async def run():
        async with _DummyScraper(settings=_test_settings(), transport=httpx.MockTransport(handler)) as scraper:
            response = await scraper.get("/search")
            assert response.json() == {"ok": True}

    asyncio.run(run())


def test_retries_then_succeeds():
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 3:
            return httpx.Response(500)
        return httpx.Response(200, json={"ok": True})

    async def run():
        async with _DummyScraper(settings=_test_settings(), transport=httpx.MockTransport(handler)) as scraper:
            response = await scraper.get("/search")
            assert response.json() == {"ok": True}

    asyncio.run(run())
    assert attempts["count"] == 3


def test_404_fails_fast_without_retrying():
    # A 404 is a definitive answer, not a transient failure - retrying it
    # only wastes time (a lot of it, on a store with a real crawl-delay)
    # without ever changing the outcome.
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(404)

    async def run():
        settings = _test_settings(MAX_RETRIES=3)
        async with _DummyScraper(settings=settings, transport=httpx.MockTransport(handler)) as scraper:
            with pytest.raises(RequestError):
                await scraper.get("/missing")

    asyncio.run(run())
    assert attempts["count"] == 1


def test_429_still_retries():
    # Unlike a plain 404, a 429 (rate limited) is worth retrying - the
    # server is explicitly asking to slow down and try again.
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 2:
            return httpx.Response(429)
        return httpx.Response(200, json={"ok": True})

    async def run():
        settings = _test_settings(MAX_RETRIES=3)
        async with _DummyScraper(settings=settings, transport=httpx.MockTransport(handler)) as scraper:
            response = await scraper.get("/rate-limited")
            assert response.json() == {"ok": True}

    asyncio.run(run())
    assert attempts["count"] == 2


def test_exhausted_retries_raise_request_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    async def run():
        settings = _test_settings(MAX_RETRIES=2)
        async with _DummyScraper(settings=settings, transport=httpx.MockTransport(handler)) as scraper:
            with pytest.raises(RequestError):
                await scraper.get("/search")

    asyncio.run(run())


def test_rate_limit_delays_consecutive_requests():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    async def run():
        settings = _test_settings(REQUEST_DELAY=0.2)
        async with _DummyScraper(settings=settings, transport=httpx.MockTransport(handler)) as scraper:
            start = time.monotonic()
            await scraper.get("/a")
            await scraper.get("/b")
            return time.monotonic() - start

    elapsed = asyncio.run(run())
    assert elapsed >= 0.2


def test_min_request_delay_overrides_a_lower_global_setting():
    # A store with a stricter robots.txt Crawl-delay (e.g. 10s) must never
    # be throttled down to the global REQUEST_DELAY if that's lower.
    class _StrictDelayScraper(_DummyScraper):
        min_request_delay = 0.2

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    async def run():
        settings = _test_settings(REQUEST_DELAY=0.0)
        async with _StrictDelayScraper(settings=settings, transport=httpx.MockTransport(handler)) as scraper:
            start = time.monotonic()
            await scraper.get("/a")
            await scraper.get("/b")
            return time.monotonic() - start

    elapsed = asyncio.run(run())
    assert elapsed >= 0.2


def test_min_request_delay_never_shortens_a_higher_global_setting():
    class _StrictDelayScraper(_DummyScraper):
        min_request_delay = 0.05

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    async def run():
        settings = _test_settings(REQUEST_DELAY=0.2)
        async with _StrictDelayScraper(settings=settings, transport=httpx.MockTransport(handler)) as scraper:
            start = time.monotonic()
            await scraper.get("/a")
            await scraper.get("/b")
            return time.monotonic() - start

    elapsed = asyncio.run(run())
    assert elapsed >= 0.2


def test_discover_offers_orchestrates_search_fetch_parse():
    from app.schemas.scraping import ScrapedOffer

    class _RecordingScraper(BaseScraper):
        store_name = "Recording Store"
        store_slug = "recording"
        base_url = "https://example.test"

        async def search_perfume(self, brand, perfume_name):
            return ["candidate-1", "candidate-2"]

        async def fetch_product(self, candidate):
            return candidate

        async def parse_product(self, raw_product):
            return [
                ScrapedOffer(
                    store_slug=self.store_slug,
                    raw_title=f"Offer from {raw_product}",
                    product_url=f"https://example.test/{raw_product}",
                    availability="in_stock",
                )
            ]

    async def run():
        async with _RecordingScraper(settings=_test_settings()) as scraper:
            return await scraper.discover_offers("Xerjoff", "Erba Gold")

    offers = asyncio.run(run())
    assert len(offers) == 2
    assert {o.raw_title for o in offers} == {"Offer from candidate-1", "Offer from candidate-2"}


def test_discover_offers_isolates_one_candidate_failure_from_the_rest():
    # A stale candidate URL (e.g. from a sitemap that's drifted out of
    # date) failing to fetch must not discard offers already found from
    # other candidates that did succeed.
    from app.schemas.scraping import ScrapedOffer
    from app.scrapers.exceptions import RequestError

    class _PartiallyFailingScraper(BaseScraper):
        store_name = "Partially Failing Store"
        store_slug = "partially-failing"
        base_url = "https://example.test"

        async def search_perfume(self, brand, perfume_name):
            return ["good-candidate", "stale-candidate"]

        async def fetch_product(self, candidate):
            if candidate == "stale-candidate":
                raise RequestError("404 for stale-candidate")
            return candidate

        async def parse_product(self, raw_product):
            return [
                ScrapedOffer(
                    store_slug=self.store_slug,
                    raw_title=f"Offer from {raw_product}",
                    product_url=f"https://example.test/{raw_product}",
                    availability="in_stock",
                )
            ]

    async def run():
        async with _PartiallyFailingScraper(settings=_test_settings()) as scraper:
            return await scraper.discover_offers("Xerjoff", "Erba Gold")

    offers = asyncio.run(run())
    assert len(offers) == 1
    assert offers[0].raw_title == "Offer from good-candidate"
