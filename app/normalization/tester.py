"""Tester detection.

Explicit, word-boundary-safe matching only. A product without an explicit
tester indication is normal (False) - never infer tester status from
unrelated context.

Fragranza.ro (confirmed live) sometimes glues "Tester" directly onto the
preceding word with no space at all in its own raw HTML - not a
BeautifulSoup text-concatenation artifact, the markup itself reads
"Apă de parfumTester EDP". \\btester\\b can't match inside "parfumtester"
(no boundary between two word characters), which silently missed a real
tester and, worse, made it collide with the regular bottle as the exact
same variant (same concentration+volume+tester=False) once persisted -
confirmed live on Xerjoff XJ 1861 Naxos, where this store's two separate
product pages (regular and, per its URL, "fara-ambalaj" - "without
packaging", its own way of describing a tester) upsert into a single
StoreProduct row, one silently overwriting the other. A capital "T"
immediately after a lowercase letter is treated as an implicit boundary
too (a camelCase-style split, the same shape this glued markup has).
"""

import re

from app.normalization.text_utils import strip_diacritics

_TESTER_PATTERN = re.compile(r"\btester\b", re.IGNORECASE)
_GLUED_TESTER_PATTERN = re.compile(r"(?<=[a-z])Tester\b")


def is_tester(text: str) -> bool:
    normalized = strip_diacritics(text)
    return bool(_TESTER_PATTERN.search(normalized)) or bool(_GLUED_TESTER_PATTERN.search(normalized))


def strip_tester_tokens(text: str) -> str:
    """Remove the word "tester" from text - see strip_concentration_tokens.

    Only handles the normal \\btester\\b case, not the glued-word one above -
    its only caller (extract_core_name) always lowercases the text first,
    which destroys the capital "T" that's the sole signal distinguishing a
    genuinely glued "Tester" from an unrelated run of lowercase letters.
    Not a gap in practice: every store scraper builds its offer's
    perfume_name from a store's own clean, separate name field, never from
    the same raw_title/type text is_tester() checks (confirmed for
    Fragranza.ro, whose "parfumTester"-glued field is a `type_text`
    element the perfume_name never touches).
    """
    return _TESTER_PATTERN.sub(" ", text)
