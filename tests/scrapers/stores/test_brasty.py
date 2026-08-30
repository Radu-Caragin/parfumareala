"""Tests for BrastyScraper, using a saved JSON fixture (real structure,
trimmed) via httpx.MockTransport - no live requests are made.
"""

import asyncio
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from app.config.settings import Settings
from app.scrapers.exceptions import ParsingError
from app.scrapers.registry import get_scraper_class
from app.scrapers.stores.brasty import BrastyScraper

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures" / "brasty"


def _fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def _handler(requested: list[str], *, fixture_name: str = "suggest_dior_sauvage.json"):
    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if urlparse(str(request.url)).path != "/produkty/naseptavac":
            return httpx.Response(404, text="not found")
        return httpx.Response(200, text=_fixture(fixture_name))

    return handler


def _test_settings(**overrides) -> Settings:
    defaults = dict(REQUEST_TIMEOUT=5.0, REQUEST_DELAY=0.0, MAX_RETRIES=1, USER_AGENT="test-agent")
    defaults.update(overrides)
    return Settings(**defaults)


def test_registered_in_scraper_registry():
    assert get_scraper_class("brasty") is BrastyScraper


def test_search_perfume_queries_suggester_with_brand_and_name():
    requested: list[str] = []

    async def run():
        async with BrastyScraper(
            settings=_test_settings(), transport=httpx.MockTransport(_handler(requested))
        ) as scraper:
            return await scraper.search_perfume("Dior", "Sauvage")

    candidates = asyncio.run(run())

    assert len(requested) == 1
    query_params = parse_qs(urlparse(requested[0]).query)
    assert query_params["text"] == ["Dior Sauvage"]

    titles = {c.raw_title for c in candidates}
    assert "Dior (Christian Dior) Sauvage Parfum bărbați 200 ml" in titles
    assert "Dior (Christian Dior) Sauvage Eau de Toilette bărbați 100 ml" in titles
    # Same brand, different product line - must not pass the name filter.
    assert "Dior (Christian Dior) Eau Sauvage deostick bărbați 75 ml" not in titles
    # A completely different brand's product must not pass the brand
    # pre-check, even though the suggester itself returned it.
    assert "Nishane Ani Extrait de Parfum unisex 50 ml" not in titles


def test_search_perfume_handles_brand_alias_in_suggester_name():
    # Regression: Brasty's own brand *directory* only lists "Christian
    # Dior", not "Dior" - confirmed live, this made the old category-
    # browsing version of this scraper resolve no brand at all for
    # "Dior". The suggester's own `name` field embeds the alias instead
    # ("Dior (Christian Dior) Sauvage ..."), so searching for "Dior" must
    # still match it.
    async def run():
        async with BrastyScraper(
            settings=_test_settings(), transport=httpx.MockTransport(_handler([]))
        ) as scraper:
            return await scraper.discover_offers("Dior", "Sauvage")

    offers = asyncio.run(run())

    by_volume = {o.volume_ml: o for o in offers}
    assert by_volume[200].perfume_name == "sauvage"
    assert by_volume[200].availability == "in_stock"
    assert by_volume[100].availability == "out_of_stock"


def test_parse_price_handles_thousands_dot_and_nbsp():
    assert BrastyScraper._parse_price("1.013 lei") == Decimal("1013")
    assert BrastyScraper._parse_price("133 lei") == Decimal("133")
    assert BrastyScraper._parse_price("26\xa0lei") == Decimal("26")


def test_discover_offers_end_to_end_against_fixture():
    async def run():
        async with BrastyScraper(
            settings=_test_settings(), transport=httpx.MockTransport(_handler([]))
        ) as scraper:
            return await scraper.discover_offers("Dior", "Sauvage")

    offers = asyncio.run(run())

    # No detail-page fetch happens for this store (see module docstring) -
    # discover_offers must still yield fully-formed offers straight from
    # the suggester response alone.
    assert len(offers) == 2
    by_volume = {o.volume_ml: o for o in offers}
    assert by_volume[200].price == Decimal("1013")
    assert by_volume[200].concentration == "Parfum"
    assert by_volume[100].price == Decimal("493")
    assert by_volume[100].concentration == "EDT"


def test_search_perfume_raises_when_suggester_response_unrecognized():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text='{"unexpected": "shape"}')

    async def run():
        async with BrastyScraper(
            settings=_test_settings(), transport=httpx.MockTransport(handler)
        ) as scraper:
            return await scraper.search_perfume("Dior", "Sauvage")

    try:
        asyncio.run(run())
        assert False, "expected ParsingError"
    except ParsingError:
        pass


def test_search_perfume_raises_when_suggester_response_not_json():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    async def run():
        async with BrastyScraper(
            settings=_test_settings(), transport=httpx.MockTransport(handler)
        ) as scraper:
            return await scraper.search_perfume("Dior", "Sauvage")

    try:
        asyncio.run(run())
        assert False, "expected ParsingError"
    except ParsingError:
        pass
