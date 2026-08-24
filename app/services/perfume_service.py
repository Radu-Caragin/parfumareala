"""Domain logic for monitored perfumes.

Bridges the normalization layer with the database repository: every
monitored Perfume must be stored with a normalized_brand/normalized_name
so that later matching against scraped offers is reliable and consistent.
"""

from sqlalchemy.orm import Session

from app.database.models import Perfume
from app.database.repositories import perfumes as perfumes_repo
from app.normalization.brand import normalize_brand
from app.normalization.name import normalize_name


def create_perfume(db: Session, *, brand: str, name: str) -> Perfume:
    return perfumes_repo.create(
        db,
        brand=brand.strip(),
        name=name.strip(),
        normalized_brand=normalize_brand(brand),
        normalized_name=normalize_name(name),
    )


def update_perfume(db: Session, perfume: Perfume, *, brand: str, name: str) -> Perfume:
    return perfumes_repo.update(
        db,
        perfume,
        brand=brand.strip(),
        name=name.strip(),
        normalized_brand=normalize_brand(brand),
        normalized_name=normalize_name(name),
    )
