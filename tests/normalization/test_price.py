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
        ("no price here", None),
        ("", None),
    ],
)
def test_parse_price(raw, expected):
    assert parse_price(raw) == expected
