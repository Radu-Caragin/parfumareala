"""Notino.ro scraper.

Investigation summary:
- Same Cloudflare TLS/HTTP fingerprinting block as Vivantis.ro - plain
  httpx gets a `cf-mitigated: challenge` response on the very first
  request, curl_cffi passes cleanly. Built on CurlCffiScraper
  (app/scrapers/curl_base.py), same as Vivantis - see that module's
  docstring for the full original diagnosis.
- robots.txt disallows /api/ (except /api/beautyblog, /api/faqs) and
  /productDetail specifically (an internal AJAX path, not the real
  product page URL - never fetched here), plus cart/checkout/account
  flows. No crawl-delay for our user-agent. sitemap.xml is a sitemap
  index; one of its entries, `sitemap_detail_parfemy_ro.xml` ("parfemy"
  is Czech/Slovak for "perfumes" - Notino is Czech-founded and reuses
  internal category slugs across country sites), is a flat, actively
  maintained (lastmod = today) list of ~12,300 perfume-category product
  URLs shaped `/{brand-slug}/{name-slug}/` - brand is always the first
  path segment, and simple slugification (lowercase, hyphenate) was
  confirmed live against several multi-word brands including ones that
  trip up naive guessing elsewhere (e.g. "Jean Paul Gaultier" resolves
  directly here, unlike on Vivantis where it needed an abbreviated
  slug) - so unlike Vivantis, no brand-directory lookup is needed, sitemap
  prefix-matching (brand-slug + fuzzy-matched remainder) is enough on its
  own, the same strategy used for a much earlier, since-removed store -
  except this sitemap is actually fresh, unlike that one's frozen 2022
  snapshot, which is what made the strategy unreliable there.
- The "parfemy" sitemap also includes non-fragrance items filed under the
  same brand/category (home diffusers, shower gels, aftershave, shaving
  products) - left to the existing concentration-must-be-present matching
  rule to filter out, no special-case handling needed (confirmed: a
  shower gel's own data has no "Concentrația ingredientului parfumat"
  characteristic at all, so extract_concentration() correctly finds
  nothing there).
- Every product page embeds a clean `<script id="__APOLLO_STATE__"
  type="application/json">` block - a normalized Apollo GraphQL cache
  dump, valid JSON on its own (no JS-string-escaping to undo, unlike
  Vivantis's `window.__INITIAL_STATE__state='...'`). A `CatalogProduct`
  entry references one or more `CatalogVariant` entries (one per
  concentration+volume combination sold on that page, e.g. Dior Sauvage
  EDP's own page has 4: 30/60/100/200ml) via `{"__ref": "CatalogVariant:
  {id}"}` pointers into the same top-level dict - resolved directly,
  no bracket-matching or JS-unescaping needed like the other two
  JS-state-based stores use.
- Per variant: `variantName` (e.g. "Eau de Parfum pentru bărbați") is
  concentration text - extract_concentration() already handles it
  directly, no need to look at the separate "characteristics" array that
  duplicates the same information. `additionalInfo` (e.g. "200\xa0ml" -
  a non-breaking space, confirmed extract_volume_ml() already tolerates
  it) is the volume. `price.value`/`originalPrice.value` are the
  current/pre-discount prices (verified live against a real discounted
  product: 215 RON current vs 315 RON originalPrice, ~32% off - populated
  only when non-null, which correlates with there being an actual active
  discount). `availability.state == "CanBeBought"` is the reliable
  in/out-of-stock signal (verified against a real out-of-stock example -
  a refill product showed state "ShowWatchdog", a "notify me" state, with
  its stockAvailability.code as the plainer confirming signal
  "outOfStock" - CanBeBought is treated as the sole in-stock state, any
  other value as out of stock, the conservative direction).
- Testers: none found anywhere - checked the whole ~12,300-URL perfume
  sitemap and several brand pages (Dior, Nishane) for "tester" text, zero
  matches. Tester is always False here, a verified absence rather than
  an assumption - consistent with this being an official multi-country
  retailer rather than the smaller niche Romanian sites that do carry
  testers.
- Refill-only products (e.g. "Sauvage Eau de Parfum Rezerva 300 ml",
  which its own description states "nu poate fi utilizata singura" - "
  can't be used alone") are real and distinct from normal refillable
  bottles ("reincarcabil") - added a Romanian "rezerva"/"rezerve"
  exclusion pattern to app/normalization/exclusions.py, the same
  distinction already established for the English "refill" pattern.
"""

import json
import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from rapidfuzz import fuzz

from app.normalization.concentration import extract_concentration
from app.normalization.name import extract_core_name, normalize_name
from app.normalization.text_utils import strip_diacritics
from app.normalization.volume import extract_volume_ml
from app.schemas.scraping import ScrapedOffer
from app.scrapers.curl_base import CurlCffiScraper
from app.scrapers.exceptions import ParsingError
from app.scrapers.registry import register_scraper

logger = logging.getLogger(__name__)

_PRODUCT_URL_PATTERN = re.compile(r"^/([a-z0-9-]+)/([a-z0-9-]+)/$")


