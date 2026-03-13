import re
from playwright.sync_api import sync_playwright

from scrapers.base import BaseScraper, ScrapeResult


class DanielScraper(BaseScraper):
    shop_name = "Daniel"

    def can_handle(self, url: str) -> bool:
        return "parfumuri-timisoara.ro" in url.lower()

    def scrape(self, url: str, expected_volume_ml: int | None = None) -> ScrapeResult:
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
            )

            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2000)

            self._accept_cookies(page)

            title = self._extract_title(page)
            selected_volume = None

            if expected_volume_ml is not None:
                selected_volume = self._select_volume(page, expected_volume_ml)

            page.wait_for_timeout(2500)

            page_text = self._normalize_text(page.locator("body").inner_text())
            price = self._extract_price(page)
            in_stock = price is not None

            context.close()
            browser.close()

        return ScrapeResult(
            shop_name=self.shop_name,
            url=url,
            title=title,
            price=price,
            currency="RON" if price is not None else None,
            in_stock=in_stock,
            volume_ml=selected_volume or expected_volume_ml,
            raw_text=page_text[:1200],
        )

    def _accept_cookies(self, page) -> None:
        selectors = [
            "button:has-text('Sunt de acord')",
            "button:has-text('Accept')",
            "button:has-text('Accept all')",
            "button:has-text('OK')",
        ]

        for selector in selectors:
            try:
                btn = page.locator(selector).first
                if btn.count() > 0 and btn.is_visible():
                    btn.click(timeout=2000)
                    page.wait_for_timeout(1000)
                    return
            except Exception:
                pass

    def _extract_title(self, page) -> str | None:
        selectors = [
            "h1",
            ".product-name h1",
            ".product-view .product-name",
        ]

        for selector in selectors:
            try:
                el = page.locator(selector).first
                if el.count() > 0:
                    text = el.inner_text().strip()
                    if text:
                        return text
            except Exception:
                pass

        return None

    def _select_volume(self, page, expected_volume_ml: int) -> int | None:
        volume_texts = [
            f"{expected_volume_ml} ml",
            f"{expected_volume_ml}ML",
            str(expected_volume_ml),
        ]

        select_candidates = [
            "select",
            "select.required-entry",
            "select.super-attribute-select",
            "select.product-custom-option",
        ]

        for selector in select_candidates:
            try:
                select = page.locator(selector).first
                if select.count() == 0:
                    continue

                options = select.locator("option").all_inner_texts()
                options = [opt.strip() for opt in options if opt.strip()]

                for opt in options:
                    for wanted in volume_texts:
                        if wanted.lower() in opt.lower():
                            select.select_option(label=opt)
                            page.wait_for_timeout(2000)
                            return expected_volume_ml
            except Exception:
                pass

        # fallback pentru widgeturi custom
        click_candidates = [
            "text=Alege o optiune...",
            "text=Alege o opțiune...",
            ".chosen-single",
            ".select2-selection",
        ]

        for selector in click_candidates:
            try:
                trigger = page.locator(selector).first
                if trigger.count() == 0:
                    continue

                trigger.click(timeout=2000)
                page.wait_for_timeout(1000)

                for wanted in volume_texts:
                    option = page.locator(f"text={wanted}").first
                    if option.count() > 0 and option.is_visible():
                        option.click(timeout=2000)
                        page.wait_for_timeout(2500)
                        return expected_volume_ml
            except Exception:
                pass

        return None

    def _extract_price(self, page) -> float | None:
        selectors = [
            ".price",
            ".regular-price .price",
            ".special-price .price",
            ".price-box .price",
        ]

        found_prices = []

        for selector in selectors:
            try:
                texts = page.locator(selector).all_inner_texts()
                for text in texts:
                    price = self._parse_price(text)
                    if price is not None:
                        found_prices.append(price)
            except Exception:
                pass

        if found_prices:
            # alegem cel mai mare, ca să evităm cazurile unde "Pret de la"
            # coexistă cu valori auxiliare mici; dacă vrei, putem ajusta regula
            return max(found_prices)

        try:
            body_text = page.locator("body").inner_text()
            prices = re.findall(r"(\d{1,3}(?:\.\d{3})*,\d{2})\s*RON", body_text, re.IGNORECASE)
            parsed = [self._parse_price(p) for p in prices]
            parsed = [p for p in parsed if p is not None]
            if parsed:
                return max(parsed)
        except Exception:
            pass

        return None

    def _normalize_text(self, text: str) -> str:
        lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
        lines = [line for line in lines if line]
        return "\n".join(lines)

    def _parse_price(self, value: str) -> float | None:
        match = re.search(r"(\d{1,3}(?:\.\d{3})*,\d{2})", value)
        if not match:
            return None

        cleaned = match.group(1).replace(".", "").replace(",", ".").strip()
        return float(cleaned)