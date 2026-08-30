"""Parfumat.ro scraper.

Investigation summary:
- PrestaShop store (same platform family as Fragranza/EsenteDeLux/Parfimo).
  robots.txt disallows the search controller (controller=search,
  ?search_query=), so this scraper browses each brand's category page
  instead - not disallowed, and ?page=N pagination is explicitly allowed.
  A sitemap is also advertised (https://parfumat.ro/1_index_sitemap.xml,
  lastmod = today) but its ~40k URLs don't carry a reliable brand prefix
  the way Notino's do (/{brand-slug}/{name-slug}/) - a product-type word
  can come before the brand in the slug here (e.g.
  "apa-de-parfum-lattafa-qaaed-unisex-100-ml"), so prefix-matching isn't
  reliable; brand-category browsing is used instead, same strategy as
  Fragranza/EsenteDeLux.
- Brand slugs are looked up from the /parfumuri-de-brand manufacturer
  filter widget (`span[data-id^="m-"]`; `data-text` is the display name,
  `data-url` is the slug - the "m-" id prefix is confirmed specific to
  the manufacturer facet, not shared with other filter groups on the same
  page) rather than guessed - confirmed live that the display name can
  differ from the slug (e.g. "Christian Dior" -> "christian-dior"). The
  widget's own href doesn't do anything without JS, but its slug plugs
  directly into the real canonical category URL, /brand/{slug} - found by
  following the rel="next" pagination link on a real category page
  (.../brand/lattafa?page=2), a different, shorter path than
  /parfumuri-de-brand/{slug} which happens to serve identical content.
- Everything a ScrapedOffer needs (title, brand, price, old price,
  availability, product URL, a stable numeric id) is *usually* already
  present on the brand category listing itself
  (`article.product-miniature[data-id-product]`) - confirmed live that
  each bottle size is its own separate product/URL here (like Parfimo),
  not size combinations selectable on one product page (like Fragranza):
  a real product's own `.product-variants` container was confirmed empty
  on its detail page, and the listing price (`span.product-price
  [content]`) matched the detail page's price exactly. So unlike every
  other PrestaShop scraper in this project, no per-candidate detail-page
  fetch is needed for the common case - fetch_product() is a pass-through
  with no HTTP call, and parse_product() builds the offer from data
  already captured during search_perfume's listing pass.
  2026-08-25 update: not every listing title includes concentration
  wording though - confirmed live with "Paris Corner, Mawj Moscow Mule,
  Unisex, 100 ml" (comma-separated, no "Apa de Parfum"/"EDP" anywhere),
  which made extract_concentration() return None and get the whole offer
  correctly rejected downstream as "missing_variant_fields" (matching_
  service refuses to guess a variant's concentration) - not a matching
  bug, a real gap in what the listing alone provides for this specific
  product. fetch_product() now fetches the detail page ONLY when the
  listing title didn't yield a concentration, keeping the fast path
  fetch-free for the common case. Getting a *stable* source for it off
  that page took two tries: the `og:description` meta tag has the wording
  ("...Mawj Moscow Mule Eau de Parfum 100ml...") but is not reliable -
  confirmed live, two fetches of the very same product returned two
  different descriptions, one a generic template with no concentration
  wording at all, apparently rotated per-request rather than fixed per
  product. A blind `[itemprop="description"]` page scan isn't safe either
  - confirmed live, it matches 11 times on a real page (other products'
  cards in a "recommended" carousel carry the same markup). What's both
  stable AND scoped to this one specific product is `#product-details`'s
  own `data-product` JSON blob, which embeds the product's real long-form
  description (its own "features" list is always empty for this store,
  confirmed live, so that's not a usable structured source either).
- Stock: `.product-availability` renders `span.out-of-stock-product`
  ("Stoc epuizat") when unavailable; anything else (a plain "în stoc"
  span, or a low-stock warning like "ultimele 3 produse") means in stock.
- Price formatting: the current price's `content` attribute is always a
  clean decimal string regardless of display formatting. The struck-out
  old price (`.regular-price`) has no such attribute though, and its
  display text uses a dot as the decimal separator ("1099.00 lei") - the
  opposite convention from app.normalization.price.parse_price, which is
  built for the comma-decimal Romanian format Fragranza and others use
  ("625,99 lei") and does not match this site's text at all. Parsed here
  with a small dedicated pattern instead of reusing that one.
"""

import json
import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from bs4 import BeautifulSoup
from bs4.element import Tag
from rapidfuzz import fuzz

