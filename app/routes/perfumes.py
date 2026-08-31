"""Routes for managing monitored perfumes: add, edit, delete, detail page."""

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import database as database_module
from app.database.database import get_db
from app.database.models import Perfume, StoreProduct
from app.database.repositories import perfumes as perfumes_repo
from app.database.repositories import prices as prices_repo
from app.database.repositories import scrape_runs as scrape_runs_repo
from app.database.repositories import store_products as store_products_repo
from app.database.repositories import stores as stores_repo
from app.database.repositories import variants as variants_repo
from app.services import alert_service, price_chart_service, scraping_service
from app.services import progress as progress_service
from app.services.comparison_service import compare_perfume
from app.services.perfume_service import create_perfume, update_perfume
from app.utils.templates import templates

router = APIRouter()


_check_progress_key = progress_service.perfume_check_key


async def _run_check_perfume(perfume_id: int, progress_key: str) -> None:
    """Runs in the background, after the triggering request has already
    redirected the browser away - see check_perfume_route. Uses its own
    DB session: the request-scoped one from Depends(get_db) is closed by
    the time this runs. Always releases the exclusivity claim
    check_perfume_route took before scheduling this - success or failure
    - or a crashed run would block every future check of this perfume
    forever.
    """
    db = database_module.get_background_session()
    try:
        perfume = perfumes_repo.get(db, perfume_id)
        if perfume is None:
            return
        enabled_stores = stores_repo.list_enabled(db)
        await scraping_service.check_perfume(db, perfume, enabled_stores, progress_key=progress_key)
    finally:
        db.close()
        progress_service.release_check_perfume(perfume_id)


def _get_perfume_or_404(db: Session, perfume_id: int) -> Perfume:
    perfume = perfumes_repo.get(db, perfume_id)
    if perfume is None:
        raise HTTPException(status_code=404, detail="Perfume not found")
    return perfume


def _get_store_product_or_404(db: Session, perfume_id: int, store_product_id: int) -> StoreProduct:
    store_product = store_products_repo.get(db, store_product_id)
    if store_product is None or store_product.variant.perfume_id != perfume_id:
        raise HTTPException(status_code=404, detail="Store product not found")
    return store_product


@router.get("/perfumes/new", response_class=HTMLResponse)
async def new_perfume_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "perfumes/form.html",
        {
            "heading": "Add perfume",
            "action_url": "/perfumes",
            "submit_label": "Add perfume",
            "cancel_url": "/",
            "brand": "",
            "name": "",
            "error": None,
        },
    )


@router.post("/perfumes")
async def create_perfume_route(
    request: Request,
    brand: str = Form(""),
    name: str = Form(""),
    db: Session = Depends(get_db),
):
    if not brand.strip() or not name.strip():
        return templates.TemplateResponse(
            request,
            "perfumes/form.html",
            {
                "heading": "Add perfume",
                "action_url": "/perfumes",
                "submit_label": "Add perfume",
                "cancel_url": "/",
                "brand": brand,
                "name": name,
                "error": "Both brand and perfume name are required.",
            },
            status_code=400,
        )

    perfume = create_perfume(db, brand=brand, name=name)
    return RedirectResponse(url=f"/perfumes/{perfume.id}", status_code=303)


@router.get("/perfumes/{perfume_id}", response_class=HTMLResponse)
async def perfume_detail(request: Request, perfume_id: int, db: Session = Depends(get_db)) -> HTMLResponse:
    perfume = _get_perfume_or_404(db, perfume_id)
    variants = variants_repo.list_for_perfume(db, perfume.id)
    comparisons = compare_perfume(variants)
    store_results = scrape_runs_repo.get_latest_results_for_perfume(db, perfume.id)

    triggered_alerts = []
    for variant in variants:
        triggered_alerts.extend(alert_service.current_alert_status(variant))

    # One chart per store (not one combined chart per variant) - each
    # store's own price history is shown in its own dropdown, never
    # mixed with another store's line.
    charts_by_store_product = {
        sp.id: price_chart_service.build_variant_price_chart([sp])
        for comparison in comparisons
        for sp in comparison.store_products
    }
    price_drops_by_store_product = {
        sp.id: price_chart_service.real_price_drop(sp)
        for comparison in comparisons
        for sp in comparison.store_products
    }

    check_progress = progress_service.get(_check_progress_key(perfume_id))
    if check_progress is not None and check_progress.done:
        check_progress = None

    return templates.TemplateResponse(
        request,
        "perfumes/detail.html",
        {
            "perfume": perfume,
            "comparisons": comparisons,
            "store_results": store_results,
            "triggered_alerts": triggered_alerts,
            "charts_by_store_product": charts_by_store_product,
            "price_drops_by_store_product": price_drops_by_store_product,
            "check_progress": check_progress,
            "check_status_url": f"/perfumes/{perfume_id}/check-status",
        },
    )


