"""Shared text-normalization helpers used across the normalization package."""

import re
import unicodedata


def strip_diacritics(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
