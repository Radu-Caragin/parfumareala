"""Tests for NotinoScraper, using saved/synthesized HTML fixtures - no
live requests are made. This store uses curl_cffi (via CurlCffiScraper),
not httpx - see app/scrapers/curl_base.py - so these tests replace
`scraper.request` directly with a routing stub, same approach as
test_vivantis.py.
"""

import asyncio
import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.config.settings import Settings
from app.scrapers.exceptions import RequestError
from app.scrapers.registry import get_scraper_class
from app.scrapers.stores.notino import NotinoScraper, _SearchCandidate

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures" / "notino"


class _FakeResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            from curl_cffi.requests.exceptions import HTTPError

            error = HTTPError(f"HTTP Error {self.status_code}")
            error.response = self
            raise error


def _fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def _make_variant(
    web_id: str,
    *,
    name: str,
    variant_name: str,
    additional_info: str,
    url: str,
    product_code: str,
    price: float,
    original_price: float | None = None,
    state: str = "CanBeBought",
) -> dict:
    return {
        "webId": web_id,
        "name": name,
        "variantName": variant_name,
        "additionalInfo": additional_info,
        "url": url,
        "productCode": product_code,
        "price": {"__typename": "Price", "value": price, "currency": "RON", "tax": 21},
        "originalPrice": (
            {"__typename": "OriginalPrice", "value": original_price, "currency": "RON", "tax": 21}
            if original_price is not None
            else None
        ),
        "availability": {"__typename": "Availability", "state": state},
    }


def _make_apollo_html(*, master_id: str, brand_id: str, brand_name: str, variants: list[dict]) -> str:
    state: dict = {
        f"Brand:{brand_id}": {"__typename": "Brand", "id": brand_id, "name": brand_name},
    }
    for v in variants:
        state[f"CatalogVariant:{v['webId']}"] = {"__typename": "CatalogVariant", **v}

    state[f"CatalogProduct:{master_id}"] = {
        "__typename": "CatalogProduct",
        "webMasterId": master_id,
        "brand": {"__ref": f"Brand:{brand_id}"},
        "isPerfume": True,
        "variants": [{"__ref": f"CatalogVariant:{v['webId']}"} for v in variants],
    }
    json_text = json.dumps(state, ensure_ascii=False)
    return (
        '<html><body><script id="__APOLLO_STATE__" type="application/json">'
        f"{json_text}</script></body></html>"
    )


_SAUVAGE_EDP_HTML = _make_apollo_html(
    master_id="15676518",
    brand_id="1",
    brand_name="DIOR",
    variants=[
        _make_variant(
            "15971107",
            name="Sauvage",
            variant_name="Eau de Parfum pentru bărbați",
            additional_info="200\xa0ml",
            url="/dior/sauvage-eau-de-parfum-pentru-barbati/p-15971107/",
            product_code="CHDSVGM_AEDP25",
            price=1050,
        ),
        _make_variant(
            "15676518",
            name="Sauvage",
            variant_name="Eau de Parfum pentru bărbați",
            additional_info="100\xa0ml",
            url="/dior/sauvage-eau-de-parfum-pentru-barbati/p-15676518/",
            product_code="CHDSVGM_AEDP10",
            price=719,
        ),
    ],
)

_SHOWER_GEL_HTML = _make_apollo_html(
    master_id="99999",
    brand_id="1",
    brand_name="DIOR",
    variants=[
        _make_variant(
            "99999",
            name="Sauvage",
            variant_name="gel parfumat pentru duș cu pompa pentru bărbați",
            additional_info="250\xa0ml",
            url="/dior/sauvage-gel-parfumat-pentru-dus-cu-pompa-pentru-barbati/p-99999/",
            product_code="CHDSVGSG",
            price=180,
        ),
    ],
)

_ROUTES = {
    "/sitemap.xml": _fixture("sitemap.xml"),
    "https://www.notino.ro/export/sitemap/sitemap_detail_parfemy_ro.xml": _fixture(
        "sitemap_detail_parfemy_ro.xml"
    ),
    # Candidates carry the sitemap's own full absolute URL as product_url
    # (not a relative path) - fetch_product() passes it straight through.
    "https://www.notino.ro/dior/sauvage-eau-de-parfum-pentru-barbati/": _SAUVAGE_EDP_HTML,
    "https://www.notino.ro/dior/sauvage-gel-parfumat-pentru-dus-cu-pompa-pentru-barbati/": _SHOWER_GEL_HTML,
}


def _fake_request_handler(requested: list[str], routes: dict[str, str]):
    async def handler(method, url, **kwargs):
        requested.append(url)
        html = routes.get(url)
        if html is None:
            return _FakeResponse(404, "not found")
        return _FakeResponse(200, html)

    return handler


def _test_settings(**overrides) -> Settings:
    defaults = dict(REQUEST_TIMEOUT=5.0, REQUEST_DELAY=0.0, MAX_RETRIES=1, USER_AGENT="test-agent")
    defaults.update(overrides)
    return Settings(**defaults)


async def _scraper_with_routes(routes: dict[str, str], requested: list[str] | None = None) -> NotinoScraper:
    scraper = NotinoScraper(settings=_test_settings())
    scraper.request = _fake_request_handler(requested if requested is not None else [], routes)
    return scraper


def test_registered_in_scraper_registry():
    assert get_scraper_class("notino") is NotinoScraper


def test_search_perfume_finds_exact_match_via_sitemap():
    requested: list[str] = []

    async def run():
        async with await _scraper_with_routes(_ROUTES, requested) as scraper:
            return await scraper.search_perfume("Dior", "Sauvage")

    candidates = asyncio.run(run())

    assert any(u.endswith("sitemap_detail_parfemy_ro.xml") for u in requested)
    urls = {c.product_url for c in candidates}
    assert "https://www.notino.ro/dior/sauvage-eau-de-parfum-pentru-barbati/" in urls
    # Wrong brand entirely must never pass the slug-prefix filter.
    assert not any("bvlgari" in u for u in urls)


