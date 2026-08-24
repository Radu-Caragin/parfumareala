"""Optional live tests against the real Fragranza.ro website.

Excluded from the default `pytest` run (see pytest.ini: -m "not live").
Run explicitly with:

    pytest -m live tests/scrapers/stores/test_fragranza_live.py

Useful for noticing when the site's markup changes and the fixture-based
unit tests in test_fragranza.py have drifted from reality.
"""

import asyncio

import pytest

from app.scrapers.stores.fragranza import FragranzaScraper


@pytest.mark.live
def test_brand_directory_loads_from_real_site():
    async def run():
        async with FragranzaScraper() as scraper:
            return await scraper._load_brand_directory()

    directory = asyncio.run(run())

    assert "xerjoff" in directory
    assert directory["xerjoff"].endswith("/xerjoff")


@pytest.mark.live
def test_discover_offers_against_real_site():
    async def run():
        async with FragranzaScraper() as scraper:
            return await scraper.discover_offers("Xerjoff", "Torino 21")

    offers = asyncio.run(run())

    assert len(offers) > 0
    for offer in offers:
        assert offer.price is None or offer.price > 0
        assert offer.availability in ("in_stock", "out_of_stock")
