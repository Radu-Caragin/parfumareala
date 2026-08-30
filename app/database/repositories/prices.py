"""Data-access functions for PriceHistory.

A new row is only inserted when the price or availability actually changed
since the last recorded entry for that StoreProduct. This is a deliberate
choice for this personal, manually-triggered app: repeated identical
observations add no useful information and would bloat the history table
without benefit. StoreProduct.last_checked_at (updated separately) still
always reflects the most recent check, changed or not.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.database.models import Availability, PerfumeVariant, PriceHistory, StoreProduct


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


@dataclass(frozen=True)
class PriceChange:
    store_product: StoreProduct
    price: Decimal
    previous_price: Decimal
    delta: Decimal
    currency: str
    availability: Availability


def list_price_changes_for_run(db: Session, scrape_run_id: int) -> list[PriceChange]:
    """Every store_product whose PRICE (not just availability) actually
    changed during this scrape run, compared to whatever price was
    recorded for it right before. A store_product's very first-ever
    price_history row is never included - there's nothing to compare it
    against yet, so it's a new listing, not a "change"."""
    entries = list(
        db.scalars(
            select(PriceHistory)
            .where(PriceHistory.scrape_run_id == scrape_run_id)
            .options(
                joinedload(PriceHistory.store_product).joinedload(StoreProduct.store),
                joinedload(PriceHistory.store_product)
                .joinedload(StoreProduct.variant)
                .joinedload(PerfumeVariant.perfume),
            )
            .order_by(PriceHistory.id)
        )
    )

    changes: list[PriceChange] = []
    for entry in entries:
        previous = db.scalar(
            select(PriceHistory)
            .where(PriceHistory.store_product_id == entry.store_product_id, PriceHistory.id < entry.id)
            .order_by(PriceHistory.id.desc())
            .limit(1)
        )
        if previous is None or previous.price == entry.price:
            continue

        changes.append(
            PriceChange(
                store_product=entry.store_product,
                price=entry.price,
                previous_price=previous.price,
                delta=entry.price - previous.price,
                currency=entry.currency,
                availability=entry.availability,
            )
        )

    return changes
