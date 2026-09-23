"""Discover perfume URLs from a public Fragrantica wardrobe.

Fragrantica renders member shelves client-side and seals the AJAX payload
used by that component.  Trying to reproduce that private protocol would be
both brittle and tightly coupled to Fragrantica's JavaScript.  This scraper
therefore uses a real browser only for the discovery step.  Individual
perfume pages are still fetched by :mod:`app.scrapers.fragrantica` with
``curl_cffi``.

Only the "Perfumes I Have" shelf is returned.  "I Want" and "I Had" are
deliberately ignored.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag
from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import RequestException as CurlRequestException

from app.config.settings import get_settings
from app.scrapers.exceptions import RequestError
from app.scrapers.fragrantica import InvalidFragranticaUrl, parse_url

_ALLOWED_HOSTS = {"fragrantica.com", "www.fragrantica.com"}
_PROFILE_PATH = re.compile(r"^/@[A-Za-z0-9._-]+/?$")
_SPACE = re.compile(r"\s+")


class InvalidFragranticaProfileUrl(ValueError):
    """Raised before opening a browser when the supplied URL is not a profile."""


class WardrobeScrapingError(RequestError):
    """Raised when the public wardrobe cannot be loaded or interpreted."""


def validate_profile_url(url: str) -> str:
    """Validate and normalize a public ``fragrantica.com/@handle`` URL."""
    value = url.strip()
    parsed = urlparse(value)
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or parsed.hostname is None
        or parsed.hostname.lower() not in _ALLOWED_HOSTS
        or not _PROFILE_PATH.fullmatch(parsed.path)
    ):
        raise InvalidFragranticaProfileUrl(f"Not a Fragrantica profile URL: {url!r}")

    return urlunparse(("https", "www.fragrantica.com", parsed.path.rstrip("/"), "", "", ""))


def parse_owned_perfume_urls(html: str, *, base_url: str = "https://www.fragrantica.com") -> list[str]:
    """Extract canonical perfume URLs from rendered wardrobe markup.

    The parser intentionally finds the shelf by its visible label instead of
    relying on Fragrantica's generated CSS classes.  Those classes change far
    more often than the user-facing shelf name.
    """
    soup = BeautifulSoup(html, "lxml")
    shelf = _find_owned_shelf(soup)
    if shelf is None:
        raise WardrobeScrapingError("fragrantica wardrobe: 'Perfumes I Have' shelf was not found")

    urls: list[str] = []
    seen: set[str] = set()
    for anchor in shelf.select('a[href*="/perfume/"]'):
        href = anchor.get("href")
        if not isinstance(href, str):
            continue
        canonical = _canonical_perfume_url(href, base_url=base_url)
        if canonical is None:
            continue
        if canonical not in seen:
            seen.add(canonical)
            urls.append(canonical)
    return urls


def parse_owned_shelf_payload(payload: object) -> list[str]:
    """Extract owned perfume URLs from Fragrantica's decoded shelf data."""
    if not isinstance(payload, list):
        raise WardrobeScrapingError("fragrantica wardrobe: invalid shelf response")

    owned_shelf = next(
        (
            shelf
            for shelf in payload
            if isinstance(shelf, dict)
            and shelf.get("type") == "wardrobe"
            and shelf.get("field") == "relation"
            and shelf.get("value") == "have"
        ),
        None,
    )
    if owned_shelf is None or not isinstance(owned_shelf.get("perfumes"), list):
        raise WardrobeScrapingError("fragrantica wardrobe: 'Perfumes I Have' shelf was not found")

    urls: list[str] = []
    seen: set[str] = set()
    for perfume in owned_shelf["perfumes"]:
        if not isinstance(perfume, dict) or not isinstance(perfume.get("url"), str):
            continue
        canonical = _canonical_perfume_url(perfume["url"], base_url="https://www.fragrantica.com")
        if canonical is not None and canonical not in seen:
            seen.add(canonical)
            urls.append(canonical)
    return urls


def _canonical_perfume_url(value: str, *, base_url: str) -> str | None:
    absolute = urljoin(base_url, value)
    parsed = urlparse(absolute)
    canonical = urlunparse(("https", "www.fragrantica.com", parsed.path, "", "", ""))
    try:
        parse_url(canonical)
    except InvalidFragranticaUrl:
        return None
    return canonical


def _find_owned_shelf(soup: BeautifulSoup) -> Tag | None:
    labels: list[Tag] = []
    for tag in soup.find_all(True):
        direct_text = " ".join(str(node) for node in tag.find_all(string=True, recursive=False))
        attribute_text = " ".join(
            str(tag.get(attribute) or "") for attribute in ("title", "aria-label", "data-title", "name")
        )
        if _is_owned_label(f"{direct_text} {attribute_text}"):
            labels.append(tag)

    # The first ancestor containing perfume links is the shelf component/card,
    # rather than a common parent that also contains I Want and I Had.
    for label in labels:
        current: Tag | None = label
        for _ in range(10):
            if current is None:
                break
            if current.select_one('a[href*="/perfume/"]') is not None:
                return current
            current = current.parent if isinstance(current.parent, Tag) else None
    return None


