import pytest

from app.normalization.tester import is_tester, strip_tester_tokens


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Tester", True),
        ("TESTER", True),
        ("tester perfume", True),
        ("100 ml tester", True),
        ("Xerjoff Naxos EDP 100 ml Tester", True),
        ("Xerjoff Naxos EDP 100 ml", False),
        ("Testerino Cosmetics", False),
    ],
)
def test_is_tester(raw, expected):
    assert is_tester(raw) == expected


def test_strip_tester_tokens_removes_the_word():
    assert "tester" not in strip_tester_tokens("erba gold tester 100 ml")
