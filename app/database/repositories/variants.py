"""Data-access functions for PerfumeVariant.

get_or_create is the main entry point used during price checking: matching
never creates duplicate variants for the same (perfume, concentration,
volume_ml, tester) combination - see uq_variant_identity in models.py.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import PerfumeVariant


def get_or_create(
    db: Session, *, perfume_id: int, concentration: str, volume_ml: int, tester: bool
) -> PerfumeVariant:
    existing = db.scalar(
        select(PerfumeVariant).where(
            PerfumeVariant.perfume_id == perfume_id,
            PerfumeVariant.concentration == concentration,
            PerfumeVariant.volume_ml == volume_ml,
            PerfumeVariant.tester == tester,
        )
    )
    if existing is not None:
        return existing

    variant = PerfumeVariant(
        perfume_id=perfume_id,
        concentration=concentration,
        volume_ml=volume_ml,
        tester=tester,
    )
    db.add(variant)
    db.commit()
    db.refresh(variant)
    return variant


def get(db: Session, variant_id: int) -> PerfumeVariant | None:
    return db.get(PerfumeVariant, variant_id)


def list_for_perfume(db: Session, perfume_id: int) -> list[PerfumeVariant]:
    # Largest bottle first, regardless of concentration (EDT/EDP/... never
    # splits the list into separate size-ordered groups) - concentration
    # and tester are only tie-breakers for two variants of the same size.
    return list(
        db.scalars(
            select(PerfumeVariant)
            .where(PerfumeVariant.perfume_id == perfume_id)
            .order_by(PerfumeVariant.volume_ml.desc(), PerfumeVariant.concentration, PerfumeVariant.tester)
        )
    )
