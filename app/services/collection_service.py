"""Adds a perfume to the user's personal Collection from a Fragrantica.com
URL - fetches the page, parses accords/notes, and persists it. Distinct
from the store price-tracking Perfume model: a CollectionPerfume has no
variants/stores, just brand/name/accords/notes and an optional
self-reported price.
"""

from sqlalchemy.orm import Session

from app.database.models import CollectionPerfume
from app.database.repositories import collection as collection_repo
from app.scrapers import fragrantica


class DuplicateCollectionItem(Exception):
    def __init__(self, existing: CollectionPerfume) -> None:
        self.existing = existing
        super().__init__(f"Already in your collection: {existing.brand} {existing.name}")


async def add_from_fragrantica_url(db: Session, url: str) -> CollectionPerfume:
    cleaned_url = url.strip()
    fragrantica.parse_url(cleaned_url)  # raises InvalidFragranticaUrl before any request is made

    existing = collection_repo.get_by_url(db, cleaned_url)
    if existing is not None:
        raise DuplicateCollectionItem(existing)

    html = await fragrantica.fetch_page(cleaned_url)
    parsed = fragrantica.parse_page(cleaned_url, html)

    return collection_repo.create(
        db,
        brand=parsed.brand,
        name=parsed.name,
        fragrantica_url=cleaned_url,
        accords=[(accord.name, accord.strength) for accord in parsed.accords],
        notes=[(note.tier, note.name) for note in parsed.notes],
    )
