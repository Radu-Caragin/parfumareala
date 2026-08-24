"""Fragranza.ro scraper.

Investigation summary (Phase 9):
- PrestaShop store. robots.txt disallows the search controller
  (controller=search / search_query), so this scraper browses each
  brand's category page instead (e.g. /xerjoff) - not disallowed, and
  pagination via ?page=N is explicitly allowed.
- Brand slugs are looked up from the /brands directory page rather than
  guessed, to avoid slugification mistakes on multi-word/accented names.
- Everything needed (listing + variant combinations, prices, stock) is
  present in the initial server-rendered HTML - no JavaScript execution
  or AJAX calls are required.
- Testers are separate products (their own URL/page), not a combination
  attribute alongside volume - tester detection runs on the combined
  brand/name/type text, same as any other title.
- Brand category pages also list non-fragrance products (makeup, etc.);
  these naturally fail matching later since they have no detectable
  concentration, so no special-case filtering is needed here.
"""

import json
import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from bs4 import BeautifulSoup
from bs4.element import Tag
from rapidfuzz import fuzz

from app.normalization.brand import normalize_brand
from app.normalization.concentration import extract_concentration
from app.normalization.name import normalize_name
from app.normalization.price import parse_price
from app.normalization.tester import is_tester
from app.normalization.volume import extract_volume_ml
from app.schemas.scraping import ScrapedOffer
from app.scrapers.base import BaseScraper
from app.scrapers.exceptions import ParsingError
from app.scrapers.registry import register_scraper

logger = logging.getLogger(__name__)

_MAX_CATEGORY_PAGES = 20


@dataclass(frozen=True)
class _ListingCandidate:
    product_url: str
    brand: str
    name: str
    type_text: str


@dataclass(frozen=True)
class _FetchedProduct:
    candidate: _ListingCandidate
    soup: BeautifulSoup


