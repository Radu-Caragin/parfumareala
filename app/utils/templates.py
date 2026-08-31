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


templates.env.globals["static_version"] = _static_version
templates.env.globals["pending_review_count"] = _pending_review_count
