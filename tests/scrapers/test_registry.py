from app.scrapers.base import BaseScraper
from app.scrapers.registry import SCRAPER_REGISTRY, get_scraper_class, register_scraper


def test_register_scraper_adds_to_registry():
    SCRAPER_REGISTRY.pop("test-store", None)

    @register_scraper
    class _TestScraper(BaseScraper):
        store_name = "Test Store"
        store_slug = "test-store"
        base_url = "https://example.test"

        async def search_perfume(self, brand, perfume_name):
            return []

        async def fetch_product(self, candidate):
            return None

        async def parse_product(self, raw_product):
            return []

    try:
        assert get_scraper_class("test-store") is _TestScraper
        assert get_scraper_class("does-not-exist") is None
    finally:
        SCRAPER_REGISTRY.pop("test-store", None)