@router.post("/perfumes/{perfume_id}/check")
async def check_perfume_route(perfume_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    perfume = _get_perfume_or_404(db, perfume_id)
    # claim_check_perfume() is refused while this perfume already has an
    # active check, or a check-all is running (which already covers it);
    # the redirect happens either way, so a refused claim just lands back
    # on a page that's already rendering the in-progress run's own status
    # instead of starting a second, overlapping one.
    if progress_service.claim_check_perfume(perfume_id):
        background_tasks.add_task(_run_check_perfume, perfume_id, _check_progress_key(perfume_id))
    return RedirectResponse(url=f"/perfumes/{perfume.id}", status_code=303)


@router.get("/perfumes/{perfume_id}/check-status", response_class=HTMLResponse)
async def check_perfume_status(request: Request, perfume_id: int) -> HTMLResponse:
    key = _check_progress_key(perfume_id)
    run_progress = progress_service.get(key)
    if run_progress is None or run_progress.done:
        progress_service.clear(key)
        return HTMLResponse(content="", headers={"HX-Refresh": "true"})

    return templates.TemplateResponse(
        request,
        "partials/check_progress.html",
        {"check_progress": run_progress, "check_status_url": f"/perfumes/{perfume_id}/check-status"},
    )


@router.get("/perfumes/{perfume_id}/history/{store_product_id}", response_class=HTMLResponse)
async def price_history(
    request: Request, perfume_id: int, store_product_id: int, db: Session = Depends(get_db)
) -> HTMLResponse:
    perfume = _get_perfume_or_404(db, perfume_id)
    store_product = _get_store_product_or_404(db, perfume_id, store_product_id)
    history = list(reversed(prices_repo.list_for_store_product(db, store_product_id)))
    return templates.TemplateResponse(
        request,
        "perfumes/history.html",
        {"perfume": perfume, "store_product": store_product, "history": history},
    )


@router.get("/perfumes/{perfume_id}/edit", response_class=HTMLResponse)
async def edit_perfume_form(request: Request, perfume_id: int, db: Session = Depends(get_db)) -> HTMLResponse:
    perfume = _get_perfume_or_404(db, perfume_id)
    return templates.TemplateResponse(
        request,
        "perfumes/form.html",
        {
            "heading": "Edit perfume",
            "action_url": f"/perfumes/{perfume.id}/edit",
            "submit_label": "Save changes",
            "cancel_url": f"/perfumes/{perfume.id}",
            "brand": perfume.brand,
            "name": perfume.name,
            "error": None,
        },
    )


@router.post("/perfumes/{perfume_id}/edit")
async def update_perfume_route(
    request: Request,
    perfume_id: int,
    brand: str = Form(""),
    name: str = Form(""),
    db: Session = Depends(get_db),
):
    perfume = _get_perfume_or_404(db, perfume_id)

    if not brand.strip() or not name.strip():
        return templates.TemplateResponse(
            request,
            "perfumes/form.html",
            {
                "heading": "Edit perfume",
                "action_url": f"/perfumes/{perfume.id}/edit",
                "submit_label": "Save changes",
                "cancel_url": f"/perfumes/{perfume.id}",
                "brand": brand,
                "name": name,
                "error": "Both brand and perfume name are required.",
            },
            status_code=400,
        )

    update_perfume(db, perfume, brand=brand, name=name)
    return RedirectResponse(url=f"/perfumes/{perfume.id}", status_code=303)


@router.post("/perfumes/{perfume_id}/delete")
async def delete_perfume_route(perfume_id: int, db: Session = Depends(get_db)):
    perfume = _get_perfume_or_404(db, perfume_id)
    perfumes_repo.delete(db, perfume)
    return RedirectResponse(url="/", status_code=303)
