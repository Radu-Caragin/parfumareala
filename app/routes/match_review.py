"""Routes for the "needs review" queue - candidates a scrape found that
plausibly refer to a monitored perfume under a different name, but not
closely enough to trust automatically (see app.database.models.AmbiguousMatch).
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.database.repositories import match_review as match_review_repo
from app.services import match_review_service
from app.utils.templates import templates

router = APIRouter()


@router.get("/match-review", response_class=HTMLResponse)
async def list_pending_matches(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    matches = match_review_repo.list_pending(db)
    return templates.TemplateResponse(request, "match_review/list.html", {"matches": matches})


@router.post("/match-review/{match_id}/confirm")
async def confirm_match_route(match_id: int, db: Session = Depends(get_db)):
    match = match_review_repo.get(db, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found")

    match_review_service.confirm_match(db, match)
    return RedirectResponse(url="/match-review", status_code=303)


@router.post("/match-review/{match_id}/reject")
async def reject_match_route(match_id: int, db: Session = Depends(get_db)):
    match = match_review_repo.get(db, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found")

    match_review_service.reject_match(db, match)
    return RedirectResponse(url="/match-review", status_code=303)
