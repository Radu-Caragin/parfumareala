"""Process-lifetime pool of scraper instances, one per store.

scraping_service uses this instead of creating a fresh scraper (and thus
a fresh HTTP client/session, plus discarding any per-scraper cache like a
brand directory or sitemap) for every single (perfume, store) check. A
pooled instance is created once, on first use, and kept alive - connection
included, and any cache it lazily builds along the way - for as long as
the app process runs, reused across every subsequent check against that
store, not just within one "check all" run. On the next app restart, the
pool is empty again and every scraper starts fresh - see the design
discussion this followed from: a TTL-based cache would only matter for a
long-running always-on server, and this app is restarted by hand (the
.bat launcher) far more often than any store's own brand list changes.

Safe under concurrent access: a store's pooled instance can be reached by
two overlapping check requests (e.g. the user has two browser tabs open)
at once - BaseScraper/CurlCffiScraper.request() guards its rate-limit
bookkeeping and the request itself with a lock precisely so a shared
instance can't have its polite spacing between requests defeated by two
coroutines racing through the same check-then-act step.
"""

import logging

from app.database.models import Store
from app.scrapers.base import BaseScraper
from app.scrapers.registry import get_scraper_class

logger = logging.getLogger(__name__)

_pool: dict[str, BaseScraper] = {}


async def get_scraper(store: Store) -> BaseScraper | None:
    """Returns the pooled scraper instance for this store, creating it on
    first use. Returns None if no scraper is registered for this store's
    scraper_identifier - same "not configured" signal the old
    per-call `get_scraper_class(...) is None` check produced.
    """
    existing = _pool.get(store.scraper_identifier)
    if existing is not None:
        return existing

    scraper_cls = get_scraper_class(store.scraper_identifier)
    if scraper_cls is None:
        return None

    scraper = scraper_cls()
    await scraper.__aenter__()
    _pool[store.scraper_identifier] = scraper
    return scraper


async def close_all() -> None:
    """Closes every pooled scraper. Call once, on app shutdown."""
    for scraper in _pool.values():
        try:
            await scraper.__aexit__(None, None, None)
        except Exception:
            logger.exception("error closing pooled scraper %s", scraper.store_slug)
    _pool.clear()


def reset_pool() -> None:
    """Test-only: drops all pooled instances without closing them.

    Tests register short-lived fake scraper classes under a store_slug
    they reuse across test functions - without this, a pooled instance
    from an earlier test would still be sitting under that slug and get
    handed back instead of a fresh instance of the new test's fake class.
    Skipping a real close() is fine here: test scrapers hold no real
    connections, and the process doesn't rely on this pool for cleanup.
    """
    _pool.clear()
