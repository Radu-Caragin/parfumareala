"""Data-access functions for AmbiguousMatch - the "needs review" queue (see
models.py's AmbiguousMatch docstring). Business logic for confirming/
rejecting a match lives in app.services.match_review_service; this module
is data access only.
"""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.database.models import AmbiguousMatch, Availability, MatchReviewStatus
from app.utils.helpers import utcnow


def get(db: Session, match_id: int) -> AmbiguousMatch | None:
    return db.get(AmbiguousMatch, match_id)


def list_pending(db: Session) -> list[AmbiguousMatch]:
    return list(
        db.scalars(
            select(AmbiguousMatch)
            .where(AmbiguousMatch.status == MatchReviewStatus.PENDING)
            .options(joinedload(AmbiguousMatch.perfume), joinedload(AmbiguousMatch.store))
            .order_by(AmbiguousMatch.first_seen_at.desc())
        )
    )


def count_pending(db: Session) -> int:
    """Cheap count, no row/relationship loading - used for the sidebar's
    "Needs review" badge (see app.utils.templates), rendered on every
    page, not the full list_pending() a route handler actually needs."""
    return db.scalar(select(func.count()).select_from(AmbiguousMatch).where(AmbiguousMatch.status == MatchReviewStatus.PENDING)) or 0


def upsert_pending(
    db: Session,
    *,
    perfume_id: int,
    store_id: int,
    raw_title: str,
    candidate_brand: str,
    candidate_name: str,
    concentration: str,
    volume_ml: int,
    tester: bool,
    price: Decimal,
    old_price: Decimal | None,
    currency: str,
    availability: Availability,
    product_url: str,
    store_product_identifier: str | None,
    match_score: int,
) -> AmbiguousMatch | None:
    """Create or refresh a pending review row for this exact (perfume,
    store, product_url). Returns None without writing anything if this
    candidate was already decided (confirmed or rejected) - a past
    decision is never silently overwritten by a later scrape.
    """
    existing = db.scalar(
        select(AmbiguousMatch).where(
            AmbiguousMatch.perfume_id == perfume_id,
            AmbiguousMatch.store_id == store_id,
            AmbiguousMatch.product_url == product_url,
        )
    )

    if existing is not None:
        if existing.status != MatchReviewStatus.PENDING:
            return None
        existing.raw_title = raw_title
        existing.candidate_brand = candidate_brand
        existing.candidate_name = candidate_name
        existing.concentration = concentration
        existing.volume_ml = volume_ml
        existing.tester = tester
        existing.price = price
        existing.old_price = old_price
        existing.currency = currency
        existing.availability = availability
        existing.store_product_identifier = store_product_identifier
        existing.match_score = match_score
        existing.last_seen_at = utcnow()
        db.commit()
        db.refresh(existing)
        return existing

    entry = AmbiguousMatch(
        perfume_id=perfume_id,
        store_id=store_id,
        raw_title=raw_title,
        candidate_brand=candidate_brand,
        candidate_name=candidate_name,
        concentration=concentration,
        volume_ml=volume_ml,
        tester=tester,
        price=price,
        old_price=old_price,
        currency=currency,
        availability=availability,
        product_url=product_url,
        store_product_identifier=store_product_identifier,
        match_score=match_score,
        status=MatchReviewStatus.PENDING,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def mark_confirmed(db: Session, match: AmbiguousMatch) -> None:
    match.status = MatchReviewStatus.CONFIRMED
    match.resolved_at = utcnow()
    db.commit()


def mark_rejected(db: Session, match: AmbiguousMatch) -> None:
    match.status = MatchReviewStatus.REJECTED
    match.resolved_at = utcnow()
    db.commit()
