"""Tests for app.scrapers.pool - the process-lifetime scraper pool
scraping_service uses instead of a fresh scraper per (perfume, store)
check."""

import asyncio

import pytest

from app.database.models import Store
from app.scrapers import pool as scraper_pool
from app.scrapers.base import BaseScraper
from app.scrapers.registry import SCRAPER_REGISTRY


class _FakeScraper(BaseScraper):
    store_name = "Fake Store"
    store_slug = "pool-fake-store"
    base_url = "https://fake.test"

    async def search_perfume(self, brand, perfume_name):
        return []

    async def fetch_product(self, candidate):
        return None

    async def parse_product(self, raw_product):
        return []


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    SCRAPER_REGISTRY.pop("pool-fake-store", None)
    scraper_pool.reset_pool()


def _store() -> Store:
    return Store(
        id=1, name="Fake Store", slug="pool-fake-store", base_url="https://fake.test",
        enabled=True, scraper_identifier="pool-fake-store",
    )


def test_get_scraper_returns_none_when_not_registered():
    async def run():
        return await scraper_pool.get_scraper(_store())

    assert asyncio.run(run()) is None


def test_get_scraper_creates_and_reuses_the_same_instance():
    SCRAPER_REGISTRY["pool-fake-store"] = _FakeScraper

    async def run():
        first = await scraper_pool.get_scraper(_store())
        second = await scraper_pool.get_scraper(_store())
        return first, second

    first, second = asyncio.run(run())
    assert first is second
    assert isinstance(first, _FakeScraper)


def test_reset_pool_drops_the_cached_instance():
    SCRAPER_REGISTRY["pool-fake-store"] = _FakeScraper

    async def run():
        return await scraper_pool.get_scraper(_store())

    first = asyncio.run(run())
    scraper_pool.reset_pool()
    second = asyncio.run(run())

    assert first is not second


def test_close_all_clears_the_pool():
    SCRAPER_REGISTRY["pool-fake-store"] = _FakeScraper

    async def run():
        before = await scraper_pool.get_scraper(_store())
        await scraper_pool.close_all()
        after = await scraper_pool.get_scraper(_store())
        return before, after

    before, after = asyncio.run(run())
    assert before is not after  # close_all() forced a fresh instance to be built
