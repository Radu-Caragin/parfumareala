"""Tests for ParfumatScraper, using saved HTML fixtures (real structure,
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
from app.scrapers.stores.parfumat import ParfumatScraper

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures" / "parfumat"

_ROUTES = {
    "https://parfumat.ro/parfumuri-de-brand": "brand_directory.html",
    "https://parfumat.ro/brand/xerjoff": "category_xerjoff_page1.html",
    "https://parfumat.ro/brand/xerjoff?page=2": "category_xerjoff_page2.html",
    "https://parfumat.ro/brand/paris-corner": "category_paris_corner_page1.html",
    "https://parfumat.ro/paris-corner-mawj-moscow-mule-unisex-100-ml": "product_mawj_moscow_mule_detail.html",
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
    assert get_scraper_class("parfumat") is ParfumatScraper


def test_search_perfume_resolves_brand_slug_and_paginates():
    requested: list[str] = []

    async def run():
        async with ParfumatScraper(
            settings=_test_settings(), transport=httpx.MockTransport(_handler(requested))
        ) as scraper:
            return await scraper.search_perfume("Xerjoff", "Erba Gold")

    candidates = asyncio.run(run())

    # Brand directory resolved "Xerjoff" -> the "xerjoff" slug (not guessed)
    # and both category pages were fetched (pagination followed).
    assert "https://parfumat.ro/parfumuri-de-brand" in requested
    assert "https://parfumat.ro/brand/xerjoff" in requested
    assert "https://parfumat.ro/brand/xerjoff?page=2" in requested

    titles = {c.raw_title for c in candidates}
    assert "Xerjoff Erba Gold Apa de Parfum 100ml" in titles
    assert "Xerjoff Erba Gold Apa de Parfum 50ml" in titles
    assert "Xerjoff Erba Gold Tester Apa de Parfum 100ml" in titles
    # A different Xerjoff perfume on page 2 must not pass the name filter.
    assert "Xerjoff Naxos Apa de Parfum 100ml" not in titles


def test_search_perfume_returns_empty_for_unknown_brand():
    async def run():
        async with ParfumatScraper(
            settings=_test_settings(), transport=httpx.MockTransport(_handler([]))
        ) as scraper:
            return await scraper.search_perfume("Some Unknown Brand", "Whatever")

    candidates = asyncio.run(run())

    assert candidates == []


def test_get_brand_slug_resolves_dior_via_confirmed_alias():
    # Regression: Parfumat's brand directory only ever lists "Christian
    # Dior" (confirmed live) - looking up "Dior" must still resolve via
    # the shared alias table instead of coming back empty.
    async def run():
        async with ParfumatScraper(
            settings=_test_settings(), transport=httpx.MockTransport(_handler([]))
        ) as scraper:
            return await scraper._get_brand_slug("Dior")

    assert asyncio.run(run()) == "christian-dior"


def test_parse_listing_item_reads_price_old_price_and_availability():
    soup = BeautifulSoup(_fixture("category_xerjoff_page1.html"), "lxml")
    items = soup.select("article.product-miniature")
    by_id = {item["data-id-product"]: item for item in items}

    discounted = ParfumatScraper._parse_listing_item(by_id["30001"])
    assert discounted.price == Decimal("999")
    assert discounted.old_price == Decimal("1099.00")
    assert discounted.availability == "in_stock"

    no_discount = ParfumatScraper._parse_listing_item(by_id["30002"])
    assert no_discount.price == Decimal("620")
    assert no_discount.old_price is None
    assert no_discount.availability == "in_stock"  # "ultimele 2 produse" is still in stock

    sold_out = ParfumatScraper._parse_listing_item(by_id["30003"])
    assert sold_out.availability == "out_of_stock"


def test_discover_offers_end_to_end_against_fixtures():
    async def run():
        async with ParfumatScraper(
            settings=_test_settings(), transport=httpx.MockTransport(_handler([]))
        ) as scraper:
            return await scraper.discover_offers("Xerjoff", "Erba Gold")

    offers = asyncio.run(run())

    # No detail-page fetch happens for this store (see module docstring) -
    # discover_offers must still yield fully-formed offers straight from
    # the listing pass alone.
    by_volume = {o.volume_ml: o for o in offers if not o.tester}
    assert by_volume[100].price == Decimal("999")
    assert by_volume[100].old_price == Decimal("1099.00")
    assert by_volume[100].concentration == "EDP"
    assert by_volume[100].perfume_name == "erba gold"
    assert by_volume[50].price == Decimal("620")

    tester_offer = next(o for o in offers if o.tester)
    assert tester_offer.volume_ml == 100


def test_discover_offers_falls_back_to_detail_page_when_listing_title_lacks_concentration():
    # Regression: "Paris Corner, Mawj Moscow Mule, Unisex, 100 ml" has no
    # concentration wording anywhere in the listing title - confirmed
    # live, this made the offer get silently rejected downstream as
    # "missing_variant_fields" even though the store genuinely has it in
    # stock. The concentration only turns up in the detail page's
    # og:description meta tag, so fetch_product() must fall back to
    # fetching it precisely when (and only when) the listing alone
    # doesn't have an answer.
    requested: list[str] = []

    async def run():
        async with ParfumatScraper(
            settings=_test_settings(), transport=httpx.MockTransport(_handler(requested))
        ) as scraper:
            return await scraper.discover_offers("Paris Corner", "Mawj Moscow Mule")

    offers = asyncio.run(run())

    assert "https://parfumat.ro/paris-corner-mawj-moscow-mule-unisex-100-ml" in requested
    assert len(offers) == 1
    assert offers[0].concentration == "EDP"
    assert offers[0].perfume_name == "mawj moscow mule"
    assert offers[0].volume_ml == 100


def test_fetch_product_skips_detail_page_when_listing_title_has_concentration():
    # The common case (see module docstring) must stay fetch-free - only
    # the fallback above should ever hit the network a second time.
    requested: list[str] = []

    async def run():
        async with ParfumatScraper(
            settings=_test_settings(), transport=httpx.MockTransport(_handler(requested))
        ) as scraper:
            return await scraper.discover_offers("Xerjoff", "Erba Gold")

    asyncio.run(run())

    assert requested == [
        "https://parfumat.ro/parfumuri-de-brand",
        "https://parfumat.ro/brand/xerjoff",
        "https://parfumat.ro/brand/xerjoff?page=2",
    ]


def test_search_perfume_returns_empty_for_a_brand_with_no_products_yet():
    # Regression: a resolved brand slug here is not a guarantee of >=1
    # product, unlike Fragranza - the manufacturer facet this site's
    # brand directory is scraped from lists brands it has ever carried.
    # Confirmed live with "BDK Parfums": the category page renders
    # correctly (real, brand-titled page) with zero
    # article.product-miniature elements when nothing is currently
    # stocked - that must be treated as "no offers", not a parsing
    # failure.
    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://parfumat.ro/parfumuri-de-brand":
            return httpx.Response(200, text=_fixture("brand_directory.html"))
        return httpx.Response(200, text="<html><head><title>Lattafa</title></head><body>No products yet</body></html>")

    async def run():
        async with ParfumatScraper(
            settings=_test_settings(), transport=httpx.MockTransport(handler)
        ) as scraper:
            return await scraper.search_perfume("Lattafa", "Some New Release")

    assert asyncio.run(run()) == []


def test_load_brand_directory_raises_when_page_structure_unrecognized():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body>No manufacturer facet here</body></html>")

    async def run():
        async with ParfumatScraper(
            settings=_test_settings(), transport=httpx.MockTransport(handler)
        ) as scraper:
            return await scraper._load_brand_directory()

    try:
        asyncio.run(run())
        assert False, "expected ParsingError"
    except ParsingError:
        pass
