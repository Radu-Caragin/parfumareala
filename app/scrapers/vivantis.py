import re

from playwright.sync_api import sync_playwright

from scrapers.base import BaseScraper, ScrapeResult


class VivantisScraper(BaseScraper):
    shop_name = "Vivantis"

    def can_handle(self, url: str) -> bool:
        return "vivantis.ro" in url.lower()

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
                extra_http_headers={
                    "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7",
                },
            )

            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            self._try_accept_cookies(page)
            page.wait_for_timeout(3500)

            title = self._extract_title(page)
            page_text = self._normalize_text(page.locator("body").inner_text(timeout=10000))

            target_volume = expected_volume_ml
            if target_volume is None:
                target_volume = self._extract_volume_from_url(url)
            if target_volume is None:
                target_volume = self._extract_first_visible_volume(page_text)

            # întâi încercăm să extragem prețul exact din cardul volumului cerut
            price = None
            if target_volume is not None:
                price = self._extract_price_for_volume_card(page, target_volume)

            # fallback: prețul mare principal de pe pagină
            if price is None:
                price = self._extract_main_price(page)

            in_stock = self._is_in_stock(page_text)

            context.close()
            browser.close()

        return ScrapeResult(
            shop_name=self.shop_name,
            url=url,
            title=title,
            price=price,
            currency="RON" if price is not None else None,
            in_stock=in_stock,
            volume_ml=target_volume,
            raw_text=page_text[:1500],
        )

    def _try_accept_cookies(self, page) -> None:
        selectors = [
            "button:has-text('Accept')",
            "button:has-text('Accept all')",
            "button:has-text('Sunt de acord')",
            "button:has-text('Accept toate')",
            "button:has-text('OK')",
            "button:has-text('Înțeleg')",
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

    def _extract_title(self, page) -> str | None:
        try:
            h1 = page.locator("h1").first
            if h1.count() > 0:
                text = h1.inner_text().strip()
                if text:
                    return text
        except Exception:
            pass

        return None

    def _extract_price_for_volume_card(self, page, target_volume: int) -> float | None:
        js = """
(targetVolume) => {
            const isVisible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return (
                    style.display !== "none" &&
                    style.visibility !== "hidden" &&
                    parseFloat(style.opacity || "1") > 0 &&
                    rect.width > 0 &&
                    rect.height > 0
                );
            };

            const normalize = (txt) => (txt || "").replace(/\\s+/g, " ").trim();
            const volumeRegex = new RegExp(`\\\\b${targetVolume}\\\\s*ml\\\\b`, "i");
            const priceRegex = /(\\d{1,3}(?:\\.\\d{3})*)\\s*lei/i;

            let best = null;

            const elements = Array.from(document.querySelectorAll("button, a, div, li, span, label"));

            for (const el of elements) {
                if (!isVisible(el)) continue;

                const text = normalize(el.innerText);
                if (!text) continue;
                if (text.length > 120) continue;
                if (!volumeRegex.test(text)) continue;

                const priceMatch = text.match(priceRegex);
                if (!priceMatch) continue;

                let score = text.length;

                if (new RegExp(`^${targetVolume}\\\\s*ml`, "i").test(text)) {
                    score -= 30;
                }

                if (/\\/\\s*\\d+\\s*ml/i.test(text)) {
                    score += 20;
                }

                if (text.includes("Adaugă în coș") || text.includes("Adauga in cos")) {
                    score += 20;
                }

                if (!best || score < best.score) {
                    best = {
                        score,
                        price: priceMatch[1],
                        text,
                    };
                }
            }

            return best ? best.price : null;
        }
        """

        try:
            raw_price = page.evaluate(js, target_volume)
            if raw_price:
                return self._parse_price(raw_price)
        except Exception:
            pass

        return None

    def _extract_main_price(self, page) -> float | None:
        js = """
() => {
            const isVisible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return (
                    style.display !== "none" &&
                    style.visibility !== "hidden" &&
                    parseFloat(style.opacity || "1") > 0 &&
                    rect.width > 0 &&
                    rect.height > 0
                );
            };

            const normalize = (txt) => (txt || "").replace(/\\s+/g, " ").trim();
            const exactPriceRegex = /^(\\d{1,3}(?:\\.\\d{3})*)\\s*lei$/i;

            let candidates = [];
            const elements = Array.from(document.querySelectorAll("div, span, strong, p"));

            for (const el of elements) {
                if (!isVisible(el)) continue;

                const text = normalize(el.innerText);
                if (!text) continue;
                if (text.length > 20) continue;

                const match = text.match(exactPriceRegex);
                if (match) {
                    candidates.push(match[1]);
                }
            }

            return candidates.length ? candidates[0] : null;
        }
        """

        try:
            raw_price = page.evaluate(js)
            if raw_price:
                return self._parse_price(raw_price)
        except Exception:
            pass

        return None

    def _normalize_text(self, text: str) -> str:
        lines = []
        for line in text.splitlines():
            cleaned = re.sub(r"\s+", " ", line).strip()
            if cleaned:
                lines.append(cleaned)
        return "\n".join(lines)

    def _extract_volume_from_url(self, url: str) -> int | None:
        match = re.search(r"(\\d+)[-_]?ml", url, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None

    def _extract_first_visible_volume(self, text: str) -> int | None:
        match = re.search(r"\\b(\\d+)\\s*ml\\b", text, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None

    def _is_in_stock(self, text: str) -> bool:
        text_lower = text.lower()
        return (
            "adaugă în coș" in text_lower
            or "adauga in cos" in text_lower
            or "în stoc" in text_lower
            or "in stoc" in text_lower
        )

    def _parse_price(self, value: str) -> float | None:
        cleaned = value.replace(".", "").replace(",", ".").strip()

        try:
            return float(cleaned)
        except ValueError:
            return None