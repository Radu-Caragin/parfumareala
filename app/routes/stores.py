"""Routes for store management: list stores, enable/disable them, and the
"by store" catalog view.

Disabling a store only flips its `enabled` flag - it never deletes the
store row, its historical prices, or previously discovered products
(instructions.md section 16).
"""

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.database.models import Perfume, StoreProduct
from app.database.repositories import store_products as store_products_repo
from app.database.repositories import stores as stores_repo
from app.utils.templates import templates

router = APIRouter()


@router.get("/stores", response_class=HTMLResponse)
async def list_stores(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    stores = stores_repo.list_all(db)
    return templates.TemplateResponse(request, "stores/list.html", {"stores": stores})


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
