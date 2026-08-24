"""Scraper-specific exceptions.

Each store scraper should raise these instead of letting arbitrary
exceptions propagate, so scraping_service can map failures to a
ScrapeResult status without needing to know about any store's internals
(instructions.md section 44).
"""


class ScraperError(Exception):
    """Base class for all scraper errors."""


class RequestError(ScraperError):
    """The HTTP request itself failed (network, timeout, or a non-2xx
    status that persisted after retries)."""


class ParsingError(ScraperError):
    """The response was received but could not be parsed as expected -
    the site's markup/structure likely changed."""


class ProductNotFound(ScraperError):
    """The store was reachable and searched, but no matching product exists."""


class StoreUnavailable(ScraperError):
    """The store itself appears to be down or is blocking requests entirely
    (e.g. a bot-protection challenge page). Store scrapers raise this
    explicitly when they can detect that condition."""


class UnexpectedResponse(ScraperError):
    """The response was received but its shape/content was not what the
    scraper expected (e.g. missing required structured data)."""
