import pytest

from app.normalization.volume import extract_volume_ml, strip_volume_tokens


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("100ml", 100),
        ("100 ml", 100),
        ("100 ML", 100),
        ("Xerjoff Erba Gold EDP 100ml", 100),
        ("Dior Sauvage EDT 50 ml Tester", 50),
        ("No volume mentioned here", None),
        ("Product code SKU12345", None),
    ],
)
def test_extract_volume_ml_from_title(raw, expected):
    assert extract_volume_ml(raw) == expected


def test_extract_volume_ml_prefers_structured_value():
    assert extract_volume_ml("irrelevant text", structured_volume_ml=75) == 75


def test_extract_volume_ml_rejects_implausible_structured_value():
    assert extract_volume_ml("irrelevant text", structured_volume_ml=5000) is None


def test_strip_volume_tokens_removes_ml_amount():
    assert strip_volume_tokens("erba gold 50 ml") == "erba gold  "
