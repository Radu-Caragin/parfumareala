"""Price parsing: converts a store's raw price text into a Decimal.

Fragranza.ro (and similar Romanian stores) format prices like "625,99 lei"
- comma as the decimal separator, dot/space as an optional thousands
separator, "lei" as the currency word, sometimes with a non-breaking
space (already matched by \\s in the pattern below). Prefer Decimal over
float for money (instructions.md section 19).
"""

import re
from decimal import Decimal, InvalidOperation

_PRICE_PATTERN = re.compile(r"(\d+(?:[.\s]\d{3})*),(\d{2})")


def parse_price(text: str) -> Decimal | None:
    if not text:
        return None

    match = _PRICE_PATTERN.search(text)
    if not match:
        return None

    integer_part = re.sub(r"[.\s]", "", match.group(1))
    decimal_part = match.group(2)

    try:
        return Decimal(f"{integer_part}.{decimal_part}")
    except InvalidOperation:
        return None


def compute_discount_percentage(price: Decimal, old_price: Decimal | None) -> int | None:
    """Shared by scraping_service (persisting a fresh offer) and
    match_review_service (persisting a confirmed AmbiguousMatch) - both
    need the exact same rule for deriving a discount percentage from a
    price/old_price pair."""
    if old_price is None or old_price <= 0 or price >= old_price:
        return None
    return int(round((old_price - price) / old_price * 100))
