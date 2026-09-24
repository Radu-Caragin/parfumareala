"""Data-access functions for the user's personal Collection - perfumes
added directly via a Fragrantica URL (see app/scrapers/fragrantica.py),
independent of the store price-tracking Perfume entity."""

from decimal import Decimal

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database.models import (
    CollectionAccord,
    CollectionNote,
    CollectionPerfume,
    CollectionSimilarPerfume,
    NoteTier,
)


def get(db: Session, collection_perfume_id: int) -> CollectionPerfume | None:
    return db.get(CollectionPerfume, collection_perfume_id)


def get_by_url(db: Session, fragrantica_url: str) -> CollectionPerfume | None:
    return db.scalar(select(CollectionPerfume).where(CollectionPerfume.fragrantica_url == fragrantica_url))


def list_all(db: Session, *, sort_by: str = "brand") -> list[CollectionPerfume]:
    """sort_by="brand" (default) orders by brand then name, so perfumes
    from the same brand stay grouped together. sort_by="name" orders by
    the perfume name alone, ignoring brand entirely - e.g. "Erba Gold"
    sorts under E, not under Xerjoff."""
    order = (
        (CollectionPerfume.name,)
        if sort_by == "name"
        else (CollectionPerfume.brand, CollectionPerfume.name)
    )
    return list(
        db.scalars(
            select(CollectionPerfume)
            .options(
                selectinload(CollectionPerfume.accords),
                selectinload(CollectionPerfume.notes),
                selectinload(CollectionPerfume.similar_perfumes),
            )
            .order_by(*order)
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
    similar_perfumes: list[tuple[str, str, str]] | None = None,
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
    perfume.similar_perfumes = [
        CollectionSimilarPerfume(
            brand=similar_brand,
            name=similar_name,
            fragrantica_url=similar_url,
            position=position,
        )
        for position, (similar_brand, similar_name, similar_url) in enumerate(similar_perfumes or [])
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


def replace_similar_perfumes(
    db: Session,
    perfume: CollectionPerfume,
    similar_perfumes: list[tuple[str, str, str]],
) -> CollectionPerfume:
    # A relationship assignment lets SQLAlchemy choose the unit-of-work
    # ordering. With the unique (perfume, URL) constraint it may INSERT the
    # replacement rows before DELETEing the old ones, which makes an
    # unchanged URL fail on refresh. Remove and flush first so the two phases
    # are unambiguous.
    db.execute(
        sa_delete(CollectionSimilarPerfume).where(
            CollectionSimilarPerfume.collection_perfume_id == perfume.id
        )
    )
    db.flush()
    db.add_all([
        CollectionSimilarPerfume(
            collection_perfume_id=perfume.id,
            brand=brand,
            name=name,
            fragrantica_url=url,
            position=position,
        )
        for position, (brand, name, url) in enumerate(similar_perfumes)
    ])
    db.commit()
    db.expire(perfume, ["similar_perfumes"])
    db.refresh(perfume)
    return perfume


def delete(db: Session, perfume: CollectionPerfume) -> None:
    db.delete(perfume)
    db.commit()
