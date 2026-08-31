"""Brasty.ro scraper.

Investigation summary:
- robots.txt has no blanket Disallow for general crawlers (only archival/
  scraper-specific bots - ia_archiver, WebZip, WebCopier, etc. - are
  blocked). No Cloudflare TLS fingerprinting encountered anywhere during
  investigation - plain httpx works throughout, unlike Vivantis/Notino.
- 2026-08-25 redesign note: the original version of this scraper browsed
  each brand's category page (looked up from a /toate-marcile/parfumuri
  brand directory), the same strategy as Fragranza/EsenteDeLux/Parfumat.
  Dropped after two real, live failures were reported and confirmed:
  1. "Lattafa" has no brand directory entry, and even the plain
     /lattafa category page (which does resolve, with the correct
     <h1>Lattafa</h1>) lists zero products - yet a real, in-stock
     product ("Lattafa Khamrah Eau de Parfum unisex 100 ml") exists at
     its own direct URL, with no link back to ANY brand category
     anywhere on its own page. A genuine catalog/categorization gap on
     Brasty's side, not something browsing-by-category can ever recover
     from since there is no HTML path from the brand name to this
     product at all.
  2. "Dior" resolves in the directory only as "Christian Dior" (a real
     brand-alias mismatch, confirmed to affect Parfumat too) - browsing
     by category needs the exact catalog name, not the name a user (or
     this app) actually calls the brand.
  Both are solved by using the site's own product search instead of
  category browsing: `/produkty/naseptavac?text={query}` ("naseptavac"
  is Czech for "whisperer/suggester" - Brasty is part of the Czech-
  founded Brasty Group, like Vivantis) is the JSON backing the site's
  own search-box autocomplete (`<input name="q" data-whispaper-url=
  "/produkty/naseptavac?text=">` on every page). Queried live with
  "lattafa khamrah" it returns the exact product (plus its size/flanker
  siblings) despite the category-browsing dead end above; queried with
  "dior sauvage" it returns real hits too, because the site's own search
  already handles the brand alias internally - its `name` field literally
  reads "Dior (Christian Dior) Sauvage ...". Each suggestion already
  carries a real, VAT-inclusive price and stock text, so no per-candidate
  detail-page fetch is needed here either - fetch_product() is a
  pass-through with no HTTP call, same as the dropped category-page
  version. This endpoint is not disallowed in robots.txt and is queried
  with full "{brand} {name}" phrases, exactly what typing into the site's
  own search box produces - not a bulk/unintended use of an autocomplete
  meant for keystroke-by-keystroke queries.
- The suggester returns loosely-matched results for almost any input
  (confirmed live: even a nonsense query returns unrelated toothpaste/
  skincare products whose names happen to share a word) - never a hard
  "nothing found" signal - so, same as every other store, real filtering
  happens downstream: a coarse brand-substring pre-check here, then the
  usual extract_core_name() + fuzzy-match gate.
- Because search is now site-wide instead of confined to one brand's own
  category page, a candidate's brand can no longer be trusted-by-
  construction (the dropped version safely assumed a fetched category
  page's items were all the requested brand) - there's also no separate
  "brand" field in the suggester JSON to read instead (unlike the
  dropped version's per-item GTM blob, which did have one - see below).
  ScrapedOffer.brand is set to the already-resolved target brand instead
  (ambiguous_threshold discovery is intentionally permissive; the
  authoritative brand/name check happens later in matching_service).
- Price formatting: a dot is used as a THOUSANDS separator, not a
  decimal one, and no product was ever seen with a fractional price
  (confirmed live: "1.145 lei" = 1145 lei, not 1.145) - the opposite
  convention from app.normalization.price.parse_price (comma-decimal,
  Fragranza-style), so it isn't reused here - parsed with a small
  dedicated pattern instead. No old/crossed-out price was found anywhere
  live - old_price is always None here, not a gap to fix later.
- Stock: the suggester's own `stock_string` field is free text ("în
  stoc", sometimes with a trailing low-stock count like "în stoc 1 buc",
  or "nu se află în stoc" when unavailable) - the out-of-stock phrase is
  checked for directly, since it's the only reliable signal (there's no
  CSS class to key off here, unlike the dropped category-page version).
- A "(Common Alias)" aside sometimes follows the brand in the suggester's
  `name` field (e.g. "Dior (Christian Dior) Sauvage Parfum bărbați 200
  ml", confirmed live) - left in place, it pollutes extract_core_name()'s
  output with extra unstripped tokens once the leading brand word alone
  is removed, tanking the fuzzy-match score for no real reason. Stripped
  only for name-matching purposes - ScrapedOffer.raw_title keeps the
  original text.
"""

import json
import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin

