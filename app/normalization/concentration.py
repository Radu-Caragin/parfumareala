"""Concentration normalization.

Maps the many ways a concentration can be written to a small set of
canonical values: EDP, EDT, EDC, Parfum, Extrait. Not every perfume has an
EDP/EDT designation - some are simply "Parfum" or "Extrait" - so those are
supported as first-class values, not treated as fallbacks or defaults.

Pattern order matters: multi-word phrases that contain "parfum" or
"cologne" (e.g. "eau de parfum", "extrait de parfum") must be checked
before the bare "parfum"/"cologne" fallback patterns, otherwise the bare
pattern would match first and misclassify them.

Romanian retailers write this concentration as "Extract de Parfum", not
just the French "Extrait de Parfum" - both are matched to "Extrait".
Found via a real cross-store mismatch: EsenteDeLux and Parfimo both use
"extract" natively (confirmed live - EsenteDeLux's own "Tip produs"
dropdown option is literally "extract de parfum"), while Fragranza uses
"extrait". Missing the Romanian spelling didn't just misclassify it as
"Parfum" (falling through to the bare fallback) - it also broke candidate
discovery entirely: strip_concentration_tokens only stripped the bare
"parfum" word, leaving "extract de" behind as noise that dragged a
correct candidate's fuzzy-match score for a short perfume name (e.g.
"Ani") from ~100 down to ~35, well under the ambiguous threshold, so the
real product got silently dropped before ever being fetched.

"parfum" also needs to tolerate one specific real-world typo: EsenteDeLux
misspells it "parfume" (trailing e) on at least one live product title
("Nishane - Hacivat extrait de parfume unisex" - confirmed live, and the
same typo is baked into that product's own URL slug, so it isn't a
one-off rendering glitch). `\bparfum\b` doesn't match inside "parfume" -
there's no word boundary between the "m" and the "e", both word
characters - so every "parfum"-ending pattern left "parfume" completely
unstripped, which broke candidate discovery the exact same way the
Romanian-spelling gap above did (leftover "de parfume" noise tanking the
fuzzy-match score for "Hacivat" well under the ambiguous threshold).
`parfume?` (matched below by making the "e" optional right before the
original `\b`) absorbs the typo without weakening the boundary check for
the correctly-spelled word.

Vivantis (Czech-founded - see its module docstring) also uses the plain
Czech/Slovak word "parfém" as a bare concentration marker on at least one
live, in-stock product ("MYSLF L`Absolu - parfém" - confirmed live).
strip_diacritics() turns that into "parfem", which is not just an accent
difference from "parfum" - the vowel itself differs (parf-E-m vs
parf-U-m) - so `\bparfume?\b` never matched it and this fell through to
None entirely, same silent-drop failure mode as the other gaps above.
"""

import re

from app.normalization.text_utils import strip_diacritics

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\beau\s+de\s+parfume?\b", re.IGNORECASE), "EDP"),
    (re.compile(r"\bapa\s+de\s+parfume?\b", re.IGNORECASE), "EDP"),
    (re.compile(r"\be\.?\s?d\.?\s?p\.?\b", re.IGNORECASE), "EDP"),
    (re.compile(r"\beau\s+de\s+toilette\b", re.IGNORECASE), "EDT"),
    (re.compile(r"\bapa\s+de\s+toaleta\b", re.IGNORECASE), "EDT"),
    (re.compile(r"\be\.?\s?d\.?\s?t\.?\b", re.IGNORECASE), "EDT"),
    (re.compile(r"\beau\s+de\s+cologne\b", re.IGNORECASE), "EDC"),
    (re.compile(r"\bedc\b", re.IGNORECASE), "EDC"),
    (re.compile(r"\bextrait\s+de\s+parfume?\b", re.IGNORECASE), "Extrait"),
    (re.compile(r"\bextract\s+de\s+parfume?\b", re.IGNORECASE), "Extrait"),
    (re.compile(r"\bextrait\b", re.IGNORECASE), "Extrait"),
    (re.compile(r"\bextract\b", re.IGNORECASE), "Extrait"),
    (re.compile(r"\bcologne\b", re.IGNORECASE), "EDC"),
    (re.compile(r"\bparfume?\b", re.IGNORECASE), "Parfum"),
    (re.compile(r"\bparfem\b", re.IGNORECASE), "Parfum"),
]


def extract_concentration(text: str) -> str | None:
    normalized = strip_diacritics(text).lower()
    for pattern, canonical in _PATTERNS:
        if pattern.search(normalized):
            return canonical
    return None


def strip_concentration_tokens(text: str) -> str:
    """Remove concentration wording from text, e.g. to isolate a perfume
    name from a store's title that mixes name + concentration together
    (used by stores without a separate structured name field)."""
    result = text
    for pattern, _ in _PATTERNS:
        result = pattern.sub(" ", result)
    return result
