"""Data-access functions for the Store entity."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Store
from app.utils.helpers import utcnow


def get(db: Session, store_id: int) -> Store | None:
    return db.get(Store, store_id)


def get_by_slug(db: Session, slug: str) -> Store | None:
    return db.scalar(select(Store).where(Store.slug == slug))


def list_all(db: Session) -> list[Store]:
    return list(db.scalars(select(Store).order_by(Store.name)))


def list_enabled(db: Session) -> list[Store]:
    return list(db.scalars(select(Store).where(Store.enabled.is_(True)).order_by(Store.name)))


def set_enabled(db: Session, store: Store, enabled: bool) -> Store:
    store.enabled = enabled
    db.commit()
    db.refresh(store)
    return store


def record_success(db: Session, store: Store) -> None:
    store.last_successful_check = utcnow()
    store.last_error = None
    db.commit()


def record_error(db: Session, store: Store, *, error_message: str) -> None:
    store.last_error = error_message
    db.commit()
