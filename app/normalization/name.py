"""Perfume name normalization.

Produces a canonical, comparison-safe form of a perfume name: lowercase,
diacritic-insensitive, whitespace-collapsed. This does not attempt to strip
brand/concentration/volume/tester tokens out of a noisy store title - that
kind of extraction belongs to the matching layer, which combines this
function with the concentration/volume/tester detectors.
"""

import re

from app.normalization.concentration import strip_concentration_tokens
from app.normalization.tester import strip_tester_tokens
from app.normalization.text_utils import collapse_whitespace, strip_diacritics
from app.normalization.volume import strip_volume_tokens

_STRAY_PUNCTUATION_PATTERN = re.compile(r"[\"'‘’“”]|(?<!\S)-(?!\S)")

# Audience/gender wording (e.g. "pentru femei", "unisex") is not part of
# variant identity (instructions.md section 14 - concentration/volume/
# tester only) and is common noise in a title that mixes name+everything
# else together (e.g. "Woman Eau de Parfum pentru femei" -> "Woman").
_GENDER_PATTERN = re.compile(
    r"\bpentru\s+(femei|barbati|copii)\b|\bunisex\b|\bfor\s+(women|men|kids)\b", re.IGNORECASE
)

# A manufacturer "company suffix" word commonly appears directly after the
# brand in a title (e.g. "Zoologist Perfumes Tyrannosaurus Rex" for brand
# "Zoologist") without being part of the brand as the user entered it -
# consumed together with the brand so it doesn't linger as noise.
_BRAND_SUFFIX_WORDS = r"(?:perfumes?|parfums?|fragrances?|cosmetics?)"


def normalize_name(raw_name: str) -> str:
    text = strip_diacritics(raw_name).lower()
    return collapse_whitespace(text)


def extract_core_name(raw_title: str, *, brand: str | None = None) -> str:
    """Best-effort perfume name extraction from a raw title that mixes the
    name together with brand/concentration/volume/tester (used by stores
    that don't expose the name as its own structured field - e.g. Parfimo,
    where "Xerjoff Erba Gold Apa de parfum 50 ml" needs to become
    "erba gold" before fuzzy-matching against a monitored perfume).

    Stores with a clean structured name field (e.g. Fragranza) should use
    it directly instead - this is inherently approximate, since it relies
    on the same keyword lists as concentration/volume/tester detection and
    can leave stray words behind (a store-specific line/edition marker,
    for instance) that those detectors don't recognize. A dangling "-"
    left over from a "Brand - Name" separator (once the brand word itself
    is stripped) is cleaned up the same way as stray quote marks.
    """
    text = strip_diacritics(raw_title).lower()
    if brand:
        brand_normalized = strip_diacritics(brand).lower()
        text = re.sub(
            rf"\b{re.escape(brand_normalized)}\b(\s+{_BRAND_SUFFIX_WORDS}\b)?", " ", text, count=1
        )
    text = strip_concentration_tokens(text)
    text = strip_volume_tokens(text)
    text = strip_tester_tokens(text)
    text = _GENDER_PATTERN.sub(" ", text)
    text = _STRAY_PUNCTUATION_PATTERN.sub(" ", text)
    return collapse_whitespace(text)
