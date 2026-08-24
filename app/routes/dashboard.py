"""Dashboard route - the main page, showing all monitored perfumes."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.database.repositories import perfumes as perfumes_repo
from app.database.repositories import stores as stores_repo
from app.services import scraping_service
from app.utils.templates import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    perfumes = perfumes_repo.list_all(db)
    return templates.TemplateResponse(request, "dashboard.html", {"perfumes": perfumes})


@router.post("/check-all")
async def check_all_route(db: Session = Depends(get_db)):
    perfumes = perfumes_repo.list_all(db)
    enabled_stores = stores_repo.list_enabled(db)
    await scraping_service.check_all_perfumes(db, perfumes, enabled_stores)
    return RedirectResponse(url="/", status_code=303)