@register_scraper
class FragranzaScraper(BaseScraper):
    store_name = "Fragranza.ro"
    store_slug = "fragranza"
    base_url = "https://fragranza.ro"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._brand_url_cache: dict[str, str] | None = None

    # -- brand directory -----------------------------------------------

    async def _get_brand_url(self, brand: str) -> str | None:
        if self._brand_url_cache is None:
            self._brand_url_cache = await self._load_brand_directory()
        return self._brand_url_cache.get(normalize_brand(brand))

    async def _load_brand_directory(self) -> dict[str, str]:
        response = await self.get("/brands")
        soup = BeautifulSoup(response.text, "lxml")

        directory: dict[str, str] = {}
        for link in soup.select("div.brand-infos a[href]"):
            name = link.get_text(strip=True)
            if not name:
                continue
            directory[normalize_brand(name)] = link["href"]

        if not directory:
            raise ParsingError(f"{self.store_slug}: brand directory page structure not recognized")

        return directory

    # -- search (brand category browsing, not site search) -------------

    async def search_perfume(self, brand: str, perfume_name: str) -> list[_ListingCandidate]:
        category_url = await self._get_brand_url(brand)
        if category_url is None:
            logger.info("%s: no brand category found for %s", self.store_slug, brand)
            return []

        ambiguous_threshold = self._settings.MATCH_NAME_AMBIGUOUS_THRESHOLD
        candidates: list[_ListingCandidate] = []
        page = 1

        while page <= _MAX_CATEGORY_PAGES:
            page_url = category_url if page == 1 else f"{category_url}?page={page}"
            response = await self.get(page_url)
            soup = BeautifulSoup(response.text, "lxml")

            if page == 1 and soup.select_one("#js-product-list") is None:
                raise ParsingError(f"{self.store_slug}: category page structure not recognized for {page_url}")

            items = soup.select("article.product-miniature")
            if not items:
                break

            for item in items:
                candidate = self._parse_listing_item(item)
                if candidate is None:
                    continue
                if self._is_plausible_candidate(
                    candidate.brand, candidate.name, brand, perfume_name, ambiguous_threshold
                ):
                    candidates.append(candidate)

            if not self._has_next_page(soup, page):
                break
            page += 1

        return candidates

    @staticmethod
    def _parse_listing_item(item: Tag) -> _ListingCandidate | None:
        link = item.select_one("h2.product-title a[href]")
        brand_el = item.select_one(".product-name-manufacturer")
        name_el = item.select_one(".product-name-middle")
        type_el = item.select_one(".product-name-type")

        if link is None or brand_el is None or name_el is None:
            return None

        return _ListingCandidate(
            product_url=link["href"],
            brand=brand_el.get_text(strip=True),
            name=name_el.get_text(strip=True),
            type_text=type_el.get_text(strip=True) if type_el else "",
        )

    @staticmethod
    def _is_plausible_candidate(
        item_brand: str, item_name: str, target_brand: str, target_name: str, ambiguous_threshold: int
    ) -> bool:
        """Cheap brand+name pre-filter deciding whether a listing entry is
        worth fetching in full. Deliberately permissive - the authoritative
        match (brand, name, concentration, volume, tester) happens later in
        matching_service once the exact variant is known.
        """
        if normalize_brand(item_brand) != normalize_brand(target_brand):
            return False

        candidate_name = normalize_name(item_name)
        target_normalized = normalize_name(target_name)
        if candidate_name == target_normalized:
            return True

        return fuzz.token_sort_ratio(candidate_name, target_normalized) >= ambiguous_threshold

    @staticmethod
    def _has_next_page(soup: BeautifulSoup, current_page: int) -> bool:
        return soup.select_one(f'a[href*="page={current_page + 1}"]') is not None

    # -- fetch / parse product page -------------------------------------

    async def fetch_product(self, candidate: _ListingCandidate) -> _FetchedProduct:
        response = await self.get(candidate.product_url)
        return _FetchedProduct(candidate=candidate, soup=BeautifulSoup(response.text, "lxml"))

    async def parse_product(self, raw_product: _FetchedProduct) -> list[ScrapedOffer]:
        candidate = raw_product.candidate
        soup = raw_product.soup

        raw_title = f"{candidate.brand} {candidate.name} {candidate.type_text}".strip()
        concentration = extract_concentration(candidate.type_text) or extract_concentration(raw_title)
        tester = is_tester(raw_title) or is_tester(candidate.product_url)

        combinations = soup.select("div.product-variants ul.radio-buttons li")
        if combinations:
            offers = [
                offer
                for li in combinations
                if (offer := self._parse_combination(li, candidate, raw_title, concentration, tester)) is not None
            ]
            if offers:
                return offers

        offer = self._parse_single_variant(soup, candidate, raw_title, concentration, tester)
        return [offer] if offer else []

    def _parse_combination(
        self, li: Tag, candidate: _ListingCandidate, raw_title: str, concentration: str | None, tester: bool
    ) -> ScrapedOffer | None:
        radio = li.select_one("input.input-radio")
        price_el = li.select_one(".variant-price")
        attr_name_el = li.select_one(".attr-name")
        availability_el = li.select_one(".variant-availability")

        if radio is None or price_el is None or availability_el is None:
            return None

        price = parse_price(price_el.get_text())
        if price is None:
            return None

        old_price = None
        reduction_el = li.select_one(".attr-reduction")
        if reduction_el is not None:
            old_price = parse_price(reduction_el.get_text())

        availability = "in_stock" if "yes" in availability_el.get("class", []) else "out_of_stock"
        volume_ml = extract_volume_ml(attr_name_el.get_text()) if attr_name_el else None

        return ScrapedOffer(
            store_slug=self.store_slug,
            raw_title=raw_title,
            product_url=candidate.product_url,
            store_product_identifier=radio.get("value"),
            brand=candidate.brand,
            perfume_name=candidate.name,
            concentration=concentration,
            volume_ml=volume_ml,
            tester=tester,
            price=price,
            old_price=old_price,
            currency="RON",
            availability=availability,
        )

    def _parse_single_variant(
        self, soup: BeautifulSoup, candidate: _ListingCandidate, raw_title: str, concentration: str | None, tester: bool
    ) -> ScrapedOffer | None:
        offer_data = self._extract_json_ld_offer(soup)
        if offer_data is None:
            return None

        price, availability, sku, offer_url = offer_data

        # A single-combination product renders no radio buttons at all, so
        # its volume never appears in visible text - it's only encoded in
        # the JSON-LD offer URL's fragment, e.g. ".../product#/32-volum-100_ml".
        fragment_hint = offer_url.split("#", 1)[1].replace("_", " ") if "#" in offer_url else ""
        volume_ml = extract_volume_ml(raw_title) or extract_volume_ml(fragment_hint)

        return ScrapedOffer(
            store_slug=self.store_slug,
            raw_title=raw_title,
            product_url=candidate.product_url,
            store_product_identifier=sku,
            brand=candidate.brand,
            perfume_name=candidate.name,
            concentration=concentration,
            volume_ml=volume_ml,
            tester=tester,
            price=price,
            old_price=None,
            currency="RON",
            availability=availability,
        )

    @staticmethod
    def _extract_json_ld_offer(soup: BeautifulSoup) -> tuple[Decimal, str, str | None, str] | None:
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string or "")
            except (ValueError, TypeError):
                continue

            if data.get("@type") != "Product":
                continue

            offers = data.get("offers")
            if not isinstance(offers, dict):
                continue

            try:
                price = Decimal(str(offers["price"]))
            except (KeyError, InvalidOperation):
                continue

            availability = "in_stock" if "InStock" in str(offers.get("availability", "")) else "out_of_stock"
            return price, availability, offers.get("sku"), str(offers.get("url", ""))

        return None
