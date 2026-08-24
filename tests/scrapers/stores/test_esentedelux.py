"""Tests for EsenteDeLuxScraper, using saved HTML/JSON fixtures (real
structure, trimmed) via httpx.MockTransport - no live requests are made.

The AJAX combination-refresh endpoint is routed by inspecting the request's
query parameters (action / group[7]) rather than matching an exact URL
string, since dict key ordering isn't something tests should depend on.
"""

import asyncio
import json
from decimal import Decimal
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from app.config.settings import Settings
from app.scrapers.registry import get_scraper_class
from app.scrapers.stores.esentedelux import EsenteDeLuxScraper, _FetchedProduct, _SearchCandidate

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures" / "esentedelux"


def _fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def _handler(requested: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        path = request.url.path
        params = request.url.params

        if path == "/manufacturers":
            return httpx.Response(200, text=_fixture("manufacturers.html"))

        if path == "/brand/43-versace":
            if params.get("page") == "2":
                return httpx.Response(200, text=_fixture("category_empty_page.html"))
            return httpx.Response(200, text=_fixture("category_versace_page1.html"))

        if path == "/parfumuri-pentru-femei/1485-3514-versace-woman-eau-de-parfum-pentru-femei.html":
            if params.get("action") == "Refresh":
                volume_value = params.get("group[7]")
                if volume_value == "35":
                    return httpx.Response(200, text=_fixture("ajax_50ml.json"))
                if volume_value == "49":
                    return httpx.Response(200, text=_fixture("ajax_50ml_tester.json"))
                return httpx.Response(404, text="unexpected combination request")
            return httpx.Response(200, text=_fixture("product_versace_woman.html"))

        return httpx.Response(404, text="not found")

    return handler


def _test_settings(**overrides) -> Settings:
    defaults = dict(REQUEST_TIMEOUT=5.0, REQUEST_DELAY=0.0, MAX_RETRIES=1, USER_AGENT="test-agent")
    defaults.update(overrides)
    return Settings(**defaults)


def test_registered_in_scraper_registry():
    assert get_scraper_class("esentedelux") is EsenteDeLuxScraper


def test_search_perfume_filters_by_brand_and_name():
    requested: list[str] = []

    async def run():
        async with EsenteDeLuxScraper(
            settings=_test_settings(), transport=httpx.MockTransport(_handler(requested))
        ) as scraper:
            return await scraper.search_perfume("Versace", "Woman")

    candidates = asyncio.run(run())

    assert len(candidates) == 1
    assert candidates[0].core_name == "woman"
    assert candidates[0].brand == "Versace"
    # pagination followed, and the unrelated Ungaro product never matched
    assert any(u.endswith("page=2") for u in requested)


def test_search_perfume_unknown_brand_returns_empty():
    async def run():
        async with EsenteDeLuxScraper(
            settings=_test_settings(), transport=httpx.MockTransport(_handler([]))
        ) as scraper:
            return await scraper.search_perfume("Nonexistent Brand", "Whatever")

    assert asyncio.run(run()) == []


def test_discover_offers_fetches_all_volume_options_via_ajax():
    requested: list[str] = []

    async def run():
        async with EsenteDeLuxScraper(
            settings=_test_settings(), transport=httpx.MockTransport(_handler(requested))
        ) as scraper:
            return await scraper.discover_offers("Versace", "Woman")

    offers = asyncio.run(run())

    assert len(offers) == 3
    by_volume = {(o.volume_ml, o.tester): o for o in offers}

    # 30ml: default combination, price already on the initial page - no AJAX needed for it.
    default = by_volume[(30, False)]
    assert default.price == Decimal("99.00")
    assert default.availability == "in_stock"
    assert default.concentration == "EDP"

    # 50ml: fetched via the AJAX combination-refresh endpoint.
    normal_50 = by_volume[(50, False)]
    assert normal_50.price == Decimal("125.00")
    assert normal_50.availability == "in_stock"

    # 50ml Tester: also via AJAX, and its add-to-cart button was disabled.
    tester_offer = next(o for o in offers if o.tester)
    assert tester_offer.volume_ml == 50
    assert tester_offer.price == Decimal("79.00")
    assert tester_offer.availability == "out_of_stock"

    # confirms the AJAX endpoint was actually hit for the non-default options
    assert any("action=Refresh" in u and "group%5B7%5D=35" in u for u in requested)
    assert any("action=Refresh" in u and "group%5B7%5D=49" in u for u in requested)


def test_parse_product_returns_empty_when_no_variant_groups():
    candidate = _SearchCandidate(
        product_id=1,
        product_url="https://esentedelux.ro/some-product.html",
        brand="Versace",
        raw_title="Versace - Something",
        core_name="something",
    )
    soup = BeautifulSoup("<html><body>no variants here</body></html>", "lxml")

    async def run():
        async with EsenteDeLuxScraper(settings=_test_settings()) as scraper:
            return await scraper.parse_product(_FetchedProduct(candidate=candidate, soup=soup))

    assert asyncio.run(run()) == []


def test_ajax_json_fixtures_are_well_formed():
    # Sanity check the fixtures themselves parse as the shape the real
    # endpoint returns, so a fixture typo doesn't silently pass the tests
    # above via an unrelated 404 path.
    for name in ("ajax_50ml.json", "ajax_50ml_tester.json"):
        data = json.loads(_fixture(name))
        assert "product_prices" in data
        assert "product_add_to_cart" in data
