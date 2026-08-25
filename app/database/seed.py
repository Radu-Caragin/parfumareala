"""Seed data inserted on first startup.

Only stores that have actually been requested and implemented are listed
here. Do not add placeholder entries for stores that don't have a scraper
yet - see instructions.md section 4.
"""

import logging

from sqlalchemy.orm import Session

from app.database.models import Store

logger = logging.getLogger(__name__)

_INITIAL_STORES = [
    {
        "name": "Fragranza.ro",
        "slug": "fragranza",
        "base_url": "https://fragranza.ro/",
        "scraper_identifier": "fragranza",
    },
    {
        "name": "Parfimo.ro",
        "slug": "parfimo",
        "base_url": "https://www.parfimo.ro/",
        "scraper_identifier": "parfimo",
    },
    {
        "name": "EsenteDeLux.ro",
        "slug": "esentedelux",
        "base_url": "https://esentedelux.ro/",
        "scraper_identifier": "esentedelux",
    },
    {
        "name": "Vivantis.ro",
        "slug": "vivantis",
        "base_url": "https://www.vivantis.ro/",
        "scraper_identifier": "vivantis",
    },
    {
        "name": "Notino.ro",
        "slug": "notino",
        "base_url": "https://www.notino.ro/",
        "scraper_identifier": "notino",
    },
]


def seed_initial_stores(session: Session) -> None:
    for store_data in _INITIAL_STORES:
        exists = session.query(Store).filter_by(slug=store_data["slug"]).first()
        if exists:
            continue
        session.add(Store(enabled=True, **store_data))
        logger.info("Seeded store: %s", store_data["name"])
    session.commit()
