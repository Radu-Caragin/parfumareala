from app.database.repositories import perfumes as perfumes_repo
from app.services.matching_service import MatchCandidate, MatchConfidence, resolve_variant, validate_candidate


def _dior_perfume(db_session):
    return perfumes_repo.create(
        db_session, brand="Dior", name="Sauvage", normalized_brand="dior", normalized_name="sauvage"
    )


def _perfume(db_session):
    return perfumes_repo.create(
        db_session, brand="Xerjoff", name="Erba Gold", normalized_brand="xerjoff", normalized_name="erba gold"
    )


def _candidate(**overrides):
    defaults = dict(
        raw_title="Xerjoff Erba Gold Eau de Parfum 100 ml",
        brand="Xerjoff",
        name="Erba Gold",
        concentration="EDP",
        volume_ml=100,
        tester=False,
    )
    defaults.update(overrides)
    return MatchCandidate(**defaults)


def test_exact_match(db_session):
    perfume = _perfume(db_session)

    result = validate_candidate(perfume, _candidate())

    assert result.confidence == MatchConfidence.EXACT


def test_brand_mismatch_is_rejected(db_session):
    perfume = _perfume(db_session)

    result = validate_candidate(perfume, _candidate(brand="Dior"))

    assert result.confidence == MatchConfidence.REJECTED
    assert result.reason == "brand_mismatch"


def test_confirmed_brand_alias_is_accepted_not_rejected(db_session):
    # Regression: Parfumat's real product data reports this brand as
    # "Christian Dior", never bare "Dior" (confirmed live) - this used to
    # get rejected here as a "brand_mismatch" even after the scraper's
    # own discovery-stage filter was fixed to accept it, because this is
    # the separate, authoritative final gate and had its own bare
    # equality check.
    perfume = _dior_perfume(db_session)

    result = validate_candidate(
        perfume,
        MatchCandidate(
            raw_title="Dior (Christian Dior) Sauvage Parfum barbati 200 ml",
            brand="Christian Dior",
            name="Sauvage",
            concentration="Parfum",
            volume_ml=200,
            tester=False,
        ),
    )

    assert result.confidence == MatchConfidence.EXACT


def test_unrelated_perfume_name_is_rejected(db_session):
    perfume = _perfume(db_session)

    result = validate_candidate(
        perfume, _candidate(name="Erba Pura", raw_title="Xerjoff Erba Pura EDP 100 ml")
    )

    assert result.confidence == MatchConfidence.REJECTED
    assert result.reason == "name_mismatch"


def test_different_flanker_product_is_not_confused_with_monitored_perfume(db_session):
    # "Erba Gold Intense" must not be silently matched to monitored "Erba Gold".
    perfume = _perfume(db_session)

    result = validate_candidate(
        perfume,
        _candidate(name="Erba Gold Intense", raw_title="Xerjoff Erba Gold Intense EDP 100 ml"),
    )

    assert result.confidence == MatchConfidence.REJECTED


def test_minor_spacing_difference_is_high_confidence(db_session):
    perfume = _perfume(db_session)

    result = validate_candidate(
        perfume, _candidate(name="ErbaGold", raw_title="Xerjoff ErbaGold EDP 100ml")
    )

    assert result.confidence == MatchConfidence.HIGH_CONFIDENCE


def test_minor_typo_is_ambiguous_not_silently_accepted(db_session):
    # A borderline fuzzy score should not be treated as a confident match.
    perfume = _perfume(db_session)

    result = validate_candidate(
        perfume, _candidate(name="Erba Glod", raw_title="Xerjoff Erba Glod EDP 100ml")
    )

    assert result.confidence == MatchConfidence.AMBIGUOUS


def test_missing_variant_fields_is_ambiguous(db_session):
    perfume = _perfume(db_session)

    result = validate_candidate(perfume, _candidate(concentration=None, volume_ml=None))

    assert result.confidence == MatchConfidence.AMBIGUOUS
    assert result.reason == "missing_variant_fields"


def test_excluded_product_is_rejected(db_session):
    perfume = _perfume(db_session)

    result = validate_candidate(
        perfume, _candidate(raw_title="Xerjoff Erba Gold Gift Set EDP 100ml")
    )

    assert result.confidence == MatchConfidence.REJECTED
    assert result.reason.startswith("excluded:")


def test_only_exact_and_high_confidence_are_usable():
    from app.services.matching_service import MatchResult

    assert MatchResult(MatchConfidence.EXACT).is_usable is True
    assert MatchResult(MatchConfidence.HIGH_CONFIDENCE).is_usable is True
    assert MatchResult(MatchConfidence.AMBIGUOUS).is_usable is False
    assert MatchResult(MatchConfidence.REJECTED).is_usable is False


def test_resolve_variant_creates_distinct_variants_for_different_fields(db_session):
    perfume = _perfume(db_session)

    v_100_edp = resolve_variant(db_session, perfume, _candidate())
    v_50_edp = resolve_variant(db_session, perfume, _candidate(volume_ml=50))
    v_100_edt = resolve_variant(db_session, perfume, _candidate(concentration="EDT"))
    v_100_edp_tester = resolve_variant(db_session, perfume, _candidate(tester=True))

    ids = {v_100_edp.id, v_50_edp.id, v_100_edt.id, v_100_edp_tester.id}
    assert len(ids) == 4


def test_resolve_variant_reuses_existing_variant(db_session):
    perfume = _perfume(db_session)

    v1 = resolve_variant(db_session, perfume, _candidate())
    v2 = resolve_variant(db_session, perfume, _candidate())

    assert v1.id == v2.id


def test_resolve_variant_returns_none_without_concentration_or_volume(db_session):
    perfume = _perfume(db_session)

    assert resolve_variant(db_session, perfume, _candidate(concentration=None)) is None
    assert resolve_variant(db_session, perfume, _candidate(volume_ml=None)) is None
