"""Data-access functions for PerfumeNameAlias - confirmed alternate names
for a monitored perfume (see models.py's PerfumeNameAlias docstring)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import PerfumeNameAlias
from app.normalization.name import normalize_name


def list_for_perfume(db: Session, perfume_id: int) -> list[PerfumeNameAlias]:
    return list(
        db.scalars(select(PerfumeNameAlias).where(PerfumeNameAlias.perfume_id == perfume_id))
    )


def get_or_create(db: Session, *, perfume_id: int, alias: str) -> PerfumeNameAlias:
    normalized_alias = normalize_name(alias)
    existing = db.scalar(
        select(PerfumeNameAlias).where(
            PerfumeNameAlias.perfume_id == perfume_id,
            PerfumeNameAlias.normalized_alias == normalized_alias,
        )
    )
    if existing is not None:
        return existing

    entry = PerfumeNameAlias(perfume_id=perfume_id, alias=alias, normalized_alias=normalized_alias)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
