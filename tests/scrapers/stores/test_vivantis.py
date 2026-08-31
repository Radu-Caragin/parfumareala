"""Tests for VivantisScraper, using saved/synthesized HTML fixtures - no
live requests are made. This store uses curl_cffi (not httpx) as its
transport - see the module docstring in app/scrapers/stores/vivantis.py
for why - so these tests replace `scraper.request` directly with a
routing stub instead of using httpx.MockTransport.
"""

import asyncio
import json
from decimal import Decimal

import pytest

from app.config.settings import Settings
from app.scrapers.exceptions import RequestError
from app.scrapers.registry import get_scraper_class
from app.scrapers.stores.vivantis import VivantisScraper, _SearchCandidate


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


def _make_state_html(items: list[dict], *, listing_page: int = 1, listing_pages_count: int = 1) -> str:
    """Builds a minimal but structurally faithful copy of the real
    `window.__INITIAL_STATE__state='...'` blob - just the pieces
    VivantisScraper actually reads (productsStore.listingData.items,
    listingPage, listingPagesCount) - via json.dumps + the same
    single-quote escaping the real site uses, rather than hand-writing
    fragile escaped JSON text.
    """
    state = {
        "configStore": {"config": {"shopName": "vivantis.ro"}},
        "productsStore": {
            "listingPage": listing_page,
            "listingPagesCount": listing_pages_count,
            "listingData": {"items": items},
        },
    }
    # Compact separators to match the real site's minified JSON (no
    # spaces after ':'/',') - the real _has_next_page regex was verified
    # against that exact format during investigation.
    json_text = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    escaped = json_text.replace("'", "\\'")
    return f"<html><body><script>window.__INITIAL_STATE__state='{escaped}'</script></body></html>"


def _make_par(
    code: str,
    value: str,
    price: str,
    *,
    online: int = 1,
    sale: bool = False,
    rrp: str | None = None,
) -> dict:
    return {
        "code": code,
        "online": online,
        "price": {
            "withVat": {"decimal": price},
            "rrpWithVat": {"decimal": rrp} if rrp is not None else None,
        },
        "priceAction": {"sale": sale},
        "name": "Volum",
        "value": value,
        "perfumeSample": False,
    }


def _make_item(name: str, brand: str, url_relative: str, pars: list[dict]) -> dict:
    return {
        "name": name,
        "brands": [{"name": brand}],
        "urlRelative": url_relative,
        "pars": pars,
    }


BRANDURI_HTML = """
<html><body>
<div class="grid">
<a href="/bvlgari/">Bvlgari</a>
<a href="/jean-p-gaultier/">Jean P. Gaultier</a>
</div>
</body></html>
"""

_BVLGARI_ITEMS = [
    _make_item(
        "Pour Homme - EDT",
        "Bvlgari",
        "/parfumuri/bvlgari-pour-homme-edt.html",
        [
            _make_par("pBV014100", "100 ml", "438.00"),
            _make_par("pBV01450", "50 ml", "290.00"),
        ],
    ),
    _make_item(
        "Man in Black - EDP",
        "Bvlgari",
        "/parfumuri/bvlgari-man-in-black-edp.html",
        [_make_par("pBV248100", "100 ml", "550.00", online=0)],
    ),
]

_ROUTES = {
    "/branduri/": BRANDURI_HTML,
    "/bvlgari/parfumuri/": _make_state_html(_BVLGARI_ITEMS),
}


def _fake_request_handler(requested: list[str], routes: dict[str, str]):
    async def handler(method, url, **kwargs):
        requested.append(url)
        html = routes.get(url)
        if html is None:
            # Faithful to the real contract: this stub replaces
            # CurlCffiScraper.request() entirely (see its own
            # raise_for_status() call, curl_base.py), so it must raise on
            # a 4xx the same way, not return the error response - a
            # caller catching RequestError with a chained CurlHTTPError
            # (see VivantisScraper.search_perfume's "brand sells no
            # perfumes" branch) would otherwise never see one.
            response = _FakeResponse(404, "not found")
            try:
                response.raise_for_status()
            except Exception as exc:
                raise RequestError(f"vivantis: request to {url} failed") from exc
        return _FakeResponse(200, html)

    return handler


def _test_settings(**overrides) -> Settings:
    defaults = dict(REQUEST_TIMEOUT=5.0, REQUEST_DELAY=0.0, MAX_RETRIES=1, USER_AGENT="test-agent")
    defaults.update(overrides)
    return Settings(**defaults)


async def _scraper_with_routes(routes: dict[str, str], requested: list[str] | None = None) -> VivantisScraper:
    scraper = VivantisScraper(settings=_test_settings())
    scraper.request = _fake_request_handler(requested if requested is not None else [], routes)
    return scraper


def test_registered_in_scraper_registry():
    assert get_scraper_class("vivantis") is VivantisScraper


def test_search_perfume_finds_exact_match_and_resolves_brand_via_directory():
    requested: list[str] = []

    async def run():
        async with await _scraper_with_routes(_ROUTES, requested) as scraper:
            return await scraper.search_perfume("Bvlgari", "Pour Homme")

    candidates = asyncio.run(run())

    assert "/branduri/" in requested  # brand slug resolved via the directory, not guessed
    assert len(candidates) == 1
    assert candidates[0].item["name"] == "Pour Homme - EDT"


def test_search_perfume_unknown_brand_returns_empty():
    async def run():
        async with await _scraper_with_routes(_ROUTES) as scraper:
            return await scraper.search_perfume("Totally Fake Brand", "Whatever")

    assert asyncio.run(run()) == []


