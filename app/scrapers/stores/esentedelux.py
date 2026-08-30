"""EsenteDeLux.ro scraper.

Investigation summary:
- PrestaShop store (a different theme/module set than Fragranza, so its
  structure was investigated independently rather than assumed identical).
  robots.txt is the same PrestaShop-generated block disallowing the search
  controller (controller=search / search_query=), so brand category
  browsing is used instead: /manufacturers -> /brand/{id}-{slug}, paginated
  with ?page=N (not disallowed).
- Listing titles mix brand and name into one string
  ("Amouage - Ciel Pour Femme Eau de Parfum pentru femei") - the brand is
  split off the front (this theme always separates them with " - "), and
  extract_core_name(title, brand=...) isolates the name for matching.
- Each product has up to three attribute groups: "Pentru cine?" (gender -
  irrelevant to variant identity, ignored), "Tip produs" (concentration),
  and "Volum" (volume, with tester folded in as a distinct value alongside
  plain sizes, e.g. "50 ml" vs "50 ml Tester" - a third pattern, different
  from both Fragranza and Parfimo where testers are wholly separate
  products/pages).
- Only the default/pre-selected combination's price is present in the
  initial server-rendered HTML. Other volume options require an AJAX
  request (verified against the live site):
      GET {product_url}?action=Refresh&id_product={id}&group[{gid}]={val}...&ajax=1
  returning JSON with `product_prices` and `product_add_to_cart` HTML
  fragments for that specific combination. One extra request per
  additional volume option on a matched product.
- Availability: the schema.org JSON-LD `availability` field was
  "PreOrder" on every product checked (8/8, across different brands/
  categories) - this store fulfills orders rather than holding tracked
  stock ("Comandă acum, livrare in 2-4 zile" messaging), so PreOrder means
  orderable, not unavailable. The consistently available signal across
  both the initial page and AJAX responses is whether a non-disabled
  "add to cart" button is present - used here instead of the
  "attribute-not-in-stock" CSS class, which was present even on
  demonstrably orderable combinations and so isn't a reliable signal.
"""

import logging
from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import urljoin

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
from app.scrapers.exceptions import ParsingError, RequestError
from app.scrapers.registry import register_scraper

logger = logging.getLogger(__name__)

_MAX_CATEGORY_PAGES = 20
_VOLUME_GROUP_LABEL = "volum"


@dataclass(frozen=True)
class _SearchCandidate:
    product_id: int
    product_url: str
    brand: str
    raw_title: str
    core_name: str


@dataclass(frozen=True)
class _FetchedProduct:
    candidate: _SearchCandidate
    soup: BeautifulSoup


@dataclass(frozen=True)
class _VariantGroups:
    fixed_params: dict[int, int]
    volume_group_id: int
    volume_options: list[tuple[int, str]]
    default_value_id: int | None


