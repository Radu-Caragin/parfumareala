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


templates.env.globals["static_version"] = _static_version
