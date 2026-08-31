"""Tests for FragranzaScraper, using saved HTML fixtures (real structure,
trimmed) via httpx.MockTransport - no live requests are made.
"""

import asyncio
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup

from app.config.settings import Settings
from app.scrapers.exceptions import ParsingError
from app.scrapers.registry import get_scraper_class
from app.scrapers.stores.fragranza import FragranzaScraper, _FetchedProduct, _ListingCandidate

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures" / "fragranza"

_ROUTES = {
    "https://fragranza.ro/brands": "brands.html",
    "https://fragranza.ro/xerjoff": "category_xerjoff_page1.html",
    "https://fragranza.ro/xerjoff?page=2": "category_xerjoff_page2.html",
    "https://fragranza.ro/xerjoff-torino-21-apa-de-parfum-unisex-edp": "product_torino21.html",
    "https://fragranza.ro/xerjoff-torino-21-eau-de-toilette-edt": "product_single_variant.html",
    "https://fragranza.ro/xerjoff-erba-pura-tester-edp": "product_single_variant.html",
    "https://fragranza.ro/xerjoff-naxos-apa-de-parfum-unisex-edp": "product_single_variant.html",
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
    assert get_scraper_class("fragranza") is FragranzaScraper


def test_search_perfume_paginates_and_filters_by_name():
    requested: list[str] = []

    async def run():
        async with FragranzaScraper(settings=_test_settings(), transport=httpx.MockTransport(_handler(requested))) as scraper:
            return await scraper.search_perfume("Xerjoff", "Torino 21")

    candidates = asyncio.run(run())

    names = {c.name for c in candidates}
    assert "Torino 21" in names
    assert "Erba Pura" not in names  # different name - filtered before fetching
    assert "Naxos" not in names
    assert "https://fragranza.ro/xerjoff?page=2" in requested  # pagination followed


def test_is_plausible_candidate_strips_concentration_baked_into_name_field():
    # Regression: for most product lines .product-name-middle is a bare
    # name ("Erba Gold"), but for "Extrait de Parfum" lines the site bakes
    # the concentration into that same field ("Ani Extrait De Parfum").
    # Comparing that raw against a short target name like "Ani" used to
    # tank the fuzzy score (~25, well under threshold) and silently drop
    # the real product before it was ever fetched.
    assert FragranzaScraper._is_plausible_candidate(
        "Nishane", "Ani Extrait De Parfum", "Nishane", "Ani", ambiguous_threshold=70
    )
    # A different, unrelated Nishane fragrance must never pass this
    # permissive pre-filter at all - not even a shared brand and this
    # store's own concentration-baked-into-name-field quirk are enough.
    assert FragranzaScraper._is_plausible_candidate(
        "Nishane", "Hacivat Extrait De Parfum", "Nishane", "Ani", ambiguous_threshold=70
    ) is False


def test_is_plausible_candidate_lets_flanker_through_the_cheap_prefilter_but_not_as_exact():
    # "Ani X" is a real, different Nishane fragrance from "Ani" (confirmed
    # live elsewhere in this project) - this permissive discovery-stage
    # pre-filter isn't meant to make that call (it never was: see this
    # function's own docstring), so it correctly lets it through here.
    # names_plausibly_match's word-set containment fallback (added for
    # Xerjoff's "Naxos"/"XJ 1861 Naxos") also, deliberately, doesn't
    # weaken this: "ani x" already scores 75 against "ani" on the plain
    # fuzzy check alone, above ambiguous_threshold=70 - this candidate was
    # always going to reach the review queue at the real, configured
    # threshold, never silently dropped here. What actually guarantees
    # "Ani X" is never auto-matched to monitored "Ani" is
    # matching_service.validate_candidate downstream (see
    # test_matching_service.py's flanker test), not this cheap check.
    assert FragranzaScraper._is_plausible_candidate(
        "Nishane", "Ani X Extrait De Parfum", "Nishane", "Ani", ambiguous_threshold=70
    ) is True


def test_parse_product_cleans_concentration_out_of_perfume_name():
    # Same root cause as the plausibility-filter regression above, but for
    # the final ScrapedOffer.perfume_name - matching_service compares this
    # field against the monitored perfume's bare name, so it must be
    # cleaned the same way, not just the discovery-stage pre-filter.
    candidate = _ListingCandidate(
        product_url="https://fragranza.ro/xerjoff-erba-pura-tester-edp",
        brand="Xerjoff",
        name="Erba Pura Extrait De Parfum",
        type_text="Apa de parfum Tester EDP",
    )
    soup = BeautifulSoup(_fixture("product_single_variant.html"), "lxml")

    async def run():
        async with FragranzaScraper(settings=_test_settings()) as scraper:
            return await scraper.parse_product(_FetchedProduct(candidate=candidate, soup=soup))

    offers = asyncio.run(run())

    assert len(offers) == 1
    assert offers[0].perfume_name == "erba pura"


def test_search_perfume_unknown_brand_returns_empty():
    async def run():
        async with FragranzaScraper(settings=_test_settings(), transport=httpx.MockTransport(_handler([]))) as scraper:
            return await scraper.search_perfume("Nonexistent Brand", "Whatever")

    assert asyncio.run(run()) == []


def test_discover_offers_parses_combinations_with_price_and_stock():
    async def run():
        async with FragranzaScraper(settings=_test_settings(), transport=httpx.MockTransport(_handler([]))) as scraper:
            return await scraper.discover_offers("Xerjoff", "Torino 21")

    offers = asyncio.run(run())

    edp_offers = [o for o in offers if o.concentration == "EDP"]
    assert len(edp_offers) == 2

    by_volume = {o.volume_ml: o for o in edp_offers}
    assert by_volume[50].price == Decimal("625.99")
    assert by_volume[50].availability == "in_stock"
    assert by_volume[50].tester is False
    assert by_volume[50].store_product_identifier == "37"

    assert by_volume[100].price == Decimal("860.99")
    assert by_volume[100].old_price == Decimal("929.99")
    assert by_volume[100].availability == "in_stock"


def test_parse_product_out_of_stock_combination():
    candidate = _ListingCandidate(
        product_url="https://fragranza.ro/some-out-of-stock-product",
        brand="Xerjoff",
        name="Some Perfume",
        type_text="Apa de parfum EDP",
    )
    soup = BeautifulSoup(_fixture("product_out_of_stock.html"), "lxml")

    async def run():
        async with FragranzaScraper(settings=_test_settings()) as scraper:
            return await scraper.parse_product(_FetchedProduct(candidate=candidate, soup=soup))

    offers = asyncio.run(run())

    assert len(offers) == 1
    assert offers[0].availability == "out_of_stock"
    assert offers[0].volume_ml == 100


def test_parse_product_falls_back_to_json_ld_when_no_combinations():
    candidate = _ListingCandidate(
        product_url="https://fragranza.ro/xerjoff-erba-pura-tester-edp",
        brand="Xerjoff",
        name="Erba Pura",
        type_text="Apa de parfum Tester EDP",
    )
    soup = BeautifulSoup(_fixture("product_single_variant.html"), "lxml")

    async def run():
        async with FragranzaScraper(settings=_test_settings()) as scraper:
            return await scraper.parse_product(_FetchedProduct(candidate=candidate, soup=soup))

    offers = asyncio.run(run())

    assert len(offers) == 1
    assert offers[0].price == Decimal("399.00")
    assert offers[0].tester is True
    assert offers[0].concentration == "EDP"
    assert offers[0].store_product_identifier == "80012"
    # Single-combination products render no radio buttons at all, so the
    # volume is only recoverable from the JSON-LD offer URL's fragment
    # (".../product#/45-volum-50_ml") - see FragranzaScraper._parse_single_variant.
    assert offers[0].volume_ml == 50


def test_load_brand_directory_raises_parsing_error_when_structure_unrecognized():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body>Site redesigned, no brand list here</body></html>")

    async def run():
        async with FragranzaScraper(settings=_test_settings(), transport=httpx.MockTransport(handler)) as scraper:
            await scraper._load_brand_directory()

    with pytest.raises(ParsingError):
        asyncio.run(run())


def test_search_perfume_raises_parsing_error_when_category_page_structure_unrecognized():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://fragranza.ro/brands":
            return httpx.Response(200, text=_fixture("brands.html"))
        # Category page 1 with no #js-product-list at all - site markup changed.
        return httpx.Response(200, text="<html><body>Nothing recognizable here</body></html>")

    async def run():
        async with FragranzaScraper(settings=_test_settings(), transport=httpx.MockTransport(handler)) as scraper:
            await scraper.search_perfume("Xerjoff", "Torino 21")

    with pytest.raises(ParsingError):
        asyncio.run(run())
