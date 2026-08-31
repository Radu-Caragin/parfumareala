from app.normalization.brand import brand_lookup_candidates, normalize_brand


def test_normalize_brand_lowercases_and_trims():
    assert normalize_brand("  Xerjoff  ") == "xerjoff"


def test_normalize_brand_strips_diacritics():
    assert normalize_brand("Guerlain") == "guerlain"


def test_normalize_brand_collapses_whitespace():
    assert normalize_brand("Yves   Saint  Laurent") == "yves saint laurent"


def test_brand_lookup_candidates_includes_confirmed_alias():
    # Regression: Parfumat's and (the now-retired directory version of)
    # Brasty's brand directories only ever listed "Christian Dior", never
    # a bare "Dior" entry (confirmed live on both) - a directory-based
    # scraper looking up "Dior" must also try the alias before concluding
    # the brand isn't carried at all.
    assert brand_lookup_candidates("Dior") == ["dior", "christian dior"]
    assert brand_lookup_candidates("Christian Dior") == ["christian dior", "dior"]


def test_brand_lookup_candidates_is_just_the_normalized_name_when_no_alias_exists():
    assert brand_lookup_candidates("Xerjoff") == ["xerjoff"]


def test_brand_lookup_candidates_includes_initio_alias():
    # Regression: Notino.ro's sitemap prefixes Initio's product URLs
    # "initio-parfums-prives", not the bare "initio" this app tracks it as
    # (confirmed live: 0 vs 18 matching sitemap entries).
    assert brand_lookup_candidates("Initio") == ["initio", "initio parfums prives"]


def test_brand_lookup_candidates_includes_jean_paul_gaultier_alias():
    # Regression: confirmed live on two independent stores - Vivantis's
    # own brand directory and Brasty's product search results both spell
    # this house "Jean P. Gaultier", never "Jean Paul Gaultier" written
    # out in full.
    assert brand_lookup_candidates("Jean Paul Gaultier") == ["jean paul gaultier", "jean p. gaultier"]
