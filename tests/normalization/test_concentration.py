import pytest

from app.normalization.concentration import extract_concentration, strip_concentration_tokens


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Eau de Parfum", "EDP"),
        ("EDP", "EDP"),
        ("E.D.P.", "EDP"),
        ("E.d.P.", "EDP"),
        ("Apa de parfum", "EDP"),
        ("Eau de Toilette", "EDT"),
        ("EDT", "EDT"),
        ("E.D.T.", "EDT"),
        ("Apa de toaleta", "EDT"),
        ("Parfum", "Parfum"),
        ("Extrait de Parfum", "Extrait"),
        ("Extrait", "Extrait"),
        ("EDC", "EDC"),
        ("Eau de Cologne", "EDC"),
        ("Cologne", "EDC"),
        ("Xerjoff Erba Gold Eau de Parfum 100 ml", "EDP"),
        ("ERBA GOLD Xerjoff 100 ML Apa de Parfum", "EDP"),
        ("Xerjoff Erba Gold 100 ml Apa de Parfum", "EDP"),
        ("Random Title Without Concentration", None),
    ],
)
def test_extract_concentration(raw, expected):
    assert extract_concentration(raw) == expected


def test_strip_concentration_tokens_removes_matched_phrases():
    assert "parfum" not in strip_concentration_tokens("erba gold apa de parfum 50 ml")
    assert "erba gold" in strip_concentration_tokens("erba gold apa de parfum 50 ml")
