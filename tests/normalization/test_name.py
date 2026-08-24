import pytest

from app.normalization.name import extract_core_name, normalize_name


def test_normalize_name_lowercases_and_trims():
    assert normalize_name("  Erba Gold  ") == "erba gold"


def test_normalize_name_collapses_whitespace():
    assert normalize_name("Erba   Gold") == "erba gold"


def test_normalize_name_strips_diacritics():
    assert normalize_name("Naive Rose") == "naive rose"
    assert normalize_name("Naïve Rosé") == "naive rose"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Erba Gold Apă de parfum 50 ml", "erba gold"),
        ("Erba Gold Apă de parfum 100 ml", "erba gold"),
        ("Casamorati 1888 Apă de parfum 100 ml tester", "casamorati 1888"),
        ("Alexandria II Parfum 100 ml tester", "alexandria ii"),
    ],
)
def test_extract_core_name_strips_concentration_volume_tester(raw, expected):
    assert extract_core_name(raw) == expected


def test_extract_core_name_strips_stray_quote_marks():
    # Parfimo prefixes some lines with a `" V "` marker in the raw title.
    core = extract_core_name('" V " Erba Gold Apă de parfum decant 1 ml')
    assert '"' not in core
    assert "erba gold" in core


def test_extract_core_name_strips_leading_brand_when_given():
    # Parfimo's tracking JSON "name" field always includes the brand
    # prefixed (e.g. "Xerjoff Erba Gold Apa de parfum 50 ml") - without
    # stripping it too, fuzzy-matching against a brand-less monitored
    # perfume name scores far too low (was a real bug: ~47 instead of 100).
    assert extract_core_name("Xerjoff Erba Gold Apă de parfum 50 ml", brand="Xerjoff") == "erba gold"


def test_extract_core_name_without_brand_arg_leaves_brand_in_place():
    assert extract_core_name("Xerjoff Erba Gold Apă de parfum 50 ml") == "xerjoff erba gold"


def test_extract_core_name_strips_manufacturer_suffix_word_after_brand():
    # A title like "Zoologist Perfumes Tyrannosaurus Rex" for brand
    # "Zoologist" - without consuming "Perfumes" too, it lingers as noise
    # and drags the fuzzy-match score below the usable threshold (was a
    # real bug: 79 instead of 100).
    assert extract_core_name("Zoologist Perfumes Tyrannosaurus Rex", brand="Zoologist") == "tyrannosaurus rex"
