"""Routes for store management: list stores, enable/disable them, and the
"by store" catalog view.

Disabling a store only flips its `enabled` flag - it never deletes the
store row, its historical prices, or previously discovered products
(instructions.md section 16).
"""

from collections import defaultdict
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.database.models import Perfume, ScrapeResultStatus, StoreProduct
from app.database.repositories import scrape_runs as scrape_runs_repo
from app.database.repositories import store_products as store_products_repo
from app.database.repositories import stores as stores_repo
from app.utils.templates import templates

router = APIRouter()

# A store actually responding - whether or not it happened to have the
# product (IN_STOCK/OUT_OF_STOCK/NOT_FOUND are all a real answer) - is
# healthy. Only these two mean the scraper itself couldn't get a real
# answer at all (README's own distinction: "these are deliberately kept
# distinct so you know whether the store was actually checked").
_UNHEALTHY_STATUSES = {ScrapeResultStatus.SCRAPING_ERROR, ScrapeResultStatus.STORE_UNAVAILABLE}


@dataclass(frozen=True)
class _StoreHealth:
    recent_statuses: list[ScrapeResultStatus]
    total: int
    healthy_count: int
    consecutive_failures: int


def _compute_health(statuses: list[ScrapeResultStatus]) -> _StoreHealth:
    healthy_count = sum(1 for s in statuses if s not in _UNHEALTHY_STATUSES)
    consecutive_failures = 0
    for s in statuses:
        if s not in _UNHEALTHY_STATUSES:
            break
        consecutive_failures += 1
    return _StoreHealth(
        recent_statuses=statuses,
        total=len(statuses),
        healthy_count=healthy_count,
        consecutive_failures=consecutive_failures,
    )


@router.get("/stores", response_class=HTMLResponse)
async def list_stores(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    stores = stores_repo.list_all(db)
    health_by_store = {
        store.id: _compute_health(scrape_runs_repo.list_recent_statuses_for_store(db, store.id))
        for store in stores
    }
    return templates.TemplateResponse(
        request, "stores/list.html", {"stores": stores, "health_by_store": health_by_store}
    )


@router.get("/stores/catalog", response_class=HTMLResponse)
async def store_catalog(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    """For each store, every perfume it currently has in stock (from the
    latest price check), grouped by perfume so a variant with several
    sizes/testers shows as one entry rather than repeating the perfume."""
    stores = stores_repo.list_all(db)
    offers = store_products_repo.list_in_stock(db)

    offers_by_store: dict[int, list[StoreProduct]] = defaultdict(list)
    for offer in offers:
        offers_by_store[offer.store_id].append(offer)

    sections = [
        {"store": store, "perfumes": _group_by_perfume(offers_by_store.get(store.id, []))}
        for store in stores
    ]

    return templates.TemplateResponse(request, "stores/catalog.html", {"sections": sections})


def _group_by_perfume(offers: list[StoreProduct]) -> list[dict]:
    offers_by_perfume: dict[int, list[StoreProduct]] = defaultdict(list)
    perfumes: dict[int, Perfume] = {}
    for offer in offers:
        perfume = offer.variant.perfume
        perfumes[perfume.id] = perfume
        offers_by_perfume[perfume.id].append(offer)

    grouped = [
        {
            "perfume": perfumes[perfume_id],
            "offers": sorted(perfume_offers, key=lambda o: (o.current_price is None, o.current_price)),
        }
        for perfume_id, perfume_offers in offers_by_perfume.items()
    ]
    grouped.sort(key=lambda g: (g["perfume"].brand.lower(), g["perfume"].name.lower()))
    return grouped


@router.post("/stores/{store_id}/toggle")
async def toggle_store(store_id: int, db: Session = Depends(get_db)):
    store = stores_repo.get(db, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found")

    stores_repo.set_enabled(db, store, not store.enabled)
    return RedirectResponse(url="/stores", status_code=303)