from app.normalization.brand import brand_lookup_candidates, normalize_brand
from app.normalization.concentration import extract_concentration
from app.normalization.name import extract_core_name, normalize_name
from app.normalization.tester import is_tester
from app.normalization.volume import extract_volume_ml
from app.schemas.scraping import ScrapedOffer
from app.scrapers.base import BaseScraper
from app.scrapers.exceptions import ParsingError
from app.scrapers.registry import register_scraper

logger = logging.getLogger(__name__)

_MAX_CATEGORY_PAGES = 30
# No thousands separator observed in any real price on this site (up to
# ~3000 lei checked live) - just plain digits before the decimal dot.
_DOT_DECIMAL_PRICE_PATTERN = re.compile(r"\b(\d+)\.(\d{2})\b")


@dataclass(frozen=True)
class _ListingCandidate:
    product_url: str
    product_id: str
    brand: str
    raw_title: str
    price: Decimal
    old_price: Decimal | None
    availability: str


@dataclass(frozen=True)
class _FetchedProduct:
    candidate: _ListingCandidate
    # None when the listing title already had a concentration - see
    # fetch_product().
    detail_html: str | None


@register_scraper
class ParfumatScraper(BaseScraper):
    store_name = "Parfumat.ro"
    store_slug = "parfumat"
    base_url = "https://parfumat.ro"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._brand_slug_cache: dict[str, str] | None = None

    # -- brand directory --------------------------------------------------

    async def _get_brand_slug(self, brand: str) -> str | None:
        if self._brand_slug_cache is None:
            self._brand_slug_cache = await self._load_brand_directory()
        for candidate in brand_lookup_candidates(brand):
            slug = self._brand_slug_cache.get(candidate)
            if slug is not None:
                return slug
        return None

    async def _load_brand_directory(self) -> dict[str, str]:
        response = await self.get("/parfumuri-de-brand")
        soup = BeautifulSoup(response.text, "lxml")

        directory: dict[str, str] = {}
        for span in soup.select('span[data-id^="m-"]'):
            name = span.get("data-text")
            slug = span.get("data-url")
            if not name or not slug:
                continue
            directory[normalize_brand(name)] = slug

        if not directory:
            raise ParsingError(f"{self.store_slug}: brand directory page structure not recognized")

        return directory

    # -- search (brand category browsing, not site search) ---------------

    async def search_perfume(self, brand: str, perfume_name: str) -> list[_ListingCandidate]:
        brand_slug = await self._get_brand_slug(brand)
        if brand_slug is None:
            logger.info("%s: no brand category found for %s", self.store_slug, brand)
            return []

        ambiguous_threshold = self._settings.MATCH_NAME_AMBIGUOUS_THRESHOLD
        candidates: list[_ListingCandidate] = []
        page = 1

        while page <= _MAX_CATEGORY_PAGES:
            page_url = f"/brand/{brand_slug}" if page == 1 else f"/brand/{brand_slug}?page={page}"
            response = await self.get(page_url)
            soup = BeautifulSoup(response.text, "lxml")

            items = soup.select("article.product-miniature")
            if not items:
                # Unlike Fragranza, a resolved brand slug here is not a
                # guarantee of >=1 product - the manufacturer facet this
                # site's brand directory is scraped from lists brands it
                # has ever carried, and a brand with none currently in
                # stock renders a real, correctly-titled page (confirmed
                # live: <title>BDK Parfums</title>) with no
                # article.product-miniature at all, not a broken/
                # redesigned one. So an empty page 1 is a legitimate "no
                # products for this brand" result, not a parsing failure.
                break

            for item in items:
                candidate = self._parse_listing_item(item)
                if candidate is None:
                    continue
                if self._is_plausible_candidate(
                    candidate.brand, candidate.raw_title, brand, perfume_name, ambiguous_threshold
                ):
                    candidates.append(candidate)

            if not self._has_next_page(soup):
                break
            page += 1

        return candidates

    @staticmethod
    def _parse_listing_item(item: Tag) -> _ListingCandidate | None:
        product_id = item.get("data-id-product")
        link = item.select_one("h3.product-title a[href]")
        brand_el = item.select_one(".product-brand a")
        price_el = item.select_one(".product-price-and-shipping .product-price")

        if not product_id or link is None or brand_el is None or price_el is None:
            return None

        price = ParfumatScraper._parse_price_element(price_el)
        if price is None:
            return None

        old_price = None
        old_price_el = item.select_one(".product-price-and-shipping .regular-price")
        if old_price_el is not None:
            old_price = ParfumatScraper._parse_dot_decimal_price(old_price_el.get_text())

        availability_el = item.select_one(".product-availability")
        out_of_stock = availability_el is not None and availability_el.select_one(".out-of-stock-product") is not None

        return _ListingCandidate(
            product_url=link["href"],
            product_id=product_id,
            brand=brand_el.get_text(strip=True),
            raw_title=link.get_text(strip=True),
            price=price,
            old_price=old_price,
            availability="out_of_stock" if out_of_stock else "in_stock",
        )

    @staticmethod
    def _parse_price_element(price_el: Tag) -> Decimal | None:
        # The current price carries a clean numeric `content` attribute
        # (e.g. content="999") - preferred over parsing the "999.00 lei"
        # display text, but that text parse is kept as a fallback in case
        # a listing variant ever omits the attribute.
        content = price_el.get("content")
        if content:
            try:
                return Decimal(content)
            except InvalidOperation:
                pass
        return ParfumatScraper._parse_dot_decimal_price(price_el.get_text())

    @staticmethod
    def _parse_dot_decimal_price(text: str) -> Decimal | None:
        match = _DOT_DECIMAL_PRICE_PATTERN.search(text)
        if not match:
            return None
        try:
            return Decimal(f"{match.group(1)}.{match.group(2)}")
        except InvalidOperation:
            return None

    @staticmethod
    def _is_plausible_candidate(
        item_brand: str, raw_title: str, target_brand: str, target_name: str, ambiguous_threshold: int
    ) -> bool:
        # Alias-aware, not a bare equality check: the store's own listing
        # can display a brand under a different (also-correct) name than
        # the one this app calls it - confirmed live, Dior's own product
        # cards here read "Christian Dior", not "Dior" (see
        # brand_lookup_candidates).
        if normalize_brand(item_brand) not in brand_lookup_candidates(target_brand):
            return False

        candidate_name = extract_core_name(raw_title, brand=item_brand)
        target_normalized = normalize_name(target_name)
        if candidate_name == target_normalized:
            return True

        return fuzz.token_sort_ratio(candidate_name, target_normalized) >= ambiguous_threshold

    @staticmethod
    def _has_next_page(soup: BeautifulSoup) -> bool:
        return soup.select_one('a[rel="next"]') is not None

    # -- fetch / parse ------------------------------------------------------
    # Fetches the detail page only when the listing title didn't yield a
    # concentration - see module docstring's 2026-08-25 update. The common
    # case (title already has it) stays fetch-free.

    async def fetch_product(self, candidate: _ListingCandidate) -> _FetchedProduct:
        if extract_concentration(candidate.raw_title) is not None:
            return _FetchedProduct(candidate=candidate, detail_html=None)

        response = await self.get(candidate.product_url)
        return _FetchedProduct(candidate=candidate, detail_html=response.text)

    async def parse_product(self, raw_product: _FetchedProduct) -> list[ScrapedOffer]:
        candidate = raw_product.candidate

        concentration = extract_concentration(candidate.raw_title)
        if concentration is None and raw_product.detail_html is not None:
            concentration = self._extract_concentration_from_detail_page(raw_product.detail_html)

        return [
            ScrapedOffer(
                store_slug=self.store_slug,
                raw_title=candidate.raw_title,
                product_url=candidate.product_url,
                store_product_identifier=candidate.product_id,
                brand=candidate.brand,
                perfume_name=extract_core_name(candidate.raw_title, brand=candidate.brand),
                concentration=concentration,
                volume_ml=extract_volume_ml(candidate.raw_title),
                tester=is_tester(candidate.raw_title) or is_tester(candidate.product_url),
                price=candidate.price,
                old_price=candidate.old_price,
                currency="RON",
                availability=candidate.availability,
            )
        ]

    @staticmethod
    def _extract_concentration_from_detail_page(detail_html: str) -> str | None:
        # og:description was tried first and dropped - confirmed live it
        # isn't stable (two fetches of the same product returned two
        # different meta descriptions, one generic template text with no
        # concentration wording at all, apparently rotated/templated
        # rather than fixed per product). No structured "features" entry
        # exists for concentration here either (confirmed live: the JSON
        # below always carries an empty "features": [] for this store).
        # What IS stable is the product's own long-form description,
        # embedded as one JSON field inside `#product-details`'s
        # `data-product` attribute - scoped to this one specific product
        # (unlike a generic `[itemprop="description"]` page scan, which
        # picks up 11 matches on a real page - other products' cards in a
        # "recommended" carousel carry the same markup and would risk
        # contaminating the match).
        soup = BeautifulSoup(detail_html, "lxml")
        container = soup.select_one("#product-details")
        if container is None or not container.get("data-product"):
            return None

        try:
            data = json.loads(container["data-product"])
        except ValueError:
            return None

        description = data.get("description")
        if not description:
            return None
        return extract_concentration(description)
