"""Vivantis.ro scraper.

Investigation summary:
- Vue.js SPA (server-rendered) - every page embeds the full server state
  as a JSON blob assigned to `window.__INITIAL_STATE__state` (a
  single-quoted JS string literal wrapping escaped JSON, not a bare
  object literal). No JavaScript execution is needed - the embedded
  state already has everything: price, stock, volume options, per-variant
  SKUs.
- robots.txt disallows /fulltext/ (their search) and /kosik/ (cart); no
  crawl-delay for our user-agent (only MJ12bot has one specified).
  sitemap.xml is a sitemap index, actively maintained (lastmod = today,
  unlike a previous store's frozen one) - not used here though, since
  brand-page browsing (below) is more direct and doesn't need it.
- This store's Cloudflare configuration fingerprints the TLS/HTTP
  handshake itself, not just headers - a plain httpx request is served a
  challenge page (`cf-mitigated: challenge`) on the very first request,
  regardless of User-Agent or any other header sent at the application
  layer, while an identical request via curl succeeds. Confirmed this
  wasn't an IP-wide block (curl kept working from the same machine at
  the same moment httpx was being challenged) or a request-volume issue
  (fails on request #1, not after several). This scraper is therefore
  built on CurlCffiScraper (app/scrapers/curl_base.py), not BaseScraper
  directly - curl_cffi (Chrome TLS-fingerprint impersonation) instead of
  httpx as the transport, same rate-limiting/retry contract otherwise.
  Every other store scraper is unaffected and still uses plain httpx.
- Brand pages exist at the URL root (`/{brand-slug}/`), not
  category-nested. Naive slugification (lowercase, hyphenate) works for
  most brands but is NOT reliable - confirmed live: "Jean Paul Gaultier"
  resolves to `/jean-p-gaultier/`, not `/jean-paul-gaultier/`. A brand
  directory at `/branduri/` lists all ~815 brands with their real slugs
  on one page (no pagination) - used as the authoritative brand->slug
  lookup instead of guessing.
- `/{brand-slug}/parfumuri/` filters a brand's catalog to the
  "Parfumuri" category (paginated via the standard `?page=N`) - and,
  crucially, each listed item already carries its full variant array
  (price/stock/volume per SKU) inline, so no second per-product page
  fetch is ever needed. Even this "parfumuri" category mixes in
  non-fragrance items from the same brand (deodorants, shower gels,
  aftershave, shaving cream) - these are left to the existing
  concentration-must-be-present matching rule to filter out
  (extract_concentration finds nothing in "Sauvage - deodorant spray"),
  no special-case handling needed.
- Concentration is a suffix on the item's own name field (e.g. "Pour
  Homme - EDT", "Sauvage Elixir - extract de parfum") - the Romanian
  "extract de parfum" spelling is used here too, already covered by
  concentration.py. Also uses the bare Czech/Slovak word "parfém" as that
  suffix sometimes (e.g. "MYSLF L`Absolu - parfém", confirmed live,
  in stock) - concentration.py's diacritic-stripped "parfem" pattern
  handles this now (a real spelling, not just an accent - "parfem" has a
  different vowel than "parfum").
  2026-08-25: a handful of real, in-stock listings truncate that suffix
  down to a single letter instead - "Black Orchid - P" (confirmed live,
  100ml, in stock, no other concentration wording anywhere in the name -
  extract_concentration() found nothing and the whole offer would have
  been silently dropped downstream as "missing_variant_fields"). Sampling
  ~250 more items across 5 more brands found the same "- P" suffix on 3
  more names, always alongside "Parfum" spelled out elsewhere in the same
  name (e.g. "Bleu De Chanel Parfum - P") - consistent with "P" standing
  for Parfum, never seen paired with EDT/EDC wording. Too narrow and
  single-letter to add as a shared concentration.py pattern (real
  collision risk with unrelated text on other stores), so it's handled
  as a Vivantis-only fallback in parse_product() instead, applied only
  when the shared extractor already found nothing.
- Testers: none found anywhere in the whole catalog - checked all
  ~6800 perfume-category sitemap URLs (only false-positive matches were
  "sporttester" fitness watches) and every "pars" variant sampled across
  5 brands (~200 variants total, all `perfumeSample: false`) - tester is
  always False here, a verified absence rather than an assumption.
- Gift sets do appear within a brand's "parfumuri" listing sometimes
  (e.g. "Set cadou ...") - caught by the existing "set cadou" exclusion
  pattern; no samples/decants/refill-only items found anywhere in the
  catalog (verified via a sitemap-wide text search).
- Stock: each variant's own "online" field (1 or 0). No live
  out-of-stock example was found during investigation (checked ~200
  variants across 5 brands, all online=1) - trusted on the field's own
  unambiguous name rather than an observed example.
- old_price: `priceAction.sale` / `price.rrpWithVat` look like the
  discount signal (recommended-retail-price vs current price, following
  the same {amount,multiplier,currency,decimal} shape as the other price
  fields in the same object) - but no live discounted example was found
  either, so this is populated only when priceAction.sale is true and
  rrpWithVat is present, on the same reasoning as the stock field above;
  flagged here as unverified against a real example.
- A brand's "/parfumuri/" page can itself 404 if that brand sells no
  perfumes at all (not every brand in the directory does) - treated the
  same as "no candidates found", not a scraping error.
"""

