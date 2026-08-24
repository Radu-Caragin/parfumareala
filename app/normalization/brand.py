"""Brand normalization.

Produces a canonical, comparison-safe form of a brand name: lowercase,
diacritic-insensitive, whitespace-collapsed. Used both for the monitored
Perfume.normalized_brand and, later, for validating scraped candidates
against it in the matching layer.
"""

from app.normalization.text_utils import collapse_whitespace, strip_diacritics


def normalize_brand(raw_brand: str) -> str:
    text = strip_diacritics(raw_brand).lower()
    return collapse_whitespace(text)
