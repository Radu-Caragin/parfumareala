import re

import requests
from bs4 import BeautifulSoup

from scrapers.base import BaseScraper, ScrapeResult


class OrioudhScraper(BaseScraper):
    shop_name = "Orioudh"

    def can_handle(self, url: str) -> bool:
        return "orioudh.ro" in url.lower()

    def scrape(self, url: str, expected_volume_ml: int | None = None) -> ScrapeResult:
        response = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7",
            },
            timeout=20,
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")
        lines = self._normalize_lines(soup.get_text("\n"))
        page_text = "\n".join(lines)

        brand = self._extract_brand(lines)
        title = self._extract_title(soup, lines)

        full_title = title
        if brand and title and not title.lower().startswith(brand.lower()):
            full_title = f"{brand} {title}"

        price = self._extract_price(lines)
        in_stock = self._extract_stock(page_text)
        volume_ml = (
            expected_volume_ml
            or self._extract_volume(title)
            or self._extract_volume(page_text)
            or self._extract_volume(url)
        )

        return ScrapeResult(
            shop_name=self.shop_name,
            url=url,
            title=full_title,
            price=price,
            currency="RON" if price is not None else None,
            in_stock=in_stock,
            volume_ml=volume_ml,
            raw_text=page_text[:1500],
        )

    def _normalize_lines(self, text: str) -> list[str]:
        result = []
        for line in text.splitlines():
            cleaned = re.sub(r"\s+", " ", line).strip()
            if cleaned:
                result.append(cleaned)
        return result

    def _extract_brand(self, lines: list[str]) -> str | None:
        for i, line in enumerate(lines):
            if line.startswith("### ") and i + 1 < len(lines):
                brand = line.removeprefix("### ").strip()
                if brand:
                    return brand
        return None

    def _extract_title(self, soup: BeautifulSoup, lines: list[str]) -> str | None:
        h1 = soup.find("h1")
        if h1:
            text = h1.get_text(" ", strip=True)
            if text:
                return text

        for line in lines:
            if line.startswith("# "):
                return line.removeprefix("# ").strip()

        meta_title = soup.find("meta", attrs={"property": "og:title"})
        if meta_title and meta_title.get("content"):
            title = meta_title["content"].strip()
            if "|" in title:
                title = title.split("|")[0].strip()
            return title

        return None

    def _extract_price(self, lines: list[str]) -> float | None:
        # preferăm "Sale Price", apoi "Regular Price", apoi "Default Title - xxx lei"
        for i, line in enumerate(lines):
            if line == "Sale Price" and i + 1 < len(lines):
                parsed = self._parse_price(lines[i + 1])
                if parsed is not None:
                    return parsed

        for i, line in enumerate(lines):
            if line == "Regular Price" and i + 1 < len(lines):
                parsed = self._parse_price(lines[i + 1])
                if parsed is not None:
                    return parsed

        for line in lines:
            if "Default Title" in line:
                parsed = self._parse_price(line)
                if parsed is not None:
                    return parsed

        for line in lines:
            parsed = self._parse_price(line)
            if parsed is not None:
                return parsed

        return None

    def _extract_stock(self, page_text: str) -> bool:
        text = page_text.lower()

        if "sold out" in text:
            return False
        if "in stoc" in text or "în stoc" in text:
            return True
        if "adaugat in cos" in text or "adauga in cos" in text:
            return True

        return False

    def _extract_volume(self, text: str | None) -> int | None:
        if not text:
            return None

        match = re.search(r"(\d+)\s*ml\b", text, re.IGNORECASE)
        if match:
            return int(match.group(1))

        return None

    def _parse_price(self, text: str) -> float | None:
        match = re.search(r"(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)\s*lei", text, re.IGNORECASE)
        if not match:
            return None

        value = match.group(1).replace(".", "").replace(",", ".").strip()
        try:
            return float(value)
        except ValueError:
            return None