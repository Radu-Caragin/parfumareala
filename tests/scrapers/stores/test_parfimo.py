"""Tests for ParfimoScraper, using saved HTML fixtures (real structure,
trimmed) via httpx.MockTransport - no live requests are made.
"""

import asyncio
from decimal import Decimal
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from app.config.settings import Settings
from app.scrapers.registry import get_scraper_class
from app.scrapers.stores.parfimo import ParfimoScraper, _FetchedProduct, _SearchCandidate

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures" / "parfimo"

_ROUTES = {
    "https://www.parfimo.ro/cautare/?search=Xerjoff+Erba+Gold": "search_erba_gold.html",
    "https://www.parfimo.ro/cautare/?search=Xerjoff+Erba+Gold&page=2": "search_empty_page.html",
    "https://www.parfimo.ro/xerjoff-erba-gold-apa-de-parfum-50-ml_z909839/": "product_erba_gold_50ml.html",
    "https://www.parfimo.ro/xerjoff-erba-gold-apa-de-parfum-100-ml_z940989/": "product_erba_gold_50ml.html",
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
    assert get_scraper_class("parfimo") is ParfimoScraper


def test_search_perfume_filters_by_brand_and_name():
    requested: list[str] = []

    async def run():
        async with ParfimoScraper(settings=_test_settings(), transport=httpx.MockTransport(_handler(requested))) as scraper:
            return await scraper.search_perfume("Xerjoff", "Erba Gold")

    candidates = asyncio.run(run())

    core_names = {c.core_name for c in candidates}
    assert "erba gold" in core_names
    # Dior Sauvage (wrong brand) must never pass the pre-filter.
    assert not any("sauvage" in name for name in core_names)
    # the decant's core name scores too low against "erba gold" to pass either.
    urls = {c.product_url for c in candidates}
    assert "https://www.parfimo.ro/dior-sauvage-apa-de-parfum-100-ml_z1234567/" not in urls
    assert "https://www.parfimo.ro/xerjoff-v-erba-gold-apa-de-parfum-decant-1-ml_z1098491/" not in urls


def test_search_perfume_builds_correct_product_urls():
    async def run():
        async with ParfimoScraper(settings=_test_settings(), transport=httpx.MockTransport(_handler([]))) as scraper:
            return await scraper.search_perfume("Xerjoff", "Erba Gold")

    candidates = asyncio.run(run())
    urls_by_id = {c.product_id: c.product_url for c in candidates}

    assert urls_by_id[909839] == "https://www.parfimo.ro/xerjoff-erba-gold-apa-de-parfum-50-ml_z909839/"
    assert urls_by_id[940989] == "https://www.parfimo.ro/xerjoff-erba-gold-apa-de-parfum-100-ml_z940989/"


def test_parse_product_reads_all_sibling_variants_from_one_fetch():
    candidate = _SearchCandidate(
        product_id=909839,
        product_url="https://www.parfimo.ro/xerjoff-erba-gold-apa-de-parfum-50-ml_z909839/",
        brand="Xerjoff",
        raw_name="Xerjoff Erba Gold Apă de parfum 50 ml",
        core_name="erba gold",
    )
    soup = BeautifulSoup(_fixture("product_erba_gold_50ml.html"), "lxml")

    async def run():
        async with ParfimoScraper(settings=_test_settings()) as scraper:
            return await scraper.parse_product(_FetchedProduct(candidate=candidate, soup=soup))

    offers = asyncio.run(run())

    # One page fetch yields all 3 sibling entries (100ml, 50ml, decant) from
    # the embedded product-series JSON - the decant itself is filtered
    # later by scraping_service's exclusion check on raw_title, not by the
    # scraper.
    assert len(offers) == 3
    by_volume = {o.volume_ml: o for o in offers if o.volume_ml is not None}

    # 50ml has two JSON entries (a packaging-only "Ambalaj vechi/nou"
    # variation pair sharing one product_id) - the cheaper one must win,
    # not just whichever key happens to come first/bare in the JSON.
    assert by_volume[50].price == Decimal("580.00")
    assert by_volume[50].availability == "in_stock"
    assert by_volume[50].tester is False
    assert by_volume[50].concentration == "EDP"
    assert by_volume[50].store_product_identifier == "909839"

    # 100ml carries a real discount in the fixture JSON - old_price must
    # come through when has_discount/price_without_discount are present.
    assert by_volume[100].price == Decimal("866.00")
    assert by_volume[100].old_price == Decimal("950.00")
    assert by_volume[50].old_price is None  # no discount on this entry

    decant_offer = next(o for o in offers if o.volume_ml == 1)
    assert "decant" in decant_offer.raw_title.lower()
    # Confirms the exclusion filter would actually catch it downstream.
    from app.normalization.exclusions import check_exclusion

    assert check_exclusion(decant_offer.raw_title) == "decant"


def test_parse_product_detects_out_of_stock():
    candidate = _SearchCandidate(
        product_id=555555,
        product_url="https://www.parfimo.ro/xerjoff-naxos-apa-de-parfum-100-ml_z555555/",
        brand="Xerjoff",
        raw_name="Xerjoff Naxos Apă de parfum 100 ml",
        core_name="naxos",
    )
    soup = BeautifulSoup(_fixture("product_out_of_stock.html"), "lxml")

    async def run():
        async with ParfimoScraper(settings=_test_settings()) as scraper:
            return await scraper.parse_product(_FetchedProduct(candidate=candidate, soup=soup))

    offers = asyncio.run(run())

    assert len(offers) == 1
    assert offers[0].availability == "out_of_stock"


def test_parse_product_returns_empty_when_no_product_data_script():
    from bs4 import BeautifulSoup as BS

    candidate = _SearchCandidate(
        product_id=1,
        product_url="https://www.parfimo.ro/some-product_z1/",
        brand="Xerjoff",
        raw_name="Xerjoff Something",
        core_name="something",
    )
    soup = BS("<html><body>no product data script here</body></html>", "lxml")

    async def run():
        async with ParfimoScraper(settings=_test_settings()) as scraper:
            return await scraper.parse_product(_FetchedProduct(candidate=candidate, soup=soup))

    assert asyncio.run(run()) == []


def test_parse_product_finds_data_script_not_nested_in_product_series_widget():
    # Real-site regression: when a product has no other sizes to
    # recommend, the "product-series" widget renders with isHidden=true
    # and no script nested inside it at all - the current product's own
    # data still gets printed by a separate, unnested script elsewhere on
    # the page. An earlier version of this scraper only looked inside the
    # product-series widget's own container and silently returned zero
    # offers for such products (caught via a user report: "Erba Gold"
    # showed "not available" on a store that actually carries it).
    from bs4 import BeautifulSoup as BS

    candidate = _SearchCandidate(
        product_id=909839,
        product_url="https://www.parfimo.ro/xerjoff-erba-gold-apa-de-parfum-50-ml_z909839/",
        brand="Xerjoff",
        raw_name="Xerjoff Erba Gold Apă de parfum 50 ml",
        core_name="erba gold",
    )
    html = """
    <html><body>
    <div class="c-recommender" data-live-props-value='{"label":"product-series","isHidden":true}'>
    </div>
    <script type="wpj/gtm" data-controller="utils-gtm-productdataprinter">
    {"909839":{"product_id":909839,"has_variations":false,"item_brand":"Xerjoff",
    "item_name":"Xerjoff Erba Gold Apă de parfum 50 ml","price_with_tax":600.5,
    "price_without_discount":null,"has_discount":false,"availability":"În stoc",
    "url":"https://www.parfimo.ro/xerjoff-erba-gold-apa-de-parfum-50-ml_z909839/"}}
    </script>
    </body></html>
    """
    soup = BS(html, "lxml")

    async def run():
        async with ParfimoScraper(settings=_test_settings()) as scraper:
            return await scraper.parse_product(_FetchedProduct(candidate=candidate, soup=soup))

    offers = asyncio.run(run())

    assert len(offers) == 1
    assert offers[0].volume_ml == 50
    assert offers[0].price == Decimal("600.5")


def test_discover_offers_end_to_end_against_fixtures():
    async def run():
        async with ParfimoScraper(settings=_test_settings(), transport=httpx.MockTransport(_handler([]))) as scraper:
            return await scraper.discover_offers("Xerjoff", "Erba Gold")

    offers = asyncio.run(run())

    assert len(offers) > 0
    assert all(o.brand == "Xerjoff" for o in offers)
