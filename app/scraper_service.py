import json
import subprocess
import sys
from pathlib import Path

from scrapers.base import ScrapeResult
from scrapers.daniel import DanielScraper
from scrapers.fragranza import FragranzaScraper
from scrapers.notino import NotinoScraper
from scrapers.vivantis import VivantisScraper

SCRAPERS = [
    FragranzaScraper(),
    DanielScraper(),
    VivantisScraper(),
    NotinoScraper(),
]

BASE_DIR = Path(__file__).resolve().parent
SUBPROCESS_RUNNER = BASE_DIR / "run_scraper_subprocess.py"


def _scrape_in_subprocess(url: str, expected_volume_ml: int | None = None) -> ScrapeResult:
    volume_arg = "None" if expected_volume_ml is None else str(expected_volume_ml)

    completed = subprocess.run(
        [sys.executable, str(SUBPROCESS_RUNNER), url, volume_arg],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )

    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()

    if not stdout:
        raise RuntimeError(stderr or "Subprocesul nu a returnat niciun rezultat.")

    payload = json.loads(stdout)

    if completed.returncode != 0 or not payload.get("ok"):
        error_message = payload.get("error") or stderr or "Eroare necunoscută în subproces."
        traceback_text = payload.get("traceback", "")
        if traceback_text:
            raise RuntimeError(f"{error_message}\n\n{traceback_text}")
        raise RuntimeError(error_message)

    data = payload["data"]
    return ScrapeResult(
        shop_name=data["shop_name"],
        url=data["url"],
        title=data["title"],
        price=data["price"],
        currency=data["currency"],
        in_stock=data["in_stock"],
        volume_ml=data["volume_ml"],
        raw_text=data["raw_text"],
    )


def scrape_url(url: str, expected_volume_ml: int | None = None):
    url_lower = url.lower()

    if (
        "notino." in url_lower
        or "parfumuri-timisoara.ro" in url_lower
        or "vivantis.ro" in url_lower
    ):
        return _scrape_in_subprocess(url, expected_volume_ml)

    for scraper in SCRAPERS:
        if scraper.can_handle(url):
            return scraper.scrape(url, expected_volume_ml=expected_volume_ml)

    raise ValueError(f"Nu există încă scraper pentru URL-ul: {url}")