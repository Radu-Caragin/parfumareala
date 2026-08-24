"""Store scraper modules.

Each store gets its own module here, registering its scraper class via
@register_scraper from app.scrapers.registry. Importing each module here
ensures the decorator runs on startup.
"""

from app.scrapers.stores import esentedelux  # noqa: F401
from app.scrapers.stores import fragranza  # noqa: F401
from app.scrapers.stores import parfimo  # noqa: F401
