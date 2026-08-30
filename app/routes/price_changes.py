"""Route for the 'what changed at the last check' overview - every store
offer whose price moved during the most recent scrape run, compared to
whatever price was recorded for it right before, across any perfume, any
volume, any concentration (instructions.md doesn't cover this - added on
user request, not spec-driven)."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.database.repositories import prices as prices_repo
from app.database.repositories import scrape_runs as scrape_runs_repo
from app.utils.templates import templates

router = APIRouter()


@router.get("/price-changes", response_class=HTMLResponse)
async def list_price_changes(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    latest_run = scrape_runs_repo.get_latest(db)
    changes = prices_repo.list_price_changes_for_run(db, latest_run.id) if latest_run is not None else []
    changes.sort(key=lambda c: abs(c.delta), reverse=True)

    return templates.TemplateResponse(
        request, "price_changes/list.html", {"changes": changes, "latest_run": latest_run}
    )
