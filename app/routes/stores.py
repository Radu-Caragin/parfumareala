"""Routes for store management: list stores, enable/disable them.

Disabling a store only flips its `enabled` flag - it never deletes the
store row, its historical prices, or previously discovered products
(instructions.md section 16).
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.database.repositories import stores as stores_repo
from app.utils.templates import templates

router = APIRouter()


@router.get("/stores", response_class=HTMLResponse)
async def list_stores(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    stores = stores_repo.list_all(db)
    return templates.TemplateResponse(request, "stores/list.html", {"stores": stores})


@router.post("/stores/{store_id}/toggle")
async def toggle_store(store_id: int, db: Session = Depends(get_db)):
    store = stores_repo.get(db, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found")

    stores_repo.set_enabled(db, store, not store.enabled)
    return RedirectResponse(url="/stores", status_code=303)
