"""Add individual perfumes or a public Fragrantica wardrobe to Collection."""

import asyncio
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.database.models import CollectionPerfume
from app.database.repositories import collection as collection_repo
from app.scrapers import fragrantica
from app.scrapers import fragrantica_wardrobe
from app.scrapers.exceptions import RequestError


class DuplicateCollectionItem(Exception):
    def __init__(self, existing: CollectionPerfume) -> None:
        self.existing = existing
        super().__init__(f"Already in your collection: {existing.brand} {existing.name}")


@dataclass
class CollectionImportResult:
    discovered: int
    added: list[CollectionPerfume] = field(default_factory=list)
    skipped_urls: list[str] = field(default_factory=list)
    failed_urls: list[str] = field(default_factory=list)


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


async def import_from_fragrantica_profile(
    db: Session, profile_url: str, *, delay_seconds: float | None = None
) -> CollectionImportResult:
    """Import every perfume on the public profile's "I Have" shelf.

    Each perfume is committed independently by ``add_from_fragrantica_url``.
    A transient failure therefore does not roll back items already imported.
    """
    urls = await fragrantica_wardrobe.fetch_owned_perfume_urls(profile_url)
    result = CollectionImportResult(discovered=len(urls))
    delay = get_delay_seconds() if delay_seconds is None else max(0.0, delay_seconds)

    for index, url in enumerate(urls):
        try:
            result.added.append(await add_from_fragrantica_url(db, url))
        except DuplicateCollectionItem:
            result.skipped_urls.append(url)
        except (RequestError, fragrantica.InvalidFragranticaUrl):
            result.failed_urls.append(url)

        if delay and index < len(urls) - 1:
            await asyncio.sleep(delay)

    return result


def get_delay_seconds() -> float:
    # Kept behind a tiny function so service tests can avoid sleeping without
    # changing the application's global settings cache.
    from app.config.settings import get_settings

    return max(0.0, get_settings().REQUEST_DELAY)