def test_search_perfume_brand_with_no_perfumes_returns_empty_not_error():
    # A brand can exist in the directory without selling any fragrances -
    # its /parfumuri/ subpage 404s (not in _ROUTES -> the fake handler
    # returns 404). That's "no candidates", not a scraping error.
    routes = dict(_ROUTES)

    async def run():
        async with await _scraper_with_routes(routes) as scraper:
            return await scraper.search_perfume("Jean Paul Gaultier", "Le Male")

    assert asyncio.run(run()) == []


def test_search_perfume_paginates_across_listing_pages():
    page1 = _make_state_html(
        [_make_item("Sauvage - EDT", "Dior", "/parfumuri/sauvage-edt.html", [_make_par("pD1100", "100 ml", "500.00")])],
        listing_page=1,
        listing_pages_count=2,
    )
    page2 = _make_state_html(
        [
            _make_item(
                "Sauvage Elixir - extract de parfum",
                "Dior",
                "/parfumuri/sauvage-elixir.html",
                [_make_par("pD2100", "100 ml", "700.00")],
            )
        ],
        listing_page=2,
        listing_pages_count=2,
    )
    routes = dict(_ROUTES)
    routes["/dior/parfumuri/"] = page1
    routes["/dior/parfumuri/?page=2"] = page2
    branduri_with_dior = BRANDURI_HTML.replace("</div>", '<a href="/dior/">Dior</a></div>')
    routes["/branduri/"] = branduri_with_dior
    requested: list[str] = []

    async def run():
        async with await _scraper_with_routes(routes, requested) as scraper:
            return await scraper.search_perfume("Dior", "Sauvage Elixir")

    candidates = asyncio.run(run())

    assert "/dior/parfumuri/?page=2" in requested
    assert len(candidates) == 1
    assert candidates[0].item["name"] == "Sauvage Elixir - extract de parfum"


def test_discover_offers_builds_correct_offers_from_pars():
    async def run():
        async with await _scraper_with_routes(_ROUTES) as scraper:
            return await scraper.discover_offers("Bvlgari", "Pour Homme")

    offers = asyncio.run(run())

    assert len(offers) == 2
    by_volume = {o.volume_ml: o for o in offers}

    assert by_volume[100].price == Decimal("438.00")
    assert by_volume[100].concentration == "EDT"
    assert by_volume[100].perfume_name == "pour homme"
    assert by_volume[100].brand == "Bvlgari"
    assert by_volume[100].tester is False
    assert by_volume[100].availability == "in_stock"
    assert by_volume[100].store_product_identifier == "pBV014100"
    assert by_volume[100].product_url == "https://www.vivantis.ro/parfumuri/bvlgari-pour-homme-edt.html?c=pBV014100"

    assert by_volume[50].price == Decimal("290.00")


def test_discover_offers_detects_out_of_stock():
    async def run():
        async with await _scraper_with_routes(_ROUTES) as scraper:
            return await scraper.discover_offers("Bvlgari", "Man in Black")

    offers = asyncio.run(run())

    assert len(offers) == 1
    assert offers[0].availability == "out_of_stock"


def test_parse_product_populates_old_price_only_when_on_sale():
    item = _make_item(
        "Sale Item - EDP",
        "Bvlgari",
        "/parfumuri/sale-item-edp.html",
        [
            _make_par("pSALE100", "100 ml", "300.00", sale=True, rrp="400.00"),
            _make_par("pSALE50", "50 ml", "200.00"),  # not on sale - no old_price
        ],
    )
    candidate = _SearchCandidate(item=item, core_name="sale item")

    async def run():
        async with await _scraper_with_routes({}) as scraper:
            fetched = await scraper.fetch_product(candidate)
            return await scraper.parse_product(fetched)

    offers = asyncio.run(run())
    by_volume = {o.volume_ml: o for o in offers}

    assert by_volume[100].old_price == Decimal("400.00")
    assert by_volume[50].old_price is None


def test_parse_product_reads_trailing_p_suffix_as_parfum():
    # Regression: a real, in-stock listing ("Black Orchid - P", confirmed
    # live) truncates its concentration suffix down to a single letter,
    # with no other concentration wording anywhere in the name -
    # extract_concentration() alone finds nothing there, which would
    # silently drop the whole offer downstream as "missing_variant_fields".
    item = _make_item(
        "Black Orchid - P", "Tom Ford", "/parfumuri/tf-black-orchid-p.html",
        [_make_par("pTF106100", "100 ml", "591.00")],
    )
    candidate = _SearchCandidate(item=item, core_name="black orchid")

    async def run():
        async with await _scraper_with_routes({}) as scraper:
            fetched = await scraper.fetch_product(candidate)
            return await scraper.parse_product(fetched)

    offers = asyncio.run(run())

    assert len(offers) == 1
    assert offers[0].concentration == "Parfum"


def test_parse_product_returns_empty_for_item_with_no_variants():
    # A gift set or similar listing entry with no purchasable "pars" at
    # all must yield zero offers, not crash.
    item = _make_item("Set cadou Something", "Bvlgari", "/parfumuri/set-cadou.html", [])
    candidate = _SearchCandidate(item=item, core_name="set cadou something")

    async def run():
        async with await _scraper_with_routes({}) as scraper:
            fetched = await scraper.fetch_product(candidate)
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
        scraper = VivantisScraper(settings=_test_settings(MAX_RETRIES=3))
        scraper._curl_session.request = AsyncMock(side_effect=fake_curl_request)
        async with scraper:
            with pytest.raises(RequestError):
                await scraper.get("/missing/")

    asyncio.run(run())
    assert attempts["count"] == 1
