"""Parfimo.ro scraper.

Investigation summary:
- robots.txt is almost fully open (only /schimbare-date/ and /graphql are
  disallowed) - unlike Fragranza, the site's own search (/cautare/?search=)
  is NOT disallowed, so it's used directly instead of category browsing.
- Search results are server-rendered HTML, plus a `data-tracking-search`
  attribute (GTM/analytics data layer) holding a clean JSON blob of
  {id, name, brand} for every result on the page - used for discovery.
  Its "price" field is NOT the displayed price (empirically it's the
  displayed price divided by ~1.21, likely a pre-VAT base price) and is
  never used as the final price.
- Each bottle size is its OWN separate product page/URL (unlike Fragranza,
  where sizes are combinations on one page).
- Testers are separate products (their own name/URL containing "tester"),
  same pattern as Fragranza.
- No JavaScript execution is required for any of this - confirmed with
  plain HTTP requests only.

2026-08-25 redesign note: the site's product page markup changed since the
original investigation above (search_perfume/`/cautare/` was unaffected
and still works as originally designed). The old "product-collections"
DOM block this scraper relied on for sibling-variant discovery no longer
exists on the live site at all (verified: 0 matches on a real product
page) - parse_product() returned 0 offers for every real query as a
result, silently (no exception - discover_offers's per-candidate error
isolation only catches exceptions, not "found nothing"). Caught by
comparing a full app run against a direct scraper call while diagnosing
an unrelated bug on a different store.

Rather than re-scrape the new DOM (which spreads price/name/stock across
several different markup shapes for "the current product" vs "its
siblings"), parse_product() now reads one clean JSON blob instead: every
product page embeds one or more `<script data-controller=
"utils-gtm-productdataprinter">` tags - one is normally emitted inside
the "Alte produse din gama" ("product-series") recommender widget, and
covers the current product plus every sibling size/tester in one fetch,
keyed by product_id (with extra `{product_id}_{variation_id}` keys for
products that also have packaging-only variations, e.g. "Ambalaj
vechi/nou" - old vs new box design - which is irrelevant to our variant
identity; the cheapest entry per product_id is kept, collapsing packaging
variants down to one offer per product automatically). It also exposes
`price_without_discount`/`has_discount`, giving a first verified, real
example to populate old_price from (222 RON vs 239.50 RON list, ~7.3%
off - matches the JSON's own `discount` field) - previously omitted here
for lack of one.

An initial version scoped strictly to a script nested inside the widget
container carrying `"label":"product-series"` in its own
`data-live-props-value`, reasoning that a second, unrelated "last-visited"
widget can embed a same-tagged script elsewhere on the page once a
session has view history, and this would keep that out. That assumption
was wrong and cost a real product zero offers on the live site (found
via a user report, not a test): when a product has no other sizes to
recommend, the product-series widget renders with `"isHidden":true` and
no nested script at all, while the current product's own data still gets
printed by an *unnested*, page-level script tag instead. All
`utils-gtm-productdataprinter` scripts on the page are now collected and
merged - any genuine "last-visited" pollution is harmless, since unrelated
products it might add are already rejected downstream by
matching_service's brand/name matching, and that risk is far smaller than
silently dropping the real product's own data again.

2026-08-25 coupon widget note: some (not all) product pages also render a
"Cu codul X reducere Y%" banner (`[data-product-add-coupon-to-cart]`) with
the resulting discounted price already computed server-side as static
text - confirmed present with a real, working code/price on one tracked
product (Lattafa Khamrah, 30% off) and absent on others (Dior Sauvage, BDK
Rouge Smoking) on the same site, and the code/percentage differs between
products that do have it (Xerjoff Erba Gold's code was a different,
smaller discount) - this is a variable promotional campaign, not a fixed
product attribute. It also isn't part of the productdataprinter JSON
above, since it's rendered for whichever single product the page is
currently showing, not per sibling - only attached to the offer whose
product_id matches the page's own candidate, never to sibling
sizes/testers pulled from the same JSON blob. Surfaced as a secondary
coupon_code/coupon_price pair on ScrapedOffer, deliberately kept separate
from price/old_price: the code requires manual entry at checkout and the
campaign behind it can disappear at any time, so it isn't a stable value
to base price history or alerts on (see StoreProduct.coupon_code).
"""

import json
import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html import unescape
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from rapidfuzz import fuzz

