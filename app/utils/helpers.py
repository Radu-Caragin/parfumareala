"""Small shared helper functions used across the application."""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Current UTC time as a naive datetime, matching how SQLite stores timestamps."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