@register_scraper
class EsenteDeLuxScraper(BaseScraper):
    store_name = "EsenteDeLux.ro"
    store_slug = "esentedelux"
    base_url = "https://esentedelux.ro"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._brand_url_cache: dict[str, str] | None = None

    # -- brand directory -----------------------------------------------

    async def _get_brand_url(self, brand: str) -> str | None:
        if self._brand_url_cache is None:
            self._brand_url_cache = await self._load_brand_directory()
        for candidate in brand_lookup_candidates(brand):
            url = self._brand_url_cache.get(candidate)
            if url is not None:
                return url
        return None

    async def _load_brand_directory(self) -> dict[str, str]:
        response = await self.get("/manufacturers")
        soup = BeautifulSoup(response.text, "lxml")

        directory: dict[str, str] = {}
        for link in soup.select('a[href*="/brand/"]'):
            name = link.get_text(strip=True)
            href = link.get("href")
            if not name or not href:
                continue
            directory[normalize_brand(name)] = href

        if not directory:
            raise ParsingError(f"{self.store_slug}: brand directory page structure not recognized")

        return directory

    # -- search (brand category browsing, not site search) --------------

    async def search_perfume(self, brand: str, perfume_name: str) -> list[_SearchCandidate]:
        category_url = await self._get_brand_url(brand)
        if category_url is None:
            logger.info("%s: no brand category found for %s", self.store_slug, brand)
            return []

        ambiguous_threshold = self._settings.MATCH_NAME_AMBIGUOUS_THRESHOLD
        candidates: list[_SearchCandidate] = []
        page = 1

        while page <= _MAX_CATEGORY_PAGES:
            page_url = category_url if page == 1 else f"{category_url}?page={page}"
            response = await self.get(page_url)
            soup = BeautifulSoup(response.text, "lxml")

            items = soup.select("article.js-product-miniature")
            if not items:
                if page == 1:
                    raise ParsingError(f"{self.store_slug}: category page structure not recognized for {page_url}")
                break

            for item in items:
                candidate = self._parse_listing_item(item)
                if candidate is None:
                    continue
                if self._is_plausible_candidate(
                    candidate.brand, candidate.core_name, brand, perfume_name, ambiguous_threshold
                ):
                    candidates.append(candidate)

            if not self._has_next_page(soup, page):
                break
            page += 1

        return candidates

    def _parse_listing_item(self, item: Tag) -> _SearchCandidate | None:
        link = item.select_one("h2.product-title a[href]")
        if link is None:
            return None

        raw_title = link.get_text(strip=True)
        href = link.get("href")
        if not raw_title or not href:
            return None

        brand = raw_title.split(" - ", 1)[0].strip()
        clean_href = href.split("#", 1)[0]  # fragment is client-side only

        try:
            product_id = int(item.get("data-id-product", ""))
        except ValueError:
            return None

        return _SearchCandidate(
            product_id=product_id,
            product_url=urljoin(self.base_url, clean_href),
            brand=brand,
            raw_title=raw_title,
            core_name=extract_core_name(raw_title, brand=brand),
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

    @staticmethod
    def _has_next_page(soup: BeautifulSoup, current_page: int) -> bool:
        return soup.select_one(f'a[href*="page={current_page + 1}"]') is not None

    # -- fetch / parse ----------------------------------------------------

    async def fetch_product(self, candidate: _SearchCandidate) -> _FetchedProduct:
        response = await self.get(candidate.product_url)
        return _FetchedProduct(candidate=candidate, soup=BeautifulSoup(response.text, "lxml"))

    async def parse_product(self, raw_product: _FetchedProduct) -> list[ScrapedOffer]:
        candidate = raw_product.candidate
        soup = raw_product.soup

        groups = self._parse_variant_groups(soup)
        if groups is None:
            logger.debug("%s: no variant groups found for %s", self.store_slug, candidate.product_url)
            return []

        concentration = self._extract_group_concentration(soup)
        default_price = self._extract_price_from_soup(soup)
        default_availability = self._availability_from_soup(soup)

        offers: list[ScrapedOffer] = []
        for value_id, label in groups.volume_options:
            if value_id == groups.default_value_id:
                price, availability = default_price, default_availability
            else:
                price, availability = await self._fetch_combination(
                    candidate.product_url, candidate.product_id, groups.fixed_params, groups.volume_group_id, value_id
                )

            if price is None:
                continue

            raw_title = f"{candidate.raw_title} {label}".strip()
            offers.append(
                ScrapedOffer(
                    store_slug=self.store_slug,
                    raw_title=raw_title,
                    product_url=candidate.product_url,
                    store_product_identifier=str(value_id),
                    brand=candidate.brand,
                    perfume_name=candidate.core_name,
                    concentration=concentration,
                    volume_ml=extract_volume_ml(label),
                    tester=is_tester(label),
                    price=price,
                    old_price=None,
                    currency="RON",
                    availability=availability,
                )
            )

        return offers

    @staticmethod
    def _parse_variant_groups(soup: BeautifulSoup) -> _VariantGroups | None:
        container = soup.select_one("div.product-variants")
        if container is None:
            return None

        fixed_params: dict[int, int] = {}
        volume_group_id: int | None = None
        volume_options: list[tuple[int, str]] = []
        default_value_id: int | None = None

        for item in container.select(".product-variants-item"):
            label_el = item.select_one(".form-control-label")
            label = label_el.get_text(strip=True) if label_el else ""

            radios = item.select("input.input-radio")
            if radios:
                group_id = int(radios[0]["data-product-attribute"])
                if label.strip().lower() == _VOLUME_GROUP_LABEL:
                    volume_group_id = group_id
                    for radio in radios:
                        value_id = int(radio["value"])
                        volume_options.append((value_id, radio.get("title", "")))
                        if radio.get("checked") is not None:
                            default_value_id = value_id
                else:
                    checked = next((r for r in radios if r.get("checked") is not None), radios[0])
                    fixed_params[group_id] = int(checked["value"])
                continue

            select_el = item.select_one("select")
            if select_el is not None:
                group_id = int(select_el["data-product-attribute"])
                option = select_el.select_one("option[selected]") or select_el.select_one("option")
                if option is not None:
                    fixed_params[group_id] = int(option["value"])

        if volume_group_id is None or not volume_options:
            return None

        return _VariantGroups(
            fixed_params=fixed_params,
            volume_group_id=volume_group_id,
            volume_options=volume_options,
            default_value_id=default_value_id,
        )

    @staticmethod
    def _extract_group_concentration(soup: BeautifulSoup) -> str | None:
        for item in soup.select(".product-variants-item"):
            option = item.select_one("select option[selected]") or item.select_one("select option")
            if option is None:
                continue
            concentration = extract_concentration(option.get_text(strip=True))
            if concentration:
                return concentration
        return None

    @staticmethod
    def _extract_price_from_soup(soup: BeautifulSoup) -> Decimal | None:
        price_el = soup.select_one(".product-prices .current-price-value")
        return parse_price(price_el.get_text()) if price_el else None

    @staticmethod
    def _availability_from_soup(soup: BeautifulSoup) -> str:
        button = soup.select_one("button.add-to-cart")
        if button is None or button.has_attr("disabled"):
            return "out_of_stock"
        return "in_stock"

    async def _fetch_combination(
        self, product_url: str, product_id: int, fixed_params: dict[int, int], volume_group_id: int, value_id: int
    ) -> tuple[Decimal | None, str]:
        params: dict[str, str | int] = {"action": "Refresh", "id_product": product_id, "ajax": "1"}
        for group_id, val in fixed_params.items():
            params[f"group[{group_id}]"] = val
        params[f"group[{volume_group_id}]"] = value_id

        try:
            response = await self.get(product_url, params=params)
            data = response.json()
        except (RequestError, ValueError) as exc:
            logger.warning(
                "%s: combination refresh failed for %s (group %s=%s): %s",
                self.store_slug, product_url, volume_group_id, value_id, exc,
            )
            return None, "out_of_stock"

        price = self._extract_price_from_soup(BeautifulSoup(data.get("product_prices", ""), "lxml"))
        availability = self._availability_from_soup(BeautifulSoup(data.get("product_add_to_cart", ""), "lxml"))
        return price, availability