import json
import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from bs4 import BeautifulSoup
from curl_cffi.requests.exceptions import HTTPError as CurlHTTPError

from app.normalization.brand import brand_lookup_candidates, normalize_brand
from app.normalization.concentration import extract_concentration
from app.normalization.name import extract_core_name, names_plausibly_match, normalize_name
from app.normalization.volume import extract_volume_ml
from app.schemas.scraping import ScrapedOffer
from app.scrapers.curl_base import CurlCffiScraper
from app.scrapers.exceptions import ParsingError, RequestError
from app.scrapers.registry import register_scraper

logger = logging.getLogger(__name__)

_MAX_LISTING_PAGES = 10
_STATE_MARKER = "window.__INITIAL_STATE__state='"
_BRAND_HREF_PATTERN = re.compile(r"^/[a-z0-9][a-z0-9-]*/$")
_TRAILING_P_PATTERN = re.compile(r"-\s*P\s*\Z")


@dataclass(frozen=True)
class _SearchCandidate:
    item: dict
    core_name: str


@register_scraper
class VivantisScraper(CurlCffiScraper):
    store_name = "Vivantis.ro"
    store_slug = "vivantis"
    base_url = "https://www.vivantis.ro"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._brand_slug_cache: dict[str, str] | None = None

    # -- brand slug lookup --------------------------------------------------

    async def _get_brand_slug(self, brand: str) -> str | None:
        if self._brand_slug_cache is None:
            self._brand_slug_cache = await self._load_brand_directory()
        for candidate in brand_lookup_candidates(brand):
            slug = self._brand_slug_cache.get(candidate)
            if slug is not None:
                return slug
        return None

    async def _load_brand_directory(self) -> dict[str, str]:
        response = await self.get("/branduri/")
        soup = BeautifulSoup(response.text, "lxml")

        brands: dict[str, str] = {}
        for link in soup.select("div.grid a[href]"):
            href = link.get("href", "")
            if not _BRAND_HREF_PATTERN.match(href):
                continue
            name = link.get_text(strip=True)
            if not name:
                continue
            brands[normalize_brand(name)] = href.strip("/")

        if not brands:
            raise ParsingError(f"{self.store_slug}: brand directory structure not recognized")

        return brands

    # -- search ---------------------------------------------------------

    async def search_perfume(self, brand: str, perfume_name: str) -> list[_SearchCandidate]:
        slug = await self._get_brand_slug(brand)
        if slug is None:
            logger.debug("%s: no brand found for %s", self.store_slug, brand)
            return []

        ambiguous_threshold = self._settings.MATCH_NAME_AMBIGUOUS_THRESHOLD
        target_normalized = normalize_name(perfume_name)

        candidates: list[_SearchCandidate] = []
        page = 1
        while page <= _MAX_LISTING_PAGES:
            path = f"/{slug}/parfumuri/" if page == 1 else f"/{slug}/parfumuri/?page={page}"
            try:
                response = await self.get(path)
            except RequestError as exc:
                cause = exc.__cause__
                if isinstance(cause, CurlHTTPError) and cause.response is not None and 400 <= cause.response.status_code < 500:
                    # This brand simply sells no perfumes - not every
                    # brand in the directory does.
                    break
                raise

            items, has_next = self._parse_listing_page(response.text)

            for item in items:
                item_brand = self._extract_brand(item) or brand
                core_name = extract_core_name(item.get("name") or "", brand=item_brand)
                if names_plausibly_match(core_name, target_normalized, ambiguous_threshold):
                    candidates.append(_SearchCandidate(item=item, core_name=core_name))

            if not has_next:
                break
            page += 1

        return candidates

    @classmethod
    def _parse_listing_page(cls, html_text: str) -> tuple[list[dict], bool]:
        state = cls._extract_state_json_text(html_text)
        if state is None:
            raise ParsingError(f"{cls.store_slug}: __INITIAL_STATE__ block not found")

        # Scoped to productsStore specifically, not just "the first
        # 'items' key anywhere in the state" - configStore/brandsStore/
        # etc. happen to precede it and don't have their own "items"
        # field on every page seen so far, but relying on that ordering
        # implicitly would be fragile; this makes the actual scope match
        # what was verified during investigation.
        products_store_idx = state.find('"productsStore":')
        if products_store_idx == -1:
            raise ParsingError(f"{cls.store_slug}: productsStore not found in page state")
        state = state[products_store_idx:]

        items_raw = cls._extract_bracket_array(state, '"items":')
        if items_raw is None:
            raise ParsingError(f"{cls.store_slug}: listingData.items not found in page state")

        try:
            items = json.loads(items_raw)
        except ValueError as exc:
            raise ParsingError(f"{cls.store_slug}: listingData.items was not valid JSON") from exc

        return items, cls._has_next_page(state)

    @staticmethod
    def _has_next_page(state_text: str) -> bool:
        page_match = re.search(r'"listingPage":\s*(\d+)', state_text)
        count_match = re.search(r'"listingPagesCount":\s*(\d+)', state_text)
        if not page_match or not count_match:
            return False
        return int(page_match.group(1)) < int(count_match.group(1))

    @staticmethod
    def _extract_state_json_text(html_text: str) -> str | None:
        """The embedded state is a JS single-quoted string literal wrapping
        escaped JSON, not a bare object - it has to be string-unescaped
        before it's valid JSON at all. Some of its own text fields (page
        intro copy with embedded HTML links) carry inconsistent/double
        escaping that breaks strict JSON parsing of the WHOLE blob - so
        callers extract only the specific array they need (see
        _extract_bracket_array) rather than parsing this whole string.
        """
        start_idx = html_text.find(_STATE_MARKER)
        if start_idx == -1:
            return None
        start = start_idx + len(_STATE_MARKER)

        i = start
        n = len(html_text)
        while i < n:
            if html_text[i] == "\\":
                i += 2
                continue
            if html_text[i] == "'":
                break
            i += 1
        else:
            return None

        raw = html_text[start:i]
        return raw.replace("\\'", "'")

    @staticmethod
    def _extract_bracket_array(text: str, marker: str) -> str | None:
        idx = text.find(marker)
        if idx == -1:
            return None
        start = text.find("[", idx)
        if start == -1:
            return None

        depth = 0
        in_string = False
        escape = False
        i = start
        while i < len(text):
            ch = text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
            else:
                if ch == '"':
                    in_string = True
                elif ch == "[":
                    depth += 1
                elif ch == "]":
                    depth -= 1
                    if depth == 0:
                        return text[start : i + 1]
            i += 1
        return None

    @staticmethod
    def _extract_brand(item: dict) -> str | None:
        brands = item.get("brands") or []
        if brands and isinstance(brands[0], dict):
            return brands[0].get("name")
        return None

    @staticmethod
    def _extract_trailing_p_as_parfum(name: str) -> str | None:
        """See the module docstring's 2026-08-25 note - a trailing "- P"
        with no other concentration wording anywhere in the name means
        Parfum on this store, confirmed live."""
        if _TRAILING_P_PATTERN.search(name):
            return "Parfum"
        return None

    # -- fetch / parse ----------------------------------------------------

    async def fetch_product(self, candidate: _SearchCandidate) -> _SearchCandidate:
        # Nothing left to fetch - the listing page already carried every
        # variant's full price/stock/volume data (see search_perfume).
        return candidate

    async def parse_product(self, raw_product: _SearchCandidate) -> list[ScrapedOffer]:
        item = raw_product.item
        name = item.get("name") or ""
        brand = self._extract_brand(item)
        concentration = extract_concentration(name) or self._extract_trailing_p_as_parfum(name)
        perfume_name = extract_core_name(name, brand=brand)
        url_relative = item.get("urlRelative")

        offers = [
            offer
            for par in item.get("pars") or []
            if (
                offer := self._build_offer(
                    par,
                    name=name,
                    brand=brand,
                    perfume_name=perfume_name,
                    concentration=concentration,
                    url_relative=url_relative,
                )
            )
            is not None
        ]
        return offers

    def _build_offer(
        self,
        par: dict,
        *,
        name: str,
        brand: str | None,
        perfume_name: str | None,
        concentration: str | None,
        url_relative: str | None,
    ) -> ScrapedOffer | None:
        code = par.get("code")
        value = par.get("value")
        price_data = par.get("price") or {}
        price_decimal = (price_data.get("withVat") or {}).get("decimal")
        if not code or not value or price_decimal is None or not url_relative:
            return None

        try:
            price = Decimal(str(price_decimal))
        except InvalidOperation:
            return None

        old_price = None
        if (par.get("priceAction") or {}).get("sale"):
            rrp = price_data.get("rrpWithVat")
            if isinstance(rrp, dict) and rrp.get("decimal") is not None:
                try:
                    old_price = Decimal(str(rrp["decimal"]))
                except InvalidOperation:
                    old_price = None

        availability = "in_stock" if par.get("online") == 1 else "out_of_stock"

        return ScrapedOffer(
            store_slug=self.store_slug,
            raw_title=f"{name} {value}".strip(),
            product_url=f"{self.base_url}{url_relative}?c={code}",
            store_product_identifier=code,
            brand=brand,
            perfume_name=perfume_name,
            concentration=concentration,
            volume_ml=extract_volume_ml(value),
            tester=False,
            price=price,
            old_price=old_price,
            currency="RON",
            availability=availability,
        )
