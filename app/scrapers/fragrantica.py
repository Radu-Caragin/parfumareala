"""Fetches and parses a single Fragrantica.com perfume page, given its
exact URL (added by the user via the Collection tab - not a scraper in
the store-comparison sense, so it doesn't implement BaseScraper's
search/discover contract; it's a one-shot fetch-and-parse for a URL the
user already picked out themselves).

Brand and name are read from the URL path itself
(/perfume/<Brand-Slug>/<Name-Slug>-<id>.html), not from the page's <h1> -
the heading concatenates brand + name + gender with no reliable separator
("Narcotic Delight Initio Parfums Prives for women and men"), while the
URL slug cleanly separates them and matches the page's own displayed
brand text exactly (confirmed live: the brand link next to the "main
accords" section shows "Initio Parfums Prives", identical to the slug).

Accords and notes are present in the plain server-rendered HTML. The
"This perfume reminds me of" cards are rendered by Vue from a sealed JSON
value named ``similar_perfumes``.  That value is decoded with Fragrantica's
own ``window._pd`` function in a real browser; scraping the nearby "People
who like this also like" links would return a different recommendation list.

Fetched with curl_cffi (Chrome TLS-fingerprint impersonation), not plain
httpx - confirmed live that Fragrantica's Cloudflare bot management
challenges plain httpx with a 403 regardless of the User-Agent header
sent (a Chrome UA over httpx still gets 403), while curl_cffi's Chrome
impersonation gets a normal 200. Same root cause as Vivantis.ro (see
app/scrapers/curl_base.py's module docstring).
"""

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import RequestException as CurlRequestException

from app.config.settings import get_settings
from app.scrapers.exceptions import RequestError

_PATH_PATTERN = re.compile(r"^/perfume/(?P<brand>[^/]+)/(?P<name>[^/]+)-\d+\.html$", re.IGNORECASE)
_ALLOWED_HOSTS = {"fragrantica.com", "www.fragrantica.com"}


class InvalidFragranticaUrl(ValueError):
    pass


@dataclass
class FragranticaAccord:
    name: str
    strength: int


@dataclass
class FragranticaNote:
    tier: str  # "top" | "middle" | "base"
    name: str


@dataclass
class FragranticaSimilarPerfume:
    brand: str
    name: str
    url: str


@dataclass
class FragranticaPerfume:
    brand: str
    name: str
    accords: list[FragranticaAccord] = field(default_factory=list)
    notes: list[FragranticaNote] = field(default_factory=list)
    similar_perfumes: list[FragranticaSimilarPerfume] = field(default_factory=list)


def parse_url(url: str) -> tuple[str, str]:
    """Extracts (brand, name) from a Fragrantica product URL. Raises
    InvalidFragranticaUrl if the URL isn't a recognizable Fragrantica
    perfume page - this both rejects garbage input early and, by
    checking the hostname against a fixed allowlist, rules out fetching
    an arbitrary attacker-supplied host before any request is made."""
    parsed = urlparse(url.strip())
    if parsed.hostname is None or parsed.hostname.lower() not in _ALLOWED_HOSTS:
        raise InvalidFragranticaUrl(f"Not a Fragrantica URL: {url!r}")

    match = _PATH_PATTERN.match(parsed.path)
    if not match:
        raise InvalidFragranticaUrl(f"Not a Fragrantica perfume page URL: {url!r}")

    brand = match.group("brand").replace("-", " ").strip()
    name = match.group("name").replace("-", " ").strip()
    return brand, name


async def fetch_page(url: str) -> str:
    settings = get_settings()
    async with AsyncSession(impersonate="chrome", headers={"User-Agent": settings.USER_AGENT}) as session:
        try:
            response = await session.get(url, timeout=settings.REQUEST_TIMEOUT)
            response.raise_for_status()
        except CurlRequestException as exc:
            raise RequestError(f"fragrantica: request to {url} failed") from exc
    return response.text


def parse_page(url: str, html: str) -> FragranticaPerfume:
    brand, name = parse_url(url)
    soup = BeautifulSoup(html, "lxml")
    return FragranticaPerfume(
        brand=brand,
        name=name,
        accords=_parse_accords(soup),
        notes=_parse_notes(soup),
    )


