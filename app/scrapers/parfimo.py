import re

import requests
from bs4 import BeautifulSoup

from scrapers.base import BaseScraper, ScrapeResult


class ParfimoScraper(BaseScraper):
    shop_name = "Parfimo"

    def can_handle(self, url: str) -> bool:
        return "parfimo.ro" in url.lower()

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

        title = self._extract_title(soup, lines)
        main_block = self._extract_main_block(lines, title)

        variants = self._extract_variants(main_block)

        target_volume = expected_volume_ml or self._extract_volume_from_url(url)
        want_tester = self._url_mentions_tester(url)

        chosen = self._pick_variant(
            variants=variants,
            target_volume=target_volume,
            want_tester=want_tester,
        )

        return ScrapeResult(
            shop_name=self.shop_name,
            url=url,
            title=title,
            price=chosen["price"] if chosen else None,
            currency="RON" if chosen and chosen["price"] is not None else None,
            in_stock=chosen["in_stock"] if chosen else False,
            volume_ml=chosen["volume_ml"] if chosen else target_volume,
            raw_text="\n".join(main_block)[:1500] if main_block else page_text[:1500],
        )

    def _normalize_lines(self, text: str) -> list[str]:
        lines = []
        for line in text.splitlines():
            cleaned = re.sub(r"\s+", " ", line).strip()
            if cleaned:
                lines.append(cleaned)
        return lines

    def _extract_title(self, soup: BeautifulSoup, lines: list[str]) -> str | None:
        h1 = soup.find("h1")
        if h1:
            text = h1.get_text(" ", strip=True)
            if text:
                return text

        meta_title = soup.find("meta", attrs={"property": "og:title"})
        if meta_title and meta_title.get("content"):
            title = meta_title["content"].strip()
            if "|" in title:
                title = title.split("|")[0].strip()
            return title

        for line in lines:
            if "Apă de parfum" in line or "Apă de toaletă" in line or "Extract de parfum" in line:
                return line

        return None

    def _extract_main_block(self, lines: list[str], title: str | None) -> list[str]:
        start_idx = 0

        if title:
            for i, line in enumerate(lines):
                if title.strip() in line.strip():
                    start_idx = i
                    break

        end_idx = len(lines)
        stop_markers = {
            "Descriere",
            "Descrierea produsului",
            "Descoperiți mai multe",
            "Review",
            "Review 1x",
            "Produse similare",
            "Produse asociate",
            "Alte produse din gamă",
        }

        for i in range(start_idx + 1, len(lines)):
            if lines[i] in stop_markers:
                end_idx = i
                break

        return lines[start_idx:end_idx]

    def _extract_variants(self, lines: list[str]) -> list[dict]:
        variants = []

        variant_indices = []
        for i, line in enumerate(lines):
            if self._looks_like_variant_line(line):
                variant_indices.append(i)

        for idx, start in enumerate(variant_indices):
            end = variant_indices[idx + 1] if idx + 1 < len(variant_indices) else len(lines)
            block = lines[start:end]
            label = block[0]

            volume_ml = self._extract_volume_from_text(label)
            if volume_ml is None:
                continue

            is_tester = "tester" in label.lower()
            is_refill = "reincarcabil" in label.lower() or "reîncărcabil" in label.lower()

            price = self._extract_price_from_block(block)
            in_stock = self._extract_stock_from_block(block)

            variants.append(
                {
                    "volume_ml": volume_ml,
                    "price": price,
                    "in_stock": in_stock,
                    "is_tester": is_tester,
                    "is_refill": is_refill,
                    "label": label,
                }
            )

        return variants

    def _looks_like_variant_line(self, line: str) -> bool:
        line_lower = line.lower().strip()

        if not re.search(r"\b\d+\s*ml\b", line_lower):
            return False

        # evităm titlul principal, dar permitem "100 ml tester"
        if "apă de parfum" in line_lower or "apă de toaletă" in line_lower or "extract de parfum" in line_lower:
            return False

        return True

    def _extract_volume_from_text(self, text: str) -> int | None:
        match = re.search(r"(\d+)\s*ml", text, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None

    def _extract_price_from_block(self, block: list[str]) -> float | None:
        block_text = "\n".join(block)

        # preferăm prețul explicit LEI din blocul curent
        matches = re.findall(
            r"(\d{1,3}(?:[ .]\d{3})*(?:,\d{2})?)\s*LEI",
            block_text,
            re.IGNORECASE,
        )

        if matches:
            return self._parse_price(matches[0])

        return None

    def _extract_stock_from_block(self, block: list[str]) -> bool:
        block_text = " ".join(block).lower()

        if "nu este în stoc" in block_text or "nu este in stoc" in block_text:
            return False

        if "în stoc" in block_text or "in stoc" in block_text:
            return True

        return False

    def _pick_variant(self, variants: list[dict], target_volume: int | None, want_tester: bool) -> dict | None:
        if not variants:
            return None

        candidates = variants

        if target_volume is not None:
            same_volume = [v for v in candidates if v["volume_ml"] == target_volume]
            if same_volume:
                candidates = same_volume

        if want_tester:
            tester_candidates = [v for v in candidates if v["is_tester"]]
            if tester_candidates:
                candidates = tester_candidates
        else:
            non_tester_candidates = [v for v in candidates if not v["is_tester"]]
            if non_tester_candidates:
                candidates = non_tester_candidates

        in_stock_candidates = [v for v in candidates if v["in_stock"]]
        if in_stock_candidates:
            candidates = in_stock_candidates

        # preferăm non-refill și apoi primul bloc valid
        candidates = sorted(candidates, key=lambda v: (v["is_refill"], v["price"] is None, v["price"] or 0))
        return candidates[0] if candidates else None

    def _url_mentions_tester(self, url: str) -> bool:
        return "tester" in url.lower()

    def _extract_volume_from_url(self, url: str) -> int | None:
        match = re.search(r"(\d+)[-_ ]?ml", url, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None

    def _parse_price(self, value: str) -> float | None:
        cleaned = value.replace(" ", "").replace(".", "").replace(",", ".").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None