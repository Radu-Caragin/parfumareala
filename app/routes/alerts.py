"""Routes for local price alerts - defined per exact perfume variant.

No external notifications; alerts only ever surface inside this app
(instructions.md section 37).
"""

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.database.repositories import alerts as alerts_repo
from app.database.repositories import variants as variants_repo

router = APIRouter()


@router.post("/perfumes/{perfume_id}/variants/{variant_id}/alerts")
async def create_alert_route(
    perfume_id: int, variant_id: int, target_price: str = Form(""), db: Session = Depends(get_db)
):
    variant = variants_repo.get(db, variant_id)
    if variant is None or variant.perfume_id != perfume_id:
        raise HTTPException(status_code=404, detail="Variant not found")

    try:
        price = Decimal(target_price.strip().replace(",", "."))
        if price <= 0:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        # Malformed input from outside the normal <input type="number"> flow
        # - ignored rather than crashing; nothing is created.
        return RedirectResponse(url=f"/perfumes/{perfume_id}", status_code=303)

    alerts_repo.create(db, perfume_variant_id=variant.id, target_price=price, currency="RON")
    return RedirectResponse(url=f"/perfumes/{perfume_id}", status_code=303)


@router.post("/alerts/{alert_id}/delete")
async def delete_alert_route(alert_id: int, db: Session = Depends(get_db)):
    alert = alerts_repo.get(db, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    perfume_id = alert.variant.perfume_id
    alerts_repo.delete(db, alert)
    return RedirectResponse(url=f"/perfumes/{perfume_id}", status_code=303)
