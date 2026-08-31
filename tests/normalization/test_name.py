import pytest

from app.normalization.name import (
    extract_core_name,
    names_plausibly_match,
    normalize_name,
    word_sets_overlap_fully,
)


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


def test_extract_core_name_strips_stray_commas():
    # Regression: Parfumat.ro titles some products as a comma-separated
    # list ("Paris Corner, Mawj Moscow Mule, Unisex, 100 ml") instead of
    # plain words - once brand/volume/gender are stripped, the leftover
    # commas ("- , mawj moscow mule, ,") made the name compare unequal to
    # a clean "mawj moscow mule", falling back to a weaker fuzzy score for
    # no real reason.
    core = extract_core_name("Paris Corner, Mawj Moscow Mule, Unisex, 100 ml", brand="Paris Corner")
    assert "," not in core
    assert core == "mawj moscow mule"


def test_extract_core_name_strips_bare_gender_word_without_pentru_prefix():
    # Regression: Brasty.ro drops "pentru" and just appends the bare
    # gender word instead ("Eau de Toilette bărbați", confirmed live) -
    # the old pattern only matched "pentru bărbați"/"pentru femei"/
    # "pentru copii", so "bărbați" was left dangling in the extracted
    # name ("pour lui barbati" instead of "pour lui"), dragging its
    # fuzzy-match score against the monitored perfume's clean name below
    # the usable threshold.
    core = extract_core_name(
        "Oscar de la Renta Pour Lui Eau de Toilette bărbați 90 ml", brand="Oscar de la Renta"
    )
    assert "barbati" not in core
    assert core == "pour lui"

    # The "pentru "-prefixed phrase must still be fully consumed too, not
    # left with a dangling "pentru" once the bare word is also matched.
    assert "pentru" not in extract_core_name("Woman Eau de Parfum pentru femei", brand="")


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


def test_extract_core_name_strips_collection_noir_prefix():
    # Regression: Notino.ro titles every one of Serge Lutens' former
    # Palais-Royal-exclusive fragrances "Collection Noir(e) <name>", not
    # the bare name alone (confirmed live) - unstripped, that prefix
    # dragged a short target name's fuzzy score well under the ambiguous
    # threshold (e.g. "Collection Noir Chergui" vs "Chergui" scored ~47),
    # silently dropping a real, in-stock match.
    assert extract_core_name("Collection Noir Chergui Eau de Parfum") == "chergui"
    assert extract_core_name("Collection Noire Santal Majuscule Eau de Parfum") == "santal majuscule"


def test_extract_core_name_strips_aromatix_sub_line_prefix():
    # Regression: French Avenue's "Sun Kissed" is retailed as "Aromatix
    # Sun Kissed" - confirmed live on two independent stores (Parfumat.ro,
    # Notino.ro) using the identical wording. Unstripped, "Aromatix"
    # dragged the fuzzy score to ~69 on both, just under the ambiguous
    # threshold, silently dropping a real, in-stock match.
    assert extract_core_name("French Avenue Aromatix Sun Kissed Extract de Parfum", brand="French Avenue") == "sun kissed"


def test_word_sets_overlap_fully_catches_target_wrapped_in_decoration():
    # The confirmed-live motivating case: Xerjoff's "Naxos" is officially
    # "XJ 1861 Naxos" on some stores.
    assert word_sets_overlap_fully("xj 1861 naxos", "naxos") is True


def test_word_sets_overlap_fully_rejects_reverse_direction():
    # A candidate whose name is a strict PREFIX of the target's must not
    # match - that's usually a different, simpler flanker product, not
    # the same perfume with decoration added (confirmed live: Dior's
    # plain "Sauvage" is a different fragrance from "Sauvage Elixir").
    assert word_sets_overlap_fully("sauvage", "sauvage elixir") is False


def test_word_sets_overlap_fully_rejects_partial_overlap():
    # Sharing one word is not containment - neither name's word set is
    # fully present in the other's.
    assert word_sets_overlap_fully("erba pura", "erba gold") is False


def test_names_plausibly_match_true_for_exact_and_fuzzy_and_containment():
    assert names_plausibly_match("erba gold", "erba gold", ambiguous_threshold=70) is True
    assert names_plausibly_match("erbagold", "erba gold", ambiguous_threshold=70) is True  # fuzzy
    assert names_plausibly_match("xj 1861 naxos", "naxos", ambiguous_threshold=70) is True  # containment


def test_names_plausibly_match_false_for_unrelated_names():
    assert names_plausibly_match("erba pura", "erba gold", ambiguous_threshold=70) is False
