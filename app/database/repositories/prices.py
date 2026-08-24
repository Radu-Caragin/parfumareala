"""Data-access functions for PriceHistory.

A new row is only inserted when the price or availability actually changed
since the last recorded entry for that StoreProduct. This is a deliberate
choice for this personal, manually-triggered app: repeated identical
observations add no useful information and would bloat the history table
without benefit. StoreProduct.last_checked_at (updated separately) still
always reflects the most recent check, changed or not.
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Availability, PriceHistory


def get_latest(db: Session, store_product_id: int) -> PriceHistory | None:
    # SQLite's CURRENT_TIMESTAMP has only second-level precision, so rapid
    # successive inserts can tie on recorded_at - id (insertion order) is
    # used as the tiebreaker to keep ordering deterministic.
    return db.scalar(
        select(PriceHistory)
        .where(PriceHistory.store_product_id == store_product_id)
        .order_by(PriceHistory.recorded_at.desc(), PriceHistory.id.desc())
        .limit(1)
    )


def record_if_changed(
    db: Session,
    *,
    store_product_id: int,
    scrape_run_id: int | None,
    price: Decimal,
    old_price: Decimal | None,
    currency: str,
    discount_percentage: int | None,
    availability: Availability,
) -> PriceHistory | None:
    latest = get_latest(db, store_product_id)

    if latest is not None and latest.price == price and latest.availability == availability:
        return None

    entry = PriceHistory(
        store_product_id=store_product_id,
        scrape_run_id=scrape_run_id,
        price=price,
        old_price=old_price,
        currency=currency,
        discount_percentage=discount_percentage,
        availability=availability,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def list_for_store_product(db: Session, store_product_id: int) -> list[PriceHistory]:
    return list(
        db.scalars(
            select(PriceHistory)
            .where(PriceHistory.store_product_id == store_product_id)
            .order_by(PriceHistory.recorded_at.desc(), PriceHistory.id.desc())
        )
    )
