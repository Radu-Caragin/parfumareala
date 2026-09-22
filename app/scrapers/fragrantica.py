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

Accords and notes are confirmed live (2026-09-22) to be present in the
plain server-rendered HTML - no JS execution needed. The "This perfume
reminds me of" section, by contrast, is a lazy-loaded Vue component with
no data in the static HTML, so it is intentionally NOT scraped here.

Fetched with curl_cffi (Chrome TLS-fingerprint impersonation), not plain
httpx - confirmed live that Fragrantica's Cloudflare bot management
challenges plain httpx with a 403 regardless of the User-Agent header
sent (a Chrome UA over httpx still gets 403), while curl_cffi's Chrome
impersonation gets a normal 200. Same root cause as Vivantis.ro (see
app/scrapers/curl_base.py's module docstring).
"""

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

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
class FragranticaPerfume:
    brand: str
    name: str
    accords: list[FragranticaAccord] = field(default_factory=list)
    notes: list[FragranticaNote] = field(default_factory=list)


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
