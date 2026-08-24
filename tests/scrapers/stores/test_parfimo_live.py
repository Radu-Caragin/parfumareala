"""Optional live tests against the real Parfimo.ro website.

Excluded from the default `pytest` run (see pytest.ini: -m "not live").
Run explicitly with:

    pytest -m live tests/scrapers/stores/test_parfimo_live.py
"""

import asyncio

import pytest

from app.scrapers.stores.parfimo import ParfimoScraper


@pytest.mark.live
def test_search_perfume_against_real_site():
    async def run():
        async with ParfimoScraper() as scraper:
            return await scraper.search_perfume("Xerjoff", "Erba Gold")

    candidates = asyncio.run(run())

    assert len(candidates) > 0
    assert all(c.brand.lower() == "xerjoff" for c in candidates)


@pytest.mark.live
def test_discover_offers_against_real_site():
    async def run():
        async with ParfimoScraper() as scraper:
            return await scraper.discover_offers("Xerjoff", "Erba Gold")

    offers = asyncio.run(run())

    assert len(offers) > 0
    for offer in offers:
        assert offer.price is None or offer.price > 0
        assert offer.availability in ("in_stock", "out_of_stock")
