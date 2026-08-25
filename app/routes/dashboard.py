"""Dashboard route - the main page, showing all monitored perfumes."""

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import database as database_module
from app.database.database import get_db
from app.database.repositories import perfumes as perfumes_repo
from app.database.repositories import stores as stores_repo
from app.services import comparison_service, scraping_service
from app.services import progress as progress_service
from app.utils.templates import templates

router = APIRouter()

_ALL_CHECK_PROGRESS_KEY = "all"
_SORT_KEYS = {"name", "last_checked", "best_price"}
_MIN_DATETIME = datetime.min


async def _run_check_all(progress_key: str) -> None:
    """Runs in the background, after the triggering request has already
    redirected the browser away - see check_all_route. Uses its own DB
    session: the request-scoped one from Depends(get_db) is closed by the
    time this runs.
    """
    db = database_module.get_background_session()
    try:
        perfumes = perfumes_repo.list_all(db)
        enabled_stores = stores_repo.list_enabled(db)
        await scraping_service.check_all_perfumes(db, perfumes, enabled_stores, progress_key=progress_key)
    finally:
        db.close()


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    sort: str = "name",
    order: str = "asc",
    availability: str = "all",
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if sort not in _SORT_KEYS:
        sort = "name"
    reverse = order == "desc"

    perfumes = perfumes_repo.list_all(db)
    rows = [
        {"perfume": p, "best_price": comparison_service.cheapest_price_for_perfume(p)} for p in perfumes
    ]

    if availability == "in_stock":
        rows = [r for r in rows if r["best_price"] is not None]
    elif availability == "not_found":
        rows = [r for r in rows if r["best_price"] is None]

    if sort == "best_price":
        # Perfumes with no current in-stock offer always sort last,
        # regardless of direction - flipping to "descending" shouldn't
        # jump unavailable perfumes to the top just because there's
        # nothing to compare them by.
        priced = sorted(
            (r for r in rows if r["best_price"] is not None), key=lambda r: r["best_price"], reverse=reverse
        )
        unpriced = [r for r in rows if r["best_price"] is None]
        rows = priced + unpriced
    elif sort == "last_checked":
        rows.sort(key=lambda r: r["perfume"].last_checked_at or _MIN_DATETIME, reverse=reverse)
    else:
        rows.sort(key=lambda r: (r["perfume"].brand.lower(), r["perfume"].name.lower()), reverse=reverse)

    check_progress = progress_service.get(_ALL_CHECK_PROGRESS_KEY)
    if check_progress is not None and check_progress.done:
        check_progress = None

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "rows": rows,
            "has_any_perfumes": bool(perfumes),
            "sort": sort,
            "order": order,
            "availability": availability,
            "check_progress": check_progress,
            "check_status_url": "/check-all-status",
        },
    )


@router.post("/check-all")
async def check_all_route(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    perfumes = perfumes_repo.list_all(db)
    if perfumes:
        background_tasks.add_task(_run_check_all, _ALL_CHECK_PROGRESS_KEY)
    return RedirectResponse(url="/", status_code=303)


@router.get("/check-all-status", response_class=HTMLResponse)
async def check_all_status(request: Request) -> HTMLResponse:
    run_progress = progress_service.get(_ALL_CHECK_PROGRESS_KEY)
    if run_progress is None or run_progress.done:
        progress_service.clear(_ALL_CHECK_PROGRESS_KEY)
        return HTMLResponse(content="", headers={"HX-Refresh": "true"})

    return templates.TemplateResponse(
        request,
        "partials/check_progress.html",
        {"check_progress": run_progress, "check_status_url": "/check-all-status"},
    )
