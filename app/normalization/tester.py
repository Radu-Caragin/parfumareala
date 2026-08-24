"""Tester detection.

Explicit, word-boundary-safe matching only. A product without an explicit
tester indication is normal (False) - never infer tester status from
unrelated context.
"""

import re

_TESTER_PATTERN = re.compile(r"\btester\b", re.IGNORECASE)


def is_tester(text: str) -> bool:
    return bool(_TESTER_PATTERN.search(text))


def strip_tester_tokens(text: str) -> str:
    """Remove the word "tester" from text - see strip_concentration_tokens."""
    return _TESTER_PATTERN.sub(" ", text)
