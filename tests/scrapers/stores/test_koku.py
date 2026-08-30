"""Tests for KokuScraper, using saved HTML fixtures (real structure,
trimmed) via httpx.MockTransport - no live requests are made.
"""

import asyncio
from decimal import Decimal
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from app.config.settings import Settings
from app.scrapers.exceptions import ParsingError
from app.scrapers.registry import get_scraper_class
from app.scrapers.stores.koku import KokuScraper, _FetchedProduct, _ListingCandidate

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures" / "koku"

_ROUTES = {
    "https://www.koku.ro/parfumuri": "brand_directory.html",
    "https://www.koku.ro/parfumuri?brand=13192&page=1": "category_antonio_page1.html",
    "https://www.koku.ro/antonio-banderas-king-of-seduction-absolute-apa-de-toaleta": "product_king_of_seduction.html",
}


def _fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def _handler(requested: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        requested.append(url)
        fixture_name = _ROUTES.get(url)
        if fixture_name is None:
            return httpx.Response(404, text="not found")
        return httpx.Response(200, text=_fixture(fixture_name))

    return handler


def _test_settings(**overrides) -> Settings:
    defaults = dict(REQUEST_TIMEOUT=5.0, REQUEST_DELAY=0.0, MAX_RETRIES=1, USER_AGENT="test-agent")
    defaults.update(overrides)
    return Settings(**defaults)


def test_registered_in_scraper_registry():
    assert get_scraper_class("koku") is KokuScraper


def test_search_perfume_resolves_brand_id_and_filters_by_name():
    requested: list[str] = []

    async def run():
        async with KokuScraper(
            settings=_test_settings(), transport=httpx.MockTransport(_handler(requested))
        ) as scraper:
            return await scraper.search_perfume("Antonio Banderas", "King Of Seduction Absolute")

    candidates = asyncio.run(run())

    assert "https://www.koku.ro/parfumuri" in requested
    assert "https://www.koku.ro/parfumuri?brand=13192&page=1" in requested

    urls = {c.product_url for c in candidates}
    assert "https://www.koku.ro/antonio-banderas-king-of-seduction-absolute-apa-de-toaleta" in urls
    # A different perfume from the same brand must not pass the name filter.
    assert "https://www.koku.ro/antonio-banderas-blue-seduction-for-woman-apa-de-toaleta-1" not in urls


def test_search_perfume_resolves_brand_via_confirmed_alias():
    async def run():
        async with KokuScraper(
            settings=_test_settings(), transport=httpx.MockTransport(_handler([]))
        ) as scraper:
            return await scraper._get_brand_id("Dior")

    assert asyncio.run(run()) == "99001"


def test_is_plausible_candidate_strips_full_alias_from_slug_not_just_target_brand():
    # Regression: this store's product URLs spell the brand under its
    # confirmed alias, not the name this app calls it (e.g.
    # ".../apa-de-toaleta-christian-dior-sauvage" for a perfume monitored
    # as brand "Dior", confirmed live) - stripping only the literal
    # target brand "dior" left "christian" behind as an unrelated leftover
    # token, dragging the fuzzy-match score for "sauvage" down for no
    # real reason.
    candidate = _ListingCandidate(
        product_url="https://www.koku.ro/apa-de-toaleta-christian-dior-sauvage", brand="Dior"
    )

    assert KokuScraper._is_plausible_candidate(candidate, "Dior", "Sauvage", ambiguous_threshold=70)


def test_search_perfume_returns_empty_for_unknown_brand():
    async def run():
        async with KokuScraper(
            settings=_test_settings(), transport=httpx.MockTransport(_handler([]))
        ) as scraper:
            return await scraper.search_perfume("Some Unknown Brand", "Whatever")

    assert asyncio.run(run()) == []


def test_parse_product_reads_every_size_variant_from_one_fetch():
    candidate = _ListingCandidate(
        product_url="https://www.koku.ro/antonio-banderas-king-of-seduction-absolute-apa-de-toaleta",
        brand="Antonio Banderas",
    )
    soup = BeautifulSoup(_fixture("product_king_of_seduction.html"), "lxml")

    async def run():
        async with KokuScraper(settings=_test_settings()) as scraper:
            return await scraper.parse_product(_FetchedProduct(candidate=candidate, soup=soup))

    offers = asyncio.run(run())

    assert len(offers) == 3
    by_volume = {o.volume_ml: o for o in offers}

    # Regression: tester-ness is per-variant, read from that variant's own
    # title text - the page's <h1> alone (which always reflects whichever
    # variant happens to be selected by default) would have mislabeled
    # every size as a tester here, since the default is the 100ml tester.
    assert by_volume[100].tester is True
    assert by_volume[100].price == Decimal("102.00")
    assert by_volume[100].availability == "in_stock"

    assert by_volume[200].tester is False
    assert by_volume[200].price == Decimal("148.00")
    assert by_volume[200].availability == "in_stock"

    assert by_volume[30].availability == "out_of_stock"

    assert all(o.concentration == "EDT" for o in offers)
    assert all(o.perfume_name == "king of seduction absolute" for o in offers)


def test_load_brand_directory_raises_when_page_structure_unrecognized():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body>No brand filter here</body></html>")

    async def run():
        async with KokuScraper(
            settings=_test_settings(), transport=httpx.MockTransport(handler)
        ) as scraper:
            return await scraper._load_brand_directory()

    try:
        asyncio.run(run())
        assert False, "expected ParsingError"
    except ParsingError:
        pass
