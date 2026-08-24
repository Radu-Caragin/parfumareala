"""Product exclusion filtering - centralized so no store scraper needs to
duplicate this logic (see instructions.md section 3 and 25).

Rejects: refill-as-product, gift sets, discovery sets, samples, decants,
miniatures, bundles. Deliberately conservative: only specific, unambiguous
phrases are used (never a bare "set", which would false-positive on
legitimate product names). "refillable" must never be excluded - a normal
refillable bottle is still a legitimate product; only an item sold as the
refill itself is excluded. This works for free because \\brefill\\b does
not match inside the single word "refillable" (no word boundary between
"refill" and "able").

"decant" (found investigating Parfimo.ro) is a third party reselling a
small amount of a bottle they already own, rebottled into a vial/atomizer -
not an authentic retail unit from the brand, so it's excluded the same way
as a sample.

"esantion"/"mostra" (found investigating EsenteDeLux.ro) are Romanian for
"sample" - added defensively in case a product title ever spells it out,
even though the store's own "Esantion (Mostra)" category turned out to
contain normal full-size products when checked, so it is NOT used as a
category-based exclusion (would risk excluding legitimate bottles).
"""

import re

from app.normalization.text_utils import strip_diacritics

_EXCLUSION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\brefill\b", re.IGNORECASE), "refill"),
    (re.compile(r"\bgift\s+set\b", re.IGNORECASE), "gift_set"),
    (re.compile(r"\bset\s+cadou\b", re.IGNORECASE), "gift_set"),
    (re.compile(r"\bcoffret\b", re.IGNORECASE), "gift_set"),
    (re.compile(r"\bdiscovery\s+set\b", re.IGNORECASE), "discovery_set"),
    (re.compile(r"\bsample\s+set\b", re.IGNORECASE), "sample"),
    (re.compile(r"\bsamples?\b", re.IGNORECASE), "sample"),
    (re.compile(r"\besantion\w*\b", re.IGNORECASE), "sample"),
    (re.compile(r"\bmostr[ae]\w*\b", re.IGNORECASE), "sample"),
    (re.compile(r"\bdecant\w*\b", re.IGNORECASE), "decant"),
    (re.compile(r"\bminiatur\w*\b", re.IGNORECASE), "miniature"),
    (re.compile(r"\bbundle\b", re.IGNORECASE), "bundle"),
]


def check_exclusion(text: str) -> str | None:
    """Return the exclusion reason if the product should be rejected, else None."""
    normalized = strip_diacritics(text).lower()
    for pattern, reason in _EXCLUSION_PATTERNS:
        if pattern.search(normalized):
            return reason
    return None


def is_excluded(text: str) -> bool:
    return check_exclusion(text) is not None
