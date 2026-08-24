"""Scraper registry - avoids if/elif chains when dispatching to a store's
scraper. Each store module registers its scraper class with
@register_scraper; scraping_service looks it up by Store.scraper_identifier
(instructions.md section 41).
"""

from app.scrapers.base import BaseScraper

SCRAPER_REGISTRY: dict[str, type[BaseScraper]] = {}


def register_scraper(cls: type[BaseScraper]) -> type[BaseScraper]:
    SCRAPER_REGISTRY[cls.store_slug] = cls
    return cls


def get_scraper_class(store_slug: str) -> type[BaseScraper] | None:
    return SCRAPER_REGISTRY.get(store_slug)
