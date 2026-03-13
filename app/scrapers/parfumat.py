import re

import requests
from bs4 import BeautifulSoup

from scrapers.base import BaseScraper, ScrapeResult


class ParfumatScraper(BaseScraper):
    shop_name = "Parfumat"

    def can_handle(self, url: str) -> bool:
        return "parfumat.ro" in url.lower()

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

        title = self._extract_title(soup, lines)
        title_index = self._find_best_title_index(lines, title)

        search_block = lines[title_index:title_index + 90] if title_index is not None else lines[:90]

        price = self._extract_first_price(search_block)
        in_stock = self._extract_stock(search_block)
        volume_ml = expected_volume_ml or self._extract_volume(title) or self._extract_volume(url)

        return ScrapeResult(
            shop_name=self.shop_name,
            url=url,
            title=title,
            price=price,
            currency="RON" if price is not None else None,
            in_stock=in_stock,
            volume_ml=volume_ml,
            raw_text="\n".join(search_block)[:1500],
        )

    def _normalize_lines(self, text: str) -> list[str]:
        result = []
        for line in text.splitlines():
            cleaned = re.sub(r"\s+", " ", line).strip()
            if cleaned:
                result.append(cleaned)
        return result

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
            if line.startswith("# "):
                return line.removeprefix("# ").strip()

        return None

    def _find_best_title_index(self, lines: list[str], title: str | None) -> int | None:
        if not title:
            return None

        normalized_title = self._norm(title)
        candidates = []

        for i, line in enumerate(lines):
            current = self._norm(line)
            if current == normalized_title or normalized_title in current:
                candidates.append(i)

        if not candidates:
            return None

        best_idx = None
        best_score = -1

        for idx in candidates:
            window = lines[idx:idx + 90]
            window_text = " ".join(window).lower()

            score = 0
            if "cod produs" in window_text:
                score += 5
            if "marca:" in window_text:
                score += 5
            if "adaugă în coș" in window_text or "adauga in cos" in window_text:
                score += 5
            if "ultimul produs" in window_text:
                score += 4
            if "lei" in window_text:
                score += 5

            if score > best_score or (score == best_score and (best_idx is None or idx > best_idx)):
                best_score = score
                best_idx = idx

        return best_idx

    def _extract_first_price(self, lines: list[str]) -> float | None:
        def is_noise_line(text: str) -> bool:
            low = text.lower()
            noise_tokens = [
                "review",
                "părerea clienților",
                "cod produs",
                "marca:",
                "livrare",
                "easybox",
                "locker",
                "gratuit",
                "whatsapp",
                "marți",
                "luni",
                "miercuri",
                "joi",
                "vineri",
                "sâmbătă",
                "duminică",
            ]
            return any(token in low for token in noise_tokens)

        # 1. Căutăm mai întâi prețul spart pe 3 linii: 279 / .00 / lei
        for i in range(len(lines) - 2):
            a = lines[i].strip()
            b = lines[i + 1].strip()
            c = lines[i + 2].strip().lower()

            if is_noise_line(a) or is_noise_line(b) or is_noise_line(c):
                continue

            if re.fullmatch(r"\d{2,5}", a) and re.fullmatch(r"[.,]\d{2}", b) and c == "lei":
                return self._parse_price(f"{a}{b}")

        # 2. Căutăm preț pe 2 linii: 279.00 / lei
        for i in range(len(lines) - 1):
            a = lines[i].strip()
            b = lines[i + 1].strip().lower()

            if is_noise_line(a) or is_noise_line(b):
                continue

            if re.fullmatch(r"\d+(?:[.,]\d{2})?", a) and b == "lei":
                return self._parse_price(a)

        # 3. Căutăm preț pe o singură linie, dar ignorăm livrările și alte zgomote
        for line in lines:
            if is_noise_line(line):
                continue

            match = re.search(r"(\d+(?:[.,]\d{2})?)\s*lei", line, re.IGNORECASE)
            if match:
                return self._parse_price(match.group(1))

        return None

    def _extract_stock(self, lines: list[str]) -> bool:
        text = " ".join(lines).lower()

        if "stoc epuizat" in text or "nu este în stoc" in text or "nu este in stoc" in text:
            return False

        if "ultimul produs" in text or "în stoc" in text or "in stoc" in text:
            return True

        if "adaugă în coș" in text or "adauga in cos" in text:
            return True

        return False

    def _extract_volume(self, text: str | None) -> int | None:
        if not text:
            return None
        match = re.search(r"(\d+)\s*ml", text, re.IGNORECASE)
        return int(match.group(1)) if match else None

    def _norm(self, text: str) -> str:
        return re.sub(r"\s+", " ", text).strip().lower()

    def _parse_price(self, value: str) -> float | None:
        cleaned = value.replace(",", ".").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None