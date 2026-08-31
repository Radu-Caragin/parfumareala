"""Shared Jinja2Templates instance, used by every route module."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _static_version(relative_path: str) -> int:
    """Last-modified timestamp of a static file, used as a cache-busting
    query string (see base.html) - browsers treat a URL with a changed
    query string as a new resource, so an edited style.css is always
    fetched fresh instead of silently served from cache under the old URL
    on the next normal reload (no hard-refresh needed)."""
    path = STATIC_DIR / relative_path
    try:
        return int(path.stat().st_mtime)
    except OSError:
        return 0


def _pending_review_count() -> int:
    """Live badge count for the sidebar's "Needs review" link (see
    base.html) - called from every page, so it needs its own session
    rather than a route-injected Depends(get_db) one. Reuses
    get_background_session() (not a bare SessionLocal()) specifically so
    it goes through the SAME indirection the test suite already
    monkeypatches to an isolated test database (see tests/conftest.py's
    `client` fixture) - calling SessionLocal() directly here would hit
    the real data/*.db file even during tests.
    """
    from app.database.database import get_background_session
    from app.database.repositories import match_review as match_review_repo

    db = get_background_session()
    try:
        return match_review_repo.count_pending(db)
    finally:
        db.close()


def _price_changes_count() -> int:
    """Live badge count for the sidebar's "Price changes" link (see
    base.html) - same pattern and same reasoning as _pending_review_count
    above (own session via get_background_session, not a bare
    SessionLocal()). Reuses prices_repo.list_price_changes_for_run - the
    same single source of truth the /price-changes page itself renders
    from - rather than a separate, possibly-diverging count query.
    """
    from app.database.database import get_background_session
    from app.database.repositories import prices as prices_repo
    from app.database.repositories import scrape_runs as scrape_runs_repo

    db = get_background_session()
    try:
        latest_run = scrape_runs_repo.get_latest(db)
        if latest_run is None:
            return 0
        return len(prices_repo.list_price_changes_for_run(db, latest_run.id))
    finally:
        db.close()


templates.env.globals["static_version"] = _static_version
templates.env.globals["pending_review_count"] = _pending_review_count
templates.env.globals["price_changes_count"] = _price_changes_count
