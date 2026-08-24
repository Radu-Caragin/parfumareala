"""Data-access functions for the Perfume entity."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Perfume
from app.utils.helpers import utcnow


def create(db: Session, *, brand: str, name: str, normalized_brand: str, normalized_name: str) -> Perfume:
    perfume = Perfume(
        brand=brand,
        name=name,
        normalized_brand=normalized_brand,
        normalized_name=normalized_name,
    )
    db.add(perfume)
    db.commit()
    db.refresh(perfume)
    return perfume


def get(db: Session, perfume_id: int) -> Perfume | None:
    return db.get(Perfume, perfume_id)


def list_all(db: Session) -> list[Perfume]:
    return list(db.scalars(select(Perfume).order_by(Perfume.brand, Perfume.name)))


def update(
    db: Session, perfume: Perfume, *, brand: str, name: str, normalized_brand: str, normalized_name: str
) -> Perfume:
    perfume.brand = brand
    perfume.name = name
    perfume.normalized_brand = normalized_brand
    perfume.normalized_name = normalized_name
    db.commit()
    db.refresh(perfume)
    return perfume


def delete(db: Session, perfume: Perfume) -> None:
    db.delete(perfume)
    db.commit()


def mark_checked(db: Session, perfume: Perfume) -> None:
    perfume.last_checked_at = utcnow()
    db.commit()
