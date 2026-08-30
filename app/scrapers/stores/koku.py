"""Koku.ro scraper.

Investigation summary:
- Buxus-platform store (a multi-country perfume/watch chain - koku.ro,
  .sk, .cz, .hu, .pl, .si, .hr, .bg, .gr, .ee, .lt, .lv all share this
  same platform, confirmed via hreflang alternates on every product's
  sitemap entry). robots.txt is wide open by default (`Disallow:` empty
  under `User-agent: *`) with only specific functional pages excluded
  (cart, account, and notably the search-results page itself,
  `/rezultatele-cautarii-pentru` - so, unlike Brasty, this store's own
  search cannot be used) - category/brand-filter pages are not excluded.
- A product sitemap exists (`/sitemaps/products_ro.xml`) but is huge
  (~17MB) and its URLs put the product TYPE word before the brand (e.g.
  "/apa-de-toaleta-antonio-banderas-the-secret"), the same unreliable-
  prefix problem Parfumat's sitemap had - brand-category browsing is used
  instead, same strategy as Fragranza/EsenteDeLux/Parfumat/Vivantis.
- Brand slugs are actually numeric IDs here, looked up from the main
  `/parfumuri` category page's own brand filter checkboxes
  (`input#fs-prop-brand-val-{id}` + its `label`'s
  `.filter-checkbox-list__label-text` text, e.g. id 13192 = "Antonio
  Banderas") rather than guessed - confirmed live this is the same
  `?brand={id}` parameter explicitly allowed in robots.txt
  (`Allow: /*?*brand=`). Brand-alias lookup (brand_lookup_candidates)
  is used the same way as every other directory-based scraper in this
  project - and, uniquely here, also to STRIP the brand out of a
  candidate's text: this store's URL slugs and variant titles spell some
  brands under their confirmed alias, not the name this app calls them
  (e.g. ".../apa-de-toaleta-christian-dior-sauvage" for a perfume
  monitored as brand "Dior", confirmed live) - stripping only the literal
  target brand left "christian" behind as an unrelated leftover token,
  dragging a real match's fuzzy score down for no reason. _strip_brand()
  tries every known alias, longest first, so a multi-word alias actually
  present in the text is consumed as a whole.
- Each brand's category page (`/parfumuri?brand={id}`, paginated via
  `&page=N`) lists PRODUCT FAMILIES, not individual bottle sizes - unlike
  Parfimo/Parfumat/Vivantis/Brasty (one size = one URL), each card here
  covers every size of one product and shows a PRICE RANGE ("de la
  102,00 lei până la 148,00 lei", confirmed live), the same "combinations
  on one product page" shape Fragranza uses. So, like Fragranza, a
  detail-page fetch is required per candidate - fetch_product() is not a
  pass-through here.
- The detail page renders every size variant server-side in one fetch
  (`li.product-variants-list__item > a[data-variant-value][title]` with
  a nested `.product-variants-list__item-price`) - no second request per
  variant needed. Each variant's own `title` attribute carries that
  variant's full name including concentration/volume and, importantly,
  whether THAT SPECIFIC variant is a tester - confirmed live on one real
  product where the 100ml size was "... - Tester 100ml" while the 200ml
  size of the very same product was plain "... 200ml" with no "Tester"
  wording at all. The page's own <h1> only reflects whichever variant
  happens to be selected by default (the tester, in that example) - using
  it instead of each variant's own title would have mislabeled the 200ml
  size as a tester too.
- Stock: `.product-variants-list__item-cta-disabled` is a real class
  referenced by this exact page's own JS (tooltip init) but never seen
  attached to a variant during live investigation - every sampled brand's
  catalog was fully in stock at the time. Availability is read from this
  class when present; unlike every other store's scraper in this project,
  the out-of-stock branch could not be confirmed against a real example -
  worth rechecking if a product silently comes back "not found" here.
- Price format: comma-decimal, no thousands grouping was observed in the
  values seen ("102,00 lei", "148,00 lei") - reuses the existing
  app.normalization.price.parse_price (same convention as Fragranza).
"""

