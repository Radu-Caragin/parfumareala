import re

from playwright.sync_api import sync_playwright

from scrapers.base import BaseScraper, ScrapeResult


class NotinoScraper(BaseScraper):
    shop_name = "Notino"

    def can_handle(self, url: str) -> bool:
        return "notino." in url.lower()

    def scrape(self, url: str, expected_volume_ml: int | None = None) -> ScrapeResult:
        title, page_text = self._fetch_visible_text(url)

        variants = self._extract_variants(page_text)

        target_volume = expected_volume_ml
        if target_volume is None:
            target_volume = self._extract_volume_from_url(url)
        if target_volume is None:
            target_volume = self._extract_first_visible_volume(page_text)

        chosen = self._pick_variant(variants, target_volume)

        text_lower = page_text.lower()
        in_stock = (
            ("în stoc" in text_lower or "in stoc" in text_lower)
            and "anunță-mă când este disponibil" not in text_lower
        )

        return ScrapeResult(
            shop_name=self.shop_name,
            url=url,
            title=title,
            price=chosen["price"] if chosen else None,
            currency="RON",
            in_stock=in_stock,
            volume_ml=chosen["volume_ml"] if chosen else target_volume,
            raw_text=page_text[:1500],
        )

    def _fetch_visible_text(self, url: str) -> tuple[str | None, str]:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                locale="ro-RO",
                viewport={"width": 1400, "height": 1000},
                extra_http_headers={
                    "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7",
                },
            )

            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60000)

            self._try_accept_cookies(page)

            page.wait_for_timeout(4000)

            title = None
            try:
                h1 = page.locator("h1").first
                if h1.count() > 0:
                    title = h1.inner_text().strip()
            except Exception:
                title = None

            try:
                page_text = page.locator("body").inner_text(timeout=10000)
            except Exception:
                page_text = page.content()

            context.close()
            browser.close()

        page_text = self._normalize_text(page_text)
        return title, page_text

    def _try_accept_cookies(self, page) -> None:
        selectors = [
            "button:has-text('Accept')",
            "button:has-text('Accept all')",
            "button:has-text('Sunt de acord')",
            "button:has-text('Accept toate')",
            "button:has-text('Înțeleg')",
            "button:has-text('OK')",
        ]

        for selector in selectors:
            try:
                button = page.locator(selector).first
                if button.count() > 0 and button.is_visible():
                    button.click(timeout=2000)
                    page.wait_for_timeout(1000)
                    return
            except Exception:
                pass

    def _normalize_text(self, text: str) -> str:
        lines = []
        for line in text.splitlines():
            cleaned = re.sub(r"\s+", " ", line).strip()
            if cleaned:
                lines.append(cleaned)
        return "\n".join(lines)

    def _extract_variants(self, page_text: str) -> list[dict]:
        lines = page_text.splitlines()
        best_by_volume: dict[int, float] = {}

        # Caz 1: "100 ml 432 RON"
        inline_pattern = re.compile(
            r"(?P<volume>\d+)\s*ml\s+(?P<price>\d[\d\.,]*)\s*RON",
            re.IGNORECASE,
        )
        for match in inline_pattern.finditer(page_text):
            volume_ml = int(match.group("volume"))
            price = self._parse_price(match.group("price"))
            self._update_best(best_by_volume, volume_ml, price)

        # Caz 2: blocuri pe linii separate:
        # 100 ml
        # 541 RON
        # 432 RON folosind codul xmas
        for i, line in enumerate(lines):
            volume_match = re.fullmatch(r"(\d+)\s*ml", line, re.IGNORECASE)
            if not volume_match:
                continue

            volume_ml = int(volume_match.group(1))
            nearby_lines = self._collect_until_next_volume(lines, i + 1)

            for nearby in nearby_lines:
                price_match = re.search(r"(\d[\d\.,]*)\s*RON", nearby, re.IGNORECASE)
                if price_match:
                    price = self._parse_price(price_match.group(1))
                    self._update_best(best_by_volume, volume_ml, price)

        # Caz 3: "432 RON / 100 ml"
        ratio_pattern = re.compile(
            r"(?P<price>\d[\d\.,]*)\s*RON\s*/\s*(?P<volume>\d+)\s*ml",
            re.IGNORECASE,
        )
        for match in ratio_pattern.finditer(page_text):
            volume_ml = int(match.group("volume"))
            price = self._parse_price(match.group("price"))
            self._update_best(best_by_volume, volume_ml, price)

        return [
            {"volume_ml": volume_ml, "price": price}
            for volume_ml, price in sorted(best_by_volume.items())
        ]

    def _collect_until_next_volume(self, lines: list[str], start_index: int) -> list[str]:
        collected = []

        for line in lines[start_index:]:
            if re.fullmatch(r"(\d+)\s*ml", line, re.IGNORECASE):
                break
            collected.append(line)

            if len(collected) >= 8:
                break

        return collected

    def _extract_volume_from_url(self, url: str) -> int | None:
        match = re.search(r"(\d+)[-_]?ml", url, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None

    def _extract_first_visible_volume(self, page_text: str) -> int | None:
        match = re.search(r"\b(\d+)\s*ml\b", page_text, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None

    def _pick_variant(self, variants: list[dict], target_volume: int | None) -> dict | None:
        if not variants:
            return None

        if target_volume is not None:
            for variant in variants:
                if variant["volume_ml"] == target_volume:
                    return variant

        return variants[0]

    def _update_best(self, best_by_volume: dict[int, float], volume_ml: int, price: float) -> None:
        if volume_ml not in best_by_volume or price < best_by_volume[volume_ml]:
            best_by_volume[volume_ml] = price

    def _parse_price(self, value: str) -> float:
        cleaned = value.strip()

        if "," in cleaned and "." in cleaned:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        elif "," in cleaned:
            cleaned = cleaned.replace(",", ".")
        else:
            cleaned = cleaned.replace(".", "")

        return float(cleaned)