from app.normalization.brand import brand_lookup_candidates, normalize_brand
from app.normalization.concentration import extract_concentration
from app.normalization.name import extract_core_name, normalize_name
from app.normalization.price import parse_price
from app.normalization.tester import is_tester
from app.normalization.text_utils import strip_diacritics
from app.normalization.volume import extract_volume_ml
from app.schemas.scraping import ScrapedOffer
from app.scrapers.base import BaseScraper
from app.scrapers.exceptions import ParsingError
from app.scrapers.registry import register_scraper

logger = logging.getLogger(__name__)

_MAX_SEARCH_PAGES = 5
_PRODUCT_ID_PATTERN = re.compile(r"_z(\d+)/?(?:[?#].*)?$")
_TRACKING_SEARCH_PATTERN = re.compile(r'data-tracking-search="(.*?)"', re.S)
_OUT_OF_STOCK_MARKERS = ("epuizat", "indisponibil", "nu este")


@dataclass(frozen=True)
class _SearchCandidate:
    product_id: int
    product_url: str
    brand: str
    raw_name: str
    core_name: str


@dataclass(frozen=True)
class _FetchedProduct:
    candidate: _SearchCandidate
    soup: BeautifulSoup


@register_scraper
class ParfimoScraper(BaseScraper):
    store_name = "Parfimo.ro"
    store_slug = "parfimo"
    base_url = "https://www.parfimo.ro"

    # -- search -----------------------------------------------------------

    async def search_perfume(self, brand: str, perfume_name: str) -> list[_SearchCandidate]:
        ambiguous_threshold = self._settings.MATCH_NAME_AMBIGUOUS_THRESHOLD
        query = f"{brand} {perfume_name}"
        candidates: list[_SearchCandidate] = []
        seen_ids: set[int] = set()

        for page in range(1, _MAX_SEARCH_PAGES + 1):
            params = {"search": query} if page == 1 else {"search": query, "page": page}
            response = await self.get("/cautare/", params=params)

            tracking = self._extract_tracking_search(response.text)
            if tracking is None:
                if page == 1:
                    raise ParsingError(f"{self.store_slug}: search results structure not recognized")
                break

            products = (tracking.get("results") or {}).get("products") or []
            if not products:
                break

            soup = BeautifulSoup(response.text, "lxml")
            id_to_url = self._extract_product_urls(soup)

            for product in products:
                candidate = self._build_candidate(product, id_to_url)
                if candidate is None or candidate.product_id in seen_ids:
                    continue
                if self._is_plausible_candidate(
                    candidate.brand, candidate.core_name, brand, perfume_name, ambiguous_threshold
                ):
                    seen_ids.add(candidate.product_id)
                    candidates.append(candidate)

        return candidates

    @staticmethod
    def _extract_tracking_search(html_text: str) -> dict | None:
        match = _TRACKING_SEARCH_PATTERN.search(html_text)
        if match is None:
            return None
        try:
            return json.loads(unescape(match.group(1)))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _extract_product_urls(soup: BeautifulSoup) -> dict[int, str]:
        urls: dict[int, str] = {}
        for link in soup.select('a[href*="_z"]'):
            href = link.get("href")
            if not href:
                continue
            match = _PRODUCT_ID_PATTERN.search(href)
            if not match:
                continue
            urls.setdefault(int(match.group(1)), urljoin(ParfimoScraper.base_url, href))
        return urls

    @staticmethod
    def _build_candidate(product: dict, id_to_url: dict[int, str]) -> _SearchCandidate | None:
        product_id = product.get("id")
        name = product.get("name")
        brand = product.get("brand")
        if not isinstance(product_id, int) or not name or not brand:
            return None

        url = id_to_url.get(product_id)
        if url is None:
            return None

        return _SearchCandidate(
            product_id=product_id,
            product_url=url,
            brand=brand,
            raw_name=name,
            core_name=extract_core_name(name, brand=brand),
        )

    @staticmethod
    def _is_plausible_candidate(
        item_brand: str, item_core_name: str, target_brand: str, target_name: str, ambiguous_threshold: int
    ) -> bool:
        # Alias-aware, not a bare equality check - see
        # brand_lookup_candidates and Parfumat's own version of this same
        # fix (confirmed live there: Dior's listings read "Christian
        # Dior", not "Dior").
        if normalize_brand(item_brand) not in brand_lookup_candidates(target_brand):
            return False

        target_normalized = normalize_name(target_name)
        if item_core_name == target_normalized:
            return True

        return fuzz.token_sort_ratio(item_core_name, target_normalized) >= ambiguous_threshold

    # -- fetch / parse ------------------------------------------------------

    async def fetch_product(self, candidate: _SearchCandidate) -> _FetchedProduct:
        response = await self.get(candidate.product_url)
        return _FetchedProduct(candidate=candidate, soup=BeautifulSoup(response.text, "lxml"))

    async def parse_product(self, raw_product: _FetchedProduct) -> list[ScrapedOffer]:
        candidate = raw_product.candidate

        entries = self._collect_product_data_entries(raw_product.soup)
        if not entries:
            logger.debug("%s: no product data script found for %s", self.store_slug, candidate.product_url)
            return []

        coupon = self._extract_coupon(raw_product.soup)

        offers = []
        for entry in self._select_cheapest_per_product(entries):
            is_primary_product = entry.get("product_id") == candidate.product_id
            coupon_code, coupon_price = coupon if (coupon is not None and is_primary_product) else (None, None)
            offer = self._build_offer_from_entry(entry, coupon_code=coupon_code, coupon_price=coupon_price)
            if offer is not None:
                offers.append(offer)
        return offers

    @staticmethod
    def _extract_coupon(soup: BeautifulSoup) -> tuple[str, Decimal] | None:
        """Reads the "Cu codul X reducere Y%" widget when present - see the
        module docstring's 2026-08-25 note."""
        widget = soup.select_one("[data-product-add-coupon-to-cart]")
        if widget is None:
            return None

        code = widget.get("data-product-add-coupon-to-cart")
        price_el = widget.select_one("p.h4")
        if not code or price_el is None:
            return None

        price = parse_price(price_el.get_text())
        if price is None:
            return None

        return code, price

    @staticmethod
    def _collect_product_data_entries(soup: BeautifulSoup) -> dict:
        # Not scoped to any one widget's container - see module docstring
        # for why an earlier, stricter version silently dropped real
        # products. Every such script on the page is merged together.
        merged: dict = {}
        for script in soup.find_all("script", attrs={"data-controller": "utils-gtm-productdataprinter"}):
            try:
                data = json.loads(script.get_text())
            except ValueError:
                continue
            if isinstance(data, dict):
                merged.update(data)
        return merged

    @staticmethod
    def _select_cheapest_per_product(entries: dict) -> list[dict]:
        # Packaging-only variations (e.g. "Ambalaj vechi/nou" - old vs new
        # box design) share one product_id but appear as separate JSON
        # keys - irrelevant to our variant identity (concentration/volume/
        # tester), so they're collapsed to the cheapest entry per product.
        best: dict[int, dict] = {}
        for entry in entries.values():
            product_id = entry.get("product_id")
            price = entry.get("price_with_tax")
            if not isinstance(product_id, int) or price is None:
                continue
            current = best.get(product_id)
            if current is None or price < current["price_with_tax"]:
                best[product_id] = entry
        return list(best.values())

    def _build_offer_from_entry(
        self, entry: dict, *, coupon_code: str | None = None, coupon_price: Decimal | None = None
    ) -> ScrapedOffer | None:
        item_name = entry.get("item_name")
        brand = entry.get("item_brand")
        url = entry.get("url")
        price_raw = entry.get("price_with_tax")
        if not item_name or not brand or not url or price_raw is None:
            return None

        try:
            price = Decimal(str(price_raw))
        except InvalidOperation:
            return None

        old_price = None
        if entry.get("has_discount") and entry.get("price_without_discount") is not None:
            try:
                old_price = Decimal(str(entry["price_without_discount"]))
            except InvalidOperation:
                old_price = None

        product_id = entry.get("product_id")

        return ScrapedOffer(
            store_slug=self.store_slug,
            raw_title=item_name,
            product_url=url,
            store_product_identifier=str(product_id) if product_id is not None else None,
            brand=brand,
            perfume_name=extract_core_name(item_name, brand=brand),
            concentration=extract_concentration(item_name),
            volume_ml=extract_volume_ml(item_name),
            tester=is_tester(item_name) or is_tester(url),
            price=price,
            old_price=old_price,
            availability=self._parse_availability(entry.get("availability", "")),
            currency="RON",
            coupon_code=coupon_code,
            coupon_price=coupon_price,
        )

    @staticmethod
    def _parse_availability(text: str) -> str:
        normalized = strip_diacritics(text).lower()
        if any(marker in normalized for marker in _OUT_OF_STOCK_MARKERS):
            return "out_of_stock"
        return "in_stock" if "stoc" in normalized else "out_of_stock"
