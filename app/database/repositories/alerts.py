"""Data-access functions for PriceAlert.

Alerts belong to an exact PerfumeVariant, not a whole Perfume - see
instructions.md section 38.
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import PriceAlert
from app.utils.helpers import utcnow


def create(db: Session, *, perfume_variant_id: int, target_price: Decimal, currency: str) -> PriceAlert:
    alert = PriceAlert(
        perfume_variant_id=perfume_variant_id,
        target_price=target_price,
        currency=currency,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


def get(db: Session, alert_id: int) -> PriceAlert | None:
    return db.get(PriceAlert, alert_id)


def list_for_variant(db: Session, variant_id: int) -> list[PriceAlert]:
    return list(db.scalars(select(PriceAlert).where(PriceAlert.perfume_variant_id == variant_id)))


def list_enabled(db: Session) -> list[PriceAlert]:
    return list(db.scalars(select(PriceAlert).where(PriceAlert.enabled.is_(True))))


def set_enabled(db: Session, alert: PriceAlert, enabled: bool) -> PriceAlert:
    alert.enabled = enabled
    db.commit()
    db.refresh(alert)
    return alert


def delete(db: Session, alert: PriceAlert) -> None:
    db.delete(alert)
    db.commit()


def mark_triggered(db: Session, alert: PriceAlert, *, price: Decimal) -> None:
    alert.last_triggered_at = utcnow()
    alert.last_triggered_price = price
    db.commit()
