"""Bottle volume extraction.

Prefers a structured volume value from the store's page data when the
caller has one - title parsing is only a fallback. Both paths are bounded
to a plausible perfume-bottle range, to avoid an unrelated number (a
product code, a review count, ...) being mistaken for the volume.
"""

import re

_VOLUME_PATTERN = re.compile(r"\b(\d{1,4})\s*ml\b", re.IGNORECASE)
_MIN_VOLUME_ML = 1
_MAX_VOLUME_ML = 1000


def extract_volume_ml(text: str, *, structured_volume_ml: int | None = None) -> int | None:
    if structured_volume_ml is not None:
        return structured_volume_ml if _MIN_VOLUME_ML <= structured_volume_ml <= _MAX_VOLUME_ML else None

    match = _VOLUME_PATTERN.search(text)
    if not match:
        return None

    volume = int(match.group(1))
    return volume if _MIN_VOLUME_ML <= volume <= _MAX_VOLUME_ML else None


def strip_volume_tokens(text: str) -> str:
    """Remove "<number> ml" wording from text - see strip_concentration_tokens."""
    return _VOLUME_PATTERN.sub(" ", text)