def _is_owned_label(value: str) -> bool:
    normalized = _SPACE.sub(" ", value).strip().lower()
    normalized = re.sub(r"\(\s*\d+\s*\)$", "", normalized).strip()
    return normalized in {"have", "i have", "perfumes i have", "perfumes you have"}


async def fetch_owned_perfume_urls(profile_url: str) -> list[str]:
    """Render a public profile and return URLs from its owned shelf.

    Google Chrome is tried first because this Windows project already uses it
    in ``start_server.bat``.  Playwright's managed Chromium is a fallback for
    environments where it has been installed separately.
    """
    normalized_url = validate_profile_url(profile_url)
    settings = get_settings()
    timeout_ms = max(15_000, round(settings.REQUEST_TIMEOUT * 1_000))

    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover - depends on local installation
        raise WardrobeScrapingError(
            "fragrantica wardrobe: Playwright is not installed; run pip install -r requirements.txt"
        ) from exc

    try:
        profile_html, sealed_shelves, cookies = await _fetch_profile_data(normalized_url)
        async with async_playwright() as playwright:
            browser = await _launch_browser(playwright)
            try:
                context = await browser.new_context()
                if cookies:
                    await context.add_cookies(
                        [
                            {
                                "name": name,
                                "value": value,
                                "domain": ".fragrantica.com",
                                "path": "/",
                                "secure": True,
                            }
                            for name, value in cookies.items()
                        ]
                    )
                page = await context.new_page()

                # A direct navigation from headless Chromium is challenged by
                # Cloudflare.  curl_cffi already fetched this exact public
                # document with Chrome impersonation, so serve that response
                # to the page while allowing its normal scripts/AJAX calls to
                # run in the real browser.
                await page.route(
                    normalized_url,
                    lambda route: route.fulfill(
                        status=200,
                        content_type="text/html; charset=utf-8",
                        body=profile_html,
                    ),
                )
                response = await page.goto(normalized_url, wait_until="domcontentloaded", timeout=timeout_ms)
                if response is not None and response.status >= 400:
                    raise WardrobeScrapingError(
                        f"fragrantica wardrobe: profile returned HTTP {response.status}"
                    )

                await page.wait_for_function("typeof window._pd === 'function'", timeout=timeout_ms)
                shelves = await page.evaluate("payload => window._pd(payload)", sealed_shelves)
            finally:
                await browser.close()
    except WardrobeScrapingError:
        raise
    except Exception as exc:
        raise WardrobeScrapingError("fragrantica wardrobe: could not load the public profile") from exc

    urls = parse_owned_shelf_payload(shelves)
    if not urls:
        raise WardrobeScrapingError("fragrantica wardrobe: the 'Perfumes I Have' shelf is empty")
    return urls


async def _fetch_profile_data(url: str) -> tuple[str, object, dict[str, str]]:
    settings = get_settings()
    async with AsyncSession(impersonate="chrome", headers={"User-Agent": settings.USER_AGENT}) as session:
        try:
            profile_response = await session.get(url, timeout=settings.REQUEST_TIMEOUT)
            profile_response.raise_for_status()

            soup = BeautifulSoup(profile_response.text, "lxml")
            component = soup.find("member-shelfs-modern", attrs={"type": "wardrobe"})
            member_id = component.get(":member-id") if isinstance(component, Tag) else None
            if not isinstance(member_id, str) or not member_id.isdigit():
                raise WardrobeScrapingError("fragrantica wardrobe: member id was not found")

            shelves_response = await session.post(
                "https://www.fragrantica.com/ajax.php?user_shelves",
                data={"action": "user_shelves", "user_id": member_id},
                headers={"Referer": url, "content-type": "application/x-www-form-urlencoded"},
                timeout=settings.REQUEST_TIMEOUT,
            )
            shelves_response.raise_for_status()
            sealed_shelves = shelves_response.json()
        except CurlRequestException as exc:
            raise WardrobeScrapingError("fragrantica wardrobe: could not fetch the public profile") from exc
        return profile_response.text, sealed_shelves, session.cookies.get_dict()


async def _launch_browser(playwright):
    errors: list[Exception] = []
    for options in ({"channel": "chrome", "headless": True}, {"headless": True}):
        try:
            return await playwright.chromium.launch(**options)
        except Exception as exc:  # pragma: no cover - environment-dependent fallback
            errors.append(exc)
    raise WardrobeScrapingError(
        "fragrantica wardrobe: Chrome is unavailable; install Chrome or run 'playwright install chromium'"
    ) from errors[-1]