@dataclass(frozen=True)
class _SearchCandidate:
    product_url: str
    core_name: str


@register_scraper
class NotinoScraper(CurlCffiScraper):
    store_name = "Notino.ro"
    store_slug = "notino"
    base_url = "https://www.notino.ro"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._sitemap_urls_cache: list[str] | None = None

    # -- sitemap discovery --------------------------------------------------

    async def _get_sitemap_urls(self) -> list[str]:
        if self._sitemap_urls_cache is None:
            self._sitemap_urls_cache = await self._load_sitemap_urls()
        return self._sitemap_urls_cache

    async def _load_sitemap_urls(self) -> list[str]:
        index_response = await self.get("/sitemap.xml")
        index_soup = BeautifulSoup(index_response.text, "xml")

        perfume_sitemap_url = next(
            (
                loc.get_text(strip=True)
                for loc in index_soup.find_all("loc")
                if "parfemy" in loc.get_text(strip=True).lower()
            ),
            None,
        )
        if perfume_sitemap_url is None:
            raise ParsingError(f"{self.store_slug}: perfume sitemap not found in sitemap index")

        response = await self.get(perfume_sitemap_url)
        soup = BeautifulSoup(response.text, "xml")
        urls = [loc.get_text(strip=True) for loc in soup.find_all("loc")]
        if not urls:
            raise ParsingError(f"{self.store_slug}: perfume sitemap structure not recognized")

        return urls

    # -- search ---------------------------------------------------------

    async def search_perfume(self, brand: str, perfume_name: str) -> list[_SearchCandidate]:
        ambiguous_threshold = self._settings.MATCH_NAME_AMBIGUOUS_THRESHOLD
        target_normalized = normalize_name(perfume_name)
        brand_slug = self._slugify(brand)

        candidates: list[_SearchCandidate] = []
        for url in await self._get_sitemap_urls():
            match = _PRODUCT_URL_PATTERN.match(urlparse(url).path)
            if not match or match.group(1) != brand_slug:
                continue

            remainder = match.group(2).replace("-", " ")
            core_name = extract_core_name(remainder, brand=brand)
            if core_name == target_normalized or fuzz.token_sort_ratio(
                core_name, target_normalized
            ) >= ambiguous_threshold:
                candidates.append(_SearchCandidate(product_url=url, core_name=core_name))

        return candidates

    @staticmethod
    def _slugify(text: str) -> str:
        normalized = strip_diacritics(text).lower()
        return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")

    # -- fetch / parse ----------------------------------------------------

    async def fetch_product(self, candidate: _SearchCandidate) -> str:
        response = await self.get(candidate.product_url)
        return response.text

    async def parse_product(self, raw_product: str) -> list[ScrapedOffer]:
        soup = BeautifulSoup(raw_product, "lxml")
        script = soup.select_one('script#__APOLLO_STATE__[type="application/json"]')
        if script is None:
            return []

        try:
            state = json.loads(script.get_text())
        except ValueError:
            return []

        product_key = next((k for k in state if k.startswith("CatalogProduct:")), None)
        if product_key is None:
            return []
        product = state[product_key]

        brand_ref = (product.get("brand") or {}).get("__ref")
        brand = state.get(brand_ref, {}).get("name") if brand_ref else None

        offers = [
            offer
            for variant_ref in product.get("variants") or []
            if (offer := self._build_offer(state, variant_ref.get("__ref"), brand)) is not None
        ]
        return offers

    def _build_offer(self, state: dict, variant_key: str | None, brand: str | None) -> ScrapedOffer | None:
        if variant_key is None or variant_key not in state:
            return None
        variant = state[variant_key]

        name = variant.get("name") or ""
        variant_name = variant.get("variantName") or ""
        additional_info = variant.get("additionalInfo") or ""
        url = variant.get("url")
        price_data = variant.get("price") or {}
        price_value = price_data.get("value")

        if not url or price_value is None:
            return None

        try:
            price = Decimal(str(price_value))
        except InvalidOperation:
            return None

        old_price = None
        original_price_data = variant.get("originalPrice")
        if isinstance(original_price_data, dict) and original_price_data.get("value") is not None:
            try:
                old_price = Decimal(str(original_price_data["value"]))
            except InvalidOperation:
                old_price = None

        availability_state = (variant.get("availability") or {}).get("state")
        availability = "in_stock" if availability_state == "CanBeBought" else "out_of_stock"

        raw_title = f"{name} {variant_name} {additional_info}".strip()

        return ScrapedOffer(
            store_slug=self.store_slug,
            raw_title=raw_title,
            product_url=f"{self.base_url}{url}" if url.startswith("/") else url,
            store_product_identifier=variant.get("productCode") or variant_key,
            brand=brand,
            perfume_name=extract_core_name(name, brand=brand),
            concentration=extract_concentration(variant_name),
            volume_ml=extract_volume_ml(additional_info),
            tester=False,
            price=price,
            old_price=old_price,
            currency=price_data.get("currency", "RON"),
            availability=availability,
        )
