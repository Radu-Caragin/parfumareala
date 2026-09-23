"""Routes for the personal Collection tab - perfumes added by hand via a
Fragrantica.com URL, independent of the store price-tracking Perfume
model (see app/services/collection_service.py)."""

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.database.models import CollectionPerfume
from app.database.repositories import collection as collection_repo
from app.scrapers.exceptions import RequestError
from app.scrapers.fragrantica import InvalidFragranticaUrl
from app.scrapers.fragrantica_wardrobe import InvalidFragranticaProfileUrl, WardrobeScrapingError
from app.services import collection_family_service, collection_service
from app.utils.templates import templates

router = APIRouter()

_SORT_OPTIONS = {"brand", "name"}


def _get_item_or_404(db: Session, item_id: int) -> CollectionPerfume:
    item = collection_repo.get(db, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Collection item not found")
    return item


def _clean_sort(sort_by: str) -> str:
    return sort_by if sort_by in _SORT_OPTIONS else "brand"


@router.get("/collection", response_class=HTMLResponse)
async def list_collection(request: Request, sort: str = "brand", db: Session = Depends(get_db)) -> HTMLResponse:
    sort = _clean_sort(sort)
    items = collection_repo.list_all(db, sort_by=sort)
    return templates.TemplateResponse(
        request,
        "collection/list.html",
        {
            "items": items,
            "error": None,
            "url": "",
            "profile_url": "",
            "import_result": None,
            "sort": sort,
        },
    )


@router.get("/collection/insights", response_class=HTMLResponse)
async def collection_insights(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    items = collection_repo.list_all(db)
    families = collection_family_service.build_family_breakdown(items)
    return templates.TemplateResponse(request, "collection/insights.html", {"families": families})


@router.post("/collection")
async def add_collection_item_route(
    request: Request, url: str = Form(""), sort: str = Form("brand"), db: Session = Depends(get_db)
):
    sort = _clean_sort(sort)
    error = None
    try:
        await collection_service.add_from_fragrantica_url(db, url)
    except InvalidFragranticaUrl:
        error = "That doesn't look like a Fragrantica perfume page URL (expected something like https://www.fragrantica.com/perfume/Brand/Name-12345.html)."
    except collection_service.DuplicateCollectionItem as exc:
        error = f"Already in your collection: {exc.existing.brand} {exc.existing.name}."
    except RequestError:
        error = "Couldn't fetch that page from Fragrantica - try again in a moment."

    if error:
        items = collection_repo.list_all(db, sort_by=sort)
        return templates.TemplateResponse(
            request,
            "collection/list.html",
            {
                "items": items,
                "error": error,
                "url": url,
                "profile_url": "",
                "import_result": None,
                "sort": sort,
            },
            status_code=400,
        )
    return RedirectResponse(url=f"/collection?sort={sort}", status_code=303)


@router.post("/collection/import-fragrantica", response_class=HTMLResponse)
async def import_fragrantica_wardrobe_route(
    request: Request, profile_url: str = Form(""), sort: str = Form("brand"), db: Session = Depends(get_db)
) -> HTMLResponse:
    sort = _clean_sort(sort)
    error = None
    result = None
    try:
        result = await collection_service.import_from_fragrantica_profile(db, profile_url)
    except InvalidFragranticaProfileUrl:
        error = "Enter a Fragrantica profile URL like https://www.fragrantica.com/@username."
    except WardrobeScrapingError:
        error = "Couldn't read the public 'Perfumes I Have' shelf from that Fragrantica profile."

    items = collection_repo.list_all(db, sort_by=sort)
    return templates.TemplateResponse(
        request,
        "collection/list.html",
        {
            "items": items,
            "error": error,
            "url": "",
            "profile_url": profile_url,
            "import_result": result,
            "sort": sort,
        },
        status_code=400 if error else 200,
    )


@router.post("/collection/{item_id}/ownership")
async def update_collection_ownership_route(
    item_id: int,
    price: str = Form(""),
    volume_ml: str = Form(""),
    sort: str = Form("brand"),
    db: Session = Depends(get_db),
):
    sort = _clean_sort(sort)
    item = _get_item_or_404(db, item_id)

    price_value = price.strip()
    parsed_price: Decimal | None = None
    if price_value:
        try:
            parsed_price = Decimal(price_value.replace(",", "."))
            if parsed_price <= 0:
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            # Malformed input from outside the normal <input> flow -
            # ignored rather than crashing; this field is left blank.
            parsed_price = None

    volume_value = volume_ml.strip()
    parsed_volume: int | None = None
    if volume_value:
        try:
            parsed_volume = int(volume_value)
            if parsed_volume <= 0:
                parsed_volume = None
        except ValueError:
            parsed_volume = None

    collection_repo.update_ownership(db, item, price=parsed_price, currency=item.currency, volume_ml=parsed_volume)
    return RedirectResponse(url=f"/collection?sort={sort}", status_code=303)


@router.post("/collection/{item_id}/delete")
async def delete_collection_item_route(item_id: int, sort: str = Form("brand"), db: Session = Depends(get_db)):
    sort = _clean_sort(sort)
    item = _get_item_or_404(db, item_id)
    collection_repo.delete(db, item)
    return RedirectResponse(url=f"/collection?sort={sort}", status_code=303)
