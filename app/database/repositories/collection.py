"""Data-access functions for the user's personal Collection - perfumes
added directly via a Fragrantica URL (see app/scrapers/fragrantica.py),
independent of the store price-tracking Perfume entity."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database.models import CollectionAccord, CollectionNote, CollectionPerfume, NoteTier


def get(db: Session, collection_perfume_id: int) -> CollectionPerfume | None:
    return db.get(CollectionPerfume, collection_perfume_id)


def get_by_url(db: Session, fragrantica_url: str) -> CollectionPerfume | None:
    return db.scalar(select(CollectionPerfume).where(CollectionPerfume.fragrantica_url == fragrantica_url))


def list_all(db: Session) -> list[CollectionPerfume]:
    return list(
        db.scalars(
            select(CollectionPerfume)
            .options(selectinload(CollectionPerfume.accords), selectinload(CollectionPerfume.notes))
            .order_by(CollectionPerfume.brand, CollectionPerfume.name)
        )
    )


def create(
    db: Session,
    *,
    brand: str,
    name: str,
    fragrantica_url: str,
    accords: list[tuple[str, int]],
    notes: list[tuple[str, str]],
) -> CollectionPerfume:
    perfume = CollectionPerfume(brand=brand, name=name, fragrantica_url=fragrantica_url)
    perfume.accords = [
        CollectionAccord(name=accord_name, strength=strength, position=position)
        for position, (accord_name, strength) in enumerate(accords)
    ]
    perfume.notes = [
        CollectionNote(tier=NoteTier(tier), name=note_name, position=position)
        for position, (tier, note_name) in enumerate(notes)
    ]
    db.add(perfume)
    db.commit()
    db.refresh(perfume)
    return perfume


def update_ownership(
    db: Session,
    perfume: CollectionPerfume,
    *,
    price: Decimal | None,
    currency: str,
    volume_ml: int | None,
) -> CollectionPerfume:
    perfume.price = price
    perfume.currency = currency
    perfume.volume_ml = volume_ml
    db.commit()
    db.refresh(perfume)
    return perfume


def delete(db: Session, perfume: CollectionPerfume) -> None:
    db.delete(perfume)
    db.commit()
