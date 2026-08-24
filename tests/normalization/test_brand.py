from app.normalization.brand import normalize_brand


def test_normalize_brand_lowercases_and_trims():
    assert normalize_brand("  Xerjoff  ") == "xerjoff"


def test_normalize_brand_strips_diacritics():
    assert normalize_brand("Guerlain") == "guerlain"


def test_normalize_brand_collapses_whitespace():
    assert normalize_brand("Yves   Saint  Laurent") == "yves saint laurent"
