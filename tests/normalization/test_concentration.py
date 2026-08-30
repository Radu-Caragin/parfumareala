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
        ("Extract de Parfum", "Extrait"),
        ("extract de parfum", "Extrait"),
        ("Extract", "Extrait"),
        ("Nishane Ani Extract de parfum 50 ml", "Extrait"),
        ("EDC", "EDC"),
        ("Eau de Cologne", "EDC"),
        ("Cologne", "EDC"),
        ("Xerjoff Erba Gold Eau de Parfum 100 ml", "EDP"),
        ("ERBA GOLD Xerjoff 100 ML Apa de Parfum", "EDP"),
        ("Xerjoff Erba Gold 100 ml Apa de Parfum", "EDP"),
        ("MYSLF L`Absolu - parfém", "Parfum"),
        ("Random Title Without Concentration", None),
    ],
)
def test_extract_concentration(raw, expected):
    assert extract_concentration(raw) == expected


def test_strip_concentration_tokens_removes_matched_phrases():
    assert "parfum" not in strip_concentration_tokens("erba gold apa de parfum 50 ml")
    assert "erba gold" in strip_concentration_tokens("erba gold apa de parfum 50 ml")


def test_strip_concentration_tokens_removes_romanian_extract_spelling():
    # Regression: "extract de parfum" (Romanian) only had its "parfum"
    # word stripped by the bare fallback, leaving "extract de" behind as
    # noise - which was enough to drag a short perfume name's fuzzy-match
    # score during candidate discovery below the usable threshold.
    stripped = strip_concentration_tokens("ani extract de parfum 50 ml")
    assert "extract" not in stripped
    assert "parfum" not in stripped
    assert "ani" in stripped


def test_strip_concentration_tokens_tolerates_esentedelux_parfume_typo():
    # Regression: EsenteDeLux misspells "parfum" as "parfume" (trailing e)
    # on at least one live product title ("Nishane - Hacivat extrait de
    # parfume unisex") - \bparfum\b doesn't match inside "parfume" (no
    # word boundary between "m" and "e"), so every "parfum"-ending pattern
    # left it completely unstripped, leaving "de parfume" as noise that
    # tanked "hacivat"'s fuzzy-match score below the usable threshold.
    stripped = strip_concentration_tokens("hacivat extrait de parfume unisex")
    assert "parfume" not in stripped
    assert "hacivat" in stripped

    # The correctly-spelled word must still be matched exactly (the fix
    # only makes the trailing "e" optional, not the boundary check itself).
    assert extract_concentration("hacivat extrait de parfum unisex") == "Extrait"
