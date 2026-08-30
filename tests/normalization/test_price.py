from decimal import Decimal

import pytest

from app.normalization.price import parse_price


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("625,99 lei", Decimal("625.99")),
        ("625,99\xa0lei", Decimal("625.99")),
        ("860,99 lei", Decimal("860.99")),
        ("RRP: 929,99 lei", Decimal("929.99")),
        ("1.234,56 lei", Decimal("1234.56")),
        # Regression: Koku.ro writes 4+ digit prices with no thousands
        # separator at all (e.g. "1301,00 lei", confirmed live on Nishane
        # Shem) - the old pattern capped the integer part at 3 digits
        # unless a separator was present, so it silently matched "301,00"
        # instead and dropped the leading "1".
        ("1301,00 lei", Decimal("1301.00")),
        ("12345,00 lei", Decimal("12345.00")),
        ("no price here", None),
        ("", None),
    ],
)
def test_parse_price(raw, expected):
    assert parse_price(raw) == expected