def extract_sealed_similar_payload(html: str) -> object | None:
    """Return the sealed ``similar_perfumes`` value embedded in a page.

    The assignment is deliberately parsed as JSON instead of executing an
    arbitrary inline script.  Fragrantica currently emits the object on one
    line, but the whitespace-tolerant expression also handles pretty-printed
    markup.
    """
    match = re.search(r"\blet\s+similar_perfumes\s*=\s*(\{.*?\})\s*;", html, re.DOTALL)
    if match is None:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def parse_similar_payload(payload: object) -> list[FragranticaSimilarPerfume]:
    """Normalize the decoded payload while preserving Fragrantica's order."""
    if not isinstance(payload, dict) or not isinstance(payload.get("similar_perfumes"), list):
        return []

    perfumes: list[FragranticaSimilarPerfume] = []
    seen: set[str] = set()
    for relation in payload["similar_perfumes"]:
        perfume = relation.get("perfume") if isinstance(relation, dict) else None
        if not isinstance(perfume, dict):
            continue
        brand = perfume.get("dizajner")
        name = perfume.get("naslov")
        raw_url = perfume.get("perfume_url")
        if not all(isinstance(value, str) and value.strip() for value in (brand, name, raw_url)):
            continue

        parsed = urlparse(urljoin("https://www.fragrantica.com", raw_url))
        if parsed.hostname is None or parsed.hostname.lower() not in _ALLOWED_HOSTS:
            continue
        url = urlunparse(("https", "www.fragrantica.com", parsed.path, "", "", ""))
        try:
            parse_url(url)
        except InvalidFragranticaUrl:
            continue
        if url in seen:
            continue
        seen.add(url)
        perfumes.append(
            FragranticaSimilarPerfume(brand=brand.strip(), name=name.strip(), url=url)
        )
    return perfumes


async def decode_similar_perfumes(url: str, html: str) -> list[FragranticaSimilarPerfume]:
    """Decode the page's sealed similarity data with Fragrantica's JS opener."""
    sealed_payload = extract_sealed_similar_payload(html)
    if sealed_payload is None:
        return []

    settings = get_settings()
    timeout_ms = max(15_000, round(settings.REQUEST_TIMEOUT * 1_000))
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover - depends on local installation
        raise RequestError("fragrantica: Playwright is required to decode similar perfumes") from exc

    try:
        async with async_playwright() as playwright:
            browser = await _launch_browser(playwright)
            try:
                page = await browser.new_page()
                await page.route(
                    url,
                    lambda route: route.fulfill(
                        status=200,
                        content_type="text/html; charset=utf-8",
                        body=html,
                    ),
                )
                response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                if response is not None and response.status >= 400:
                    raise RequestError(f"fragrantica: perfume page returned HTTP {response.status}")
                await page.wait_for_function("typeof window._pd === 'function'", timeout=timeout_ms)
                decoded = await page.evaluate("payload => window._pd(payload)", sealed_payload)
            finally:
                await browser.close()
    except RequestError:
        raise
    except Exception as exc:
        raise RequestError("fragrantica: could not decode similar perfumes") from exc
    return parse_similar_payload(decoded)


async def _launch_browser(playwright):
    errors: list[Exception] = []
    for options in ({"channel": "chrome", "headless": True}, {"headless": True}):
        try:
            return await playwright.chromium.launch(**options)
        except Exception as exc:  # pragma: no cover - environment-dependent fallback
            errors.append(exc)
    raise RequestError(
        "fragrantica: Chrome is unavailable; install Chrome or run 'playwright install chromium'"
    ) from errors[-1]


def _parse_accords(soup: BeautifulSoup) -> list[FragranticaAccord]:
    heading = soup.find(["h6", "h5", "h4"], string=re.compile(r"main accords", re.IGNORECASE))
    if heading is None:
        return []
    container = heading.find_next_sibling("div")
    if container is None:
        return []

    accords = []
    for bar in container.select("div[style*=width]"):
        name = bar.get_text(strip=True)
        style = bar.get("style") or ""
        width_match = re.search(r"width:\s*([\d.]+)%", style)
        if not name or width_match is None:
            continue
        accords.append(FragranticaAccord(name=name, strength=round(float(width_match.group(1)))))
    return accords


def _parse_notes(soup: BeautifulSoup) -> list[FragranticaNote]:
    notes = []
    for level in soup.find_all("pyramid-level-new"):
        tier = level.get("notes")
        if tier not in ("top", "middle", "base"):
            continue
        for link in level.select("a.pyramid-note-link"):
            label = link.select_one(".pyramid-note-label")
            note_name = label.get_text(strip=True) if label else link.get_text(strip=True)
            if note_name:
                notes.append(FragranticaNote(tier=tier, name=note_name))
    return notes