def test_search_perfume_excludes_refill_product_at_discovery_stage():
    # "Sauvage Eau de Parfum Rezerva" scores below the ambiguous threshold
    # against plain "Sauvage" (its remainder core name is "sauvage
    # rezerva") - filtered before ever being fetched. Belt-and-suspenders
    # with the "rezerva" exclusion pattern in exclusions.py, which would
    # also catch it later if it were ever a closer match for some other
    # search.
    async def run():
        async with await _scraper_with_routes(_ROUTES) as scraper:
            return await scraper.search_perfume("Dior", "Sauvage")

    candidates = asyncio.run(run())
    assert not any("rezerva" in c.product_url for c in candidates)


def test_search_perfume_unknown_brand_returns_empty():
    async def run():
        async with await _scraper_with_routes(_ROUTES) as scraper:
            return await scraper.search_perfume("Totally Fake Brand", "Whatever")

    assert asyncio.run(run()) == []


def test_discover_offers_builds_correct_offers_from_apollo_state():
    async def run():
        async with await _scraper_with_routes(_ROUTES) as scraper:
            return await scraper.discover_offers("Dior", "Sauvage")

    offers = asyncio.run(run())

    edp_offers = [o for o in offers if o.concentration == "EDP"]
    assert len(edp_offers) == 2
    by_volume = {o.volume_ml: o for o in edp_offers}

    assert by_volume[100].price == Decimal("719")
    assert by_volume[100].brand == "DIOR"
    assert by_volume[100].perfume_name == "sauvage"
    assert by_volume[100].tester is False
    assert by_volume[100].availability == "in_stock"
    assert by_volume[100].store_product_identifier == "CHDSVGM_AEDP10"
    assert by_volume[100].product_url == "https://www.notino.ro/dior/sauvage-eau-de-parfum-pentru-barbati/p-15676518/"
    assert by_volume[100].old_price is None

    assert by_volume[200].price == Decimal("1050")


def test_shower_gel_has_no_concentration_and_is_left_ambiguous():
    # Same brand/line, but a body-care product, not a fragrance - must
    # not be mistaken for one just because it shares "Sauvage" naming.
    candidate = _SearchCandidate(
        product_url="https://www.notino.ro/dior/sauvage-gel-parfumat-pentru-dus-cu-pompa-pentru-barbati/",
        core_name="sauvage",
    )

    async def run():
        async with await _scraper_with_routes(_ROUTES) as scraper:
            fetched = await scraper.fetch_product(candidate)
            return await scraper.parse_product(fetched)

    offers = asyncio.run(run())
    assert len(offers) == 1
    assert offers[0].concentration is None


def test_parse_product_populates_old_price_only_when_discounted():
    html = _make_apollo_html(
        master_id="1",
        brand_id="2",
        brand_name="Afnan",
        variants=[
            _make_variant(
                "1",
                name="Supremacy Collector's Edition",
                variant_name="Eau de Parfum pentru bărbați",
                additional_info="100\xa0ml",
                url="/afnan/supremacy-collectors-edition-eau-de-parfum-pentru-barbati/p-1/",
                product_code="AFNSPCM_AEDP10",
                price=215,
                original_price=315,
            ),
        ],
    )
    candidate = _SearchCandidate(product_url="/afnan/x/", core_name="supremacy")

    async def run():
        async with await _scraper_with_routes({"/afnan/x/": html}) as scraper:
            fetched = await scraper.fetch_product(candidate)
            return await scraper.parse_product(fetched)

    offers = asyncio.run(run())
    assert offers[0].old_price == Decimal("315")


def test_parse_product_detects_out_of_stock():
    html = _make_apollo_html(
        master_id="1",
        brand_id="2",
        brand_name="Dior",
        variants=[
            _make_variant(
                "1",
                name="Sauvage",
                variant_name="Eau de Parfum rezervă pentru bărbați",
                additional_info="300\xa0ml Rezerve",
                url="/dior/sauvage-eau-de-parfum-rezerva-pentru-barbati/p-1/",
                product_code="CHDSVGM_AEDP30",
                price=1450,
                state="ShowWatchdog",
            ),
        ],
    )
    candidate = _SearchCandidate(product_url="/dior/x/", core_name="sauvage rezerva")

    async def run():
        async with await _scraper_with_routes({"/dior/x/": html}) as scraper:
            fetched = await scraper.fetch_product(candidate)
            return await scraper.parse_product(fetched)

    offers = asyncio.run(run())
    assert offers[0].availability == "out_of_stock"


def test_parse_product_returns_empty_when_no_apollo_state():
    async def run():
        async with await _scraper_with_routes({}) as scraper:
            fetched = "<html><body>no apollo state here</body></html>"
            return await scraper.parse_product(fetched)

    assert asyncio.run(run()) == []


def test_request_fails_fast_on_404_without_retrying():
    from unittest.mock import AsyncMock

    from curl_cffi.requests.exceptions import HTTPError

    attempts = {"count": 0}

    async def fake_curl_request(method, url, **kwargs):
        attempts["count"] += 1
        response = _FakeResponse(404, "not found")
        error = HTTPError("HTTP Error 404")
        error.response = response
        raise error

    async def run():
        scraper = NotinoScraper(settings=_test_settings(MAX_RETRIES=3))
        scraper._curl_session.request = AsyncMock(side_effect=fake_curl_request)
        async with scraper:
            with pytest.raises(RequestError):
                await scraper.get("/missing/")

    asyncio.run(run())
    assert attempts["count"] == 1