import logging
from dataclasses import dataclass

from bs4 import BeautifulSoup
from bs4.element import Tag
from rapidfuzz import fuzz

from app.normalization.brand import brand_lookup_candidates, normalize_brand
from app.normalization.concentration import extract_concentration
from app.normalization.name import extract_core_name, normalize_name
from app.normalization.price import parse_price
from app.normalization.tester import is_tester
from app.normalization.volume import extract_volume_ml
from app.schemas.scraping import ScrapedOffer
from app.scrapers.base import BaseScraper
from app.scrapers.exceptions import ParsingError
from app.scrapers.registry import register_scraper

logger = logging.getLogger(__name__)

_MAX_CATEGORY_PAGES = 30


@dataclass(frozen=True)
class _ListingCandidate:
    product_url: str
    brand: str


@dataclass(frozen=True)
class _FetchedProduct:
    candidate: _ListingCandidate
    soup: BeautifulSoup


@register_scraper
class KokuScraper(BaseScraper):
    store_name = "Koku.ro"
    store_slug = "koku"
    base_url = "https://www.koku.ro"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._brand_id_cache: dict[str, str] | None = None

    # -- brand directory --------------------------------------------------

    async def _get_brand_id(self, brand: str) -> str | None:
        if self._brand_id_cache is None:
            self._brand_id_cache = await self._load_brand_directory()
        for candidate in brand_lookup_candidates(brand):
            brand_id = self._brand_id_cache.get(candidate)
            if brand_id is not None:
                return brand_id
        return None

    async def _load_brand_directory(self) -> dict[str, str]:
        response = await self.get("/parfumuri")
        soup = BeautifulSoup(response.text, "lxml")

        directory: dict[str, str] = {}
        for checkbox in soup.select('input.filter-checkbox-list__checkbox[id^="fs-prop-brand-val-"]'):
            checkbox_id = checkbox.get("id")
            label = soup.select_one(f'label[for="{checkbox_id}"] .filter-checkbox-list__label-text')
            if not checkbox_id or label is None:
                continue
            brand_id = checkbox_id.removeprefix("fs-prop-brand-val-")
            # Label text is "Brand Name (count)" - the count is in its own
            # nested <i>, stripped by only taking this element's direct
            # text rather than get_text() on the whole span.
            name = "".join(label.find_all(string=True, recursive=False)).strip()
            if not name:
                continue
            directory[normalize_brand(name)] = brand_id

        if not directory:
            raise ParsingError(f"{self.store_slug}: brand directory page structure not recognized")

        return directory

    # -- search (brand category browsing, not site search) ---------------

    async def search_perfume(self, brand: str, perfume_name: str) -> list[_ListingCandidate]:
        brand_id = await self._get_brand_id(brand)
        if brand_id is None:
            logger.info("%s: no brand category found for %s", self.store_slug, brand)
            return []

        ambiguous_threshold = self._settings.MATCH_NAME_AMBIGUOUS_THRESHOLD
        candidates: list[_ListingCandidate] = []
        page = 1

        while page <= _MAX_CATEGORY_PAGES:
            response = await self.get("/parfumuri", params={"brand": brand_id, "page": page})
            soup = BeautifulSoup(response.text, "lxml")

            items = soup.select("div.product-card")
            if not items:
                break

            for item in items:
                candidate = self._parse_listing_item(item, brand)
                if candidate is None:
                    continue
                if self._is_plausible_candidate(candidate, brand, perfume_name, ambiguous_threshold):
                    candidates.append(candidate)

            if not self._has_next_page(soup):
                break
            page += 1

        return candidates

    @staticmethod
    def _parse_listing_item(item: Tag, brand: str) -> _ListingCandidate | None:
        link = item.select_one("a.product-card__inner[href]")
        if link is None:
            return None
        return _ListingCandidate(product_url=link["href"], brand=brand)

    @staticmethod
    def _is_plausible_candidate(
        candidate: _ListingCandidate, target_brand: str, target_name: str, ambiguous_threshold: int
    ) -> bool:
        # The product URL slug is the cheapest available signal for the
        # name at discovery time (the listing card's title text would
        # work too, but the brand-filtered category page already trusts
        # this candidate's brand - see module docstring - so the slug
        # alone is enough for this permissive pre-filter; the
        # authoritative check happens later in matching_service once the
        # real title is known from the detail page).
        slug_as_text = candidate.product_url.rstrip("/").rsplit("/", 1)[-1].replace("-", " ")
        candidate_name = KokuScraper._strip_brand(slug_as_text, target_brand)
        target_normalized = normalize_name(target_name)
        if candidate_name == target_normalized:
            return True

        return fuzz.token_sort_ratio(candidate_name, target_normalized) >= ambiguous_threshold

    @staticmethod
    def _strip_brand(text: str, target_brand: str) -> str:
        # Regression: URL slugs and variant titles here spell some brands
        # under their confirmed-live alias, not the name this app calls
        # them (e.g. "christian-dior-sauvage...", never a bare "dior-
        # sauvage..." slug, for a perfume monitored as brand "Dior") - a
        # plain extract_core_name(text, brand=target_brand) only strips
        # the literal target name, leaving "christian" behind as an
        # unrelated leftover token that drags the fuzzy-match score down
        # for no real reason. Every known alias is tried, longest first,
        # so a multi-word alias actually present in the text is consumed
        # as a whole instead of leaving part of it behind.
        for alias in sorted(brand_lookup_candidates(target_brand), key=len, reverse=True):
            if alias in normalize_name(text):
                return extract_core_name(text, brand=alias)
        return extract_core_name(text, brand=target_brand)

    @staticmethod
    def _has_next_page(soup: BeautifulSoup) -> bool:
        return soup.select_one("li.product-list-pagination__item.fs-next a[href]") is not None

    # -- fetch / parse ------------------------------------------------------

    async def fetch_product(self, candidate: _ListingCandidate) -> _FetchedProduct:
        response = await self.get(candidate.product_url)
        return _FetchedProduct(candidate=candidate, soup=BeautifulSoup(response.text, "lxml"))

    async def parse_product(self, raw_product: _FetchedProduct) -> list[ScrapedOffer]:
        candidate = raw_product.candidate
        soup = raw_product.soup

        offers = [
            offer
            for item in soup.select("li.product-variants-list__item")
            if (offer := self._build_offer_from_variant(item, candidate)) is not None
        ]
        return offers

    def _build_offer_from_variant(self, item: Tag, candidate: _ListingCandidate) -> ScrapedOffer | None:
        link = item.select_one("a[data-variant-value]")
        price_el = item.select_one(".product-variants-list__item-price")
        if link is None or price_el is None:
            return None

        variant_title = (link.get("title") or "").removeprefix("Alege opțiunea produsului ").strip()
        if not variant_title:
            return None

        price = parse_price(price_el.get_text())
        if price is None:
            return None

        classes = link.get("class") or []
        out_of_stock = any("disabled" in cls for cls in classes)

        return ScrapedOffer(
            store_slug=self.store_slug,
            raw_title=variant_title,
            product_url=candidate.product_url,
            store_product_identifier=link.get("data-variant-value"),
            brand=candidate.brand,
            perfume_name=self._strip_brand(variant_title, candidate.brand),
            concentration=extract_concentration(variant_title),
            volume_ml=extract_volume_ml(variant_title),
            tester=is_tester(variant_title),
            price=price,
            old_price=None,
            currency="RON",
            availability="out_of_stock" if out_of_stock else "in_stock",
        )
