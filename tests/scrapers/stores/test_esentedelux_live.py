"""Optional live tests against the real EsenteDeLux.ro website.

Excluded from the default `pytest` run (see pytest.ini: -m "not live").
Run explicitly with:

    pytest -m live tests/scrapers/stores/test_esentedelux_live.py
"""

import asyncio

import pytest

from app.scrapers.stores.esentedelux import EsenteDeLuxScraper


@pytest.mark.live
def test_brand_directory_loads_from_real_site():
    async def run():
        async with EsenteDeLuxScraper() as scraper:
            return await scraper._load_brand_directory()

    directory = asyncio.run(run())

    assert "versace" in directory
    assert "/brand/" in directory["versace"]


@pytest.mark.live
def test_discover_offers_against_real_site():
    async def run():
        async with EsenteDeLuxScraper() as scraper:
            return await scraper.discover_offers("Versace", "Woman")

    offers = asyncio.run(run())

    assert len(offers) > 0
    for offer in offers:
        assert offer.price is None or offer.price > 0
        assert offer.availability in ("in_stock", "out_of_stock")
