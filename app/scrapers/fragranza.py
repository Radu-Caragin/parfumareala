import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from scrapers.base import BaseScraper, ScrapeResult


class FragranzaScraper(BaseScraper):
    shop_name = "Fragranza"

    def can_handle(self, url: str) -> bool:
        return "fragranza.ro" in url.lower()

    def scrape(self, url: str, expected_volume_ml: int | None = None) -> ScrapeResult:
        clean_url = url.split("#")[0]

        response = requests.get(
            clean_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                )
            },
            timeout=20,
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")
        page_text = self._normalize_text(soup.get_text("\n"))

        title = self._extract_title(soup, page_text)
        section = self._extract_product_section(page_text)
        variants = self._extract_variants(section)

        target_volume = expected_volume_ml or self._extract_volume_from_url(url)
        chosen = self._pick_variant(variants, target_volume)

        return ScrapeResult(
            shop_name=self.shop_name,
            url=url,
            title=title,
            price=chosen["price"] if chosen else None,
            currency="RON",
            in_stock=chosen["in_stock"] if chosen else False,
            volume_ml=chosen["volume_ml"] if chosen else target_volume,
            raw_text=section[:1000],
        )

    def _normalize_text(self, text: str) -> str:
        lines = [line.strip() for line in text.splitlines()]
        lines = [line for line in lines if line]
        return "\n".join(lines)

    def _extract_title(self, soup: BeautifulSoup, text: str) -> str | None:
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(" ", strip=True)
            if title:
                return title

        og_title = soup.find("meta", attrs={"property": "og:title"})
        if og_title and og_title.get("content"):
            return og_title["content"].strip()

        title_match = re.search(r"([A-Z][^\n]{10,120})", text)
        return title_match.group(1).strip() if title_match else None

    def _extract_product_section(self, text: str) -> str:
        start = text.find("Volum:")
        if start == -1:
            return text

        end_candidates = [
            text.find("Cantitate", start),
            text.find("Descrierea produsului", start),
            text.find("Clienții care au cumpărat", start),
        ]
        end_candidates = [pos for pos in end_candidates if pos != -1]
        end = min(end_candidates) if end_candidates else len(text)

        return text[start:end]

    def _extract_variants(self, section: str) -> list[dict]:
        pattern = re.compile(
            r"(?P<price>\d{1,3}(?:\.\d{3})*,\d{2})\s*lei"
            r"(?:\s*Salvați\s*\d{1,3}(?:\.\d{3})*,\d{2}\s*lei)?"
            r"\s*(?P<volume>\d+)\s*ml"
            r"(?:\s*(?P<stock>În stoc|Anunță-mă când este disponibil))?",
            re.IGNORECASE,
        )

        variants = []
        seen = set()

        for match in pattern.finditer(section):
            volume_ml = int(match.group("volume"))
            price = self._parse_price(match.group("price"))
            stock_text = (match.group("stock") or "").strip().lower()

            key = (volume_ml, price)
            if key in seen:
                continue
            seen.add(key)

            variants.append(
                {
                    "volume_ml": volume_ml,
                    "price": price,
                    "in_stock": stock_text != "anunță-mă când este disponibil",
                }
            )

        return sorted(variants, key=lambda x: x["volume_ml"])

    def _pick_variant(self, variants: list[dict], target_volume: int | None) -> dict | None:
        if not variants:
            return None

        if target_volume is not None:
            for variant in variants:
                if variant["volume_ml"] == target_volume:
                    return variant

        if len(variants) == 1:
            return variants[0]

        return variants[0]

    def _extract_volume_from_url(self, url: str) -> int | None:
        parsed = urlparse(url)
        combined = f"{parsed.path} {parsed.fragment}"

        match = re.search(r"(\d+)_ml", combined, re.IGNORECASE)
        if match:
            return int(match.group(1))

        match = re.search(r"(\d+)\s*ml", combined, re.IGNORECASE)
        if match:
            return int(match.group(1))

        return None

    def _parse_price(self, value: str) -> float:
        cleaned = value.replace(".", "").replace(",", ".").strip()
        return float(cleaned)