from app.normalization.brand import normalize_brand
from app.normalization.concentration import extract_concentration
from app.normalization.name import extract_core_name, names_plausibly_match, normalize_name
from app.normalization.tester import is_tester
from app.normalization.text_utils import strip_diacritics
from app.normalization.volume import extract_volume_ml
from app.schemas.scraping import ScrapedOffer
from app.scrapers.base import BaseScraper
from app.scrapers.exceptions import ParsingError
from app.scrapers.registry import register_scraper

logger = logging.getLogger(__name__)

_THOUSANDS_DOT_PRICE_PATTERN = re.compile(r"(\d{1,3}(?:\.\d{3})*)\s*lei", re.IGNORECASE)
_PAREN_ALIAS_PATTERN = re.compile(r"\([^)]*\)")


@dataclass(frozen=True)
class _SearchCandidate:
    product_url: str
    product_id: str | None
    brand: str
    raw_title: str
    price: Decimal
    availability: str


@register_scraper
class BrastyScraper(BaseScraper):
    store_name = "Brasty.ro"
    store_slug = "brasty"
    base_url = "https://www.brasty.ro"

    # -- search (the site's own search-box suggester endpoint) -----------

    async def search_perfume(self, brand: str, perfume_name: str) -> list[_SearchCandidate]:
        query = f"{brand} {perfume_name}".strip()
        response = await self.get("/produkty/naseptavac", params={"text": query})

        try:
            data = json.loads(response.text)
        except ValueError as exc:
            raise ParsingError(f"{self.store_slug}: suggester response was not valid JSON") from exc

        suggestions = data.get("suggestions")
        if suggestions is None:
            raise ParsingError(f"{self.store_slug}: suggester response structure not recognized")

        ambiguous_threshold = self._settings.MATCH_NAME_AMBIGUOUS_THRESHOLD
        candidates: list[_SearchCandidate] = []

        for suggestion in suggestions:
            item = suggestion.get("data") or {}
            if item.get("type") != "product":
                continue

            candidate = self._build_candidate(item, brand)
            if candidate is None:
                continue
            if self._is_plausible_candidate(candidate.raw_title, brand, perfume_name, ambiguous_threshold):
                candidates.append(candidate)

        return candidates

    @staticmethod
    def _build_candidate(item: dict, brand: str) -> _SearchCandidate | None:
        name = item.get("name")
        url = item.get("url")
        price_text = item.get("price")

        if not name or not url or not price_text:
            return None

        price = BrastyScraper._parse_price(price_text)
        if price is None:
            return None

        stock_text = strip_diacritics(item.get("stock_string") or "").lower()
        out_of_stock = "nu se afla in stoc" in stock_text

        return _SearchCandidate(
            product_url=urljoin(BrastyScraper.base_url, url),
            product_id=item.get("code"),
            brand=brand,
            raw_title=name,
            price=price,
            availability="out_of_stock" if out_of_stock else "in_stock",
        )

    @staticmethod
    def _parse_price(text: str) -> Decimal | None:
        match = _THOUSANDS_DOT_PRICE_PATTERN.search(text)
        if not match:
            return None
        try:
            return Decimal(match.group(1).replace(".", ""))
        except InvalidOperation:
            return None

    @staticmethod
    def _name_for_matching(raw_title: str) -> str:
        return _PAREN_ALIAS_PATTERN.sub(" ", raw_title)

    @staticmethod
    def _is_plausible_candidate(
        raw_title: str, target_brand: str, target_name: str, ambiguous_threshold: int
    ) -> bool:
        # Coarse pre-check: search is site-wide now, not confined to one
        # already-resolved brand's own page, so a completely unrelated
        # brand must be ruled out before even trying a name match (see
        # module docstring).
        if normalize_brand(target_brand) not in normalize_name(raw_title):
            return False

        cleaned_title = BrastyScraper._name_for_matching(raw_title)
        candidate_name = extract_core_name(cleaned_title, brand=target_brand)
        target_normalized = normalize_name(target_name)
        return names_plausibly_match(candidate_name, target_normalized, ambiguous_threshold)

    # -- fetch / parse ------------------------------------------------------
    # No HTTP call needed here - see module docstring: everything a
    # ScrapedOffer needs was already captured from the suggester response.

    async def fetch_product(self, candidate: _SearchCandidate) -> _SearchCandidate:
        return candidate

    async def parse_product(self, raw_product: _SearchCandidate) -> list[ScrapedOffer]:
        candidate = raw_product
        cleaned_title = self._name_for_matching(candidate.raw_title)
        return [
            ScrapedOffer(
                store_slug=self.store_slug,
                raw_title=candidate.raw_title,
                product_url=candidate.product_url,
                store_product_identifier=candidate.product_id,
                brand=candidate.brand,
                perfume_name=extract_core_name(cleaned_title, brand=candidate.brand),
                concentration=extract_concentration(candidate.raw_title),
                volume_ml=extract_volume_ml(candidate.raw_title),
                tester=is_tester(candidate.raw_title) or is_tester(candidate.product_url),
                price=candidate.price,
                old_price=None,
                currency="RON",
                availability=candidate.availability,
            )
        ]
