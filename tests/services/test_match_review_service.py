"""Tests for match_review_service - confirming/rejecting an AmbiguousMatch."""

from decimal import Decimal

from app.database.models import Availability, MatchReviewStatus, Store
from app.database.repositories import alerts as alerts_repo
from app.database.repositories import match_review as match_review_repo
from app.database.repositories import name_aliases as name_aliases_repo
from app.database.repositories import perfumes as perfumes_repo
from app.database.repositories import prices as prices_repo
from app.database.repositories import store_products as store_products_repo
from app.database.repositories import variants as variants_repo
from app.services import match_review_service


def _perfume_and_store(db_session):
    store = Store(name="Fake Store", slug="fake-store", base_url="https://fake.test", enabled=True, scraper_identifier="fake-store")
    db_session.add(store)
    db_session.commit()
    perfume = perfumes_repo.create(
        db_session, brand="Xerjoff", name="Naxos", normalized_brand="xerjoff", normalized_name="naxos"
    )
    return perfume, store


def _pending_match(db_session, perfume, store, **overrides):
    defaults = dict(
        perfume_id=perfume.id,
        store_id=store.id,
        raw_title="Xerjoff XJ 1861 Naxos Eau de Parfum 100 ml",
        candidate_brand="Xerjoff",
        candidate_name="XJ 1861 Naxos",
        concentration="EDP",
        volume_ml=100,
        tester=False,
        price=Decimal("899.00"),
        old_price=None,
        currency="RON",
        availability=Availability.IN_STOCK,
        product_url="https://fake.test/xj-1861-naxos",
        store_product_identifier=None,
        match_score=62,
    )
    defaults.update(overrides)
    return match_review_repo.upsert_pending(db_session, **defaults)


def test_confirm_match_creates_alias(db_session):
    perfume, store = _perfume_and_store(db_session)
    match = _pending_match(db_session, perfume, store)

    match_review_service.confirm_match(db_session, match)

    aliases = name_aliases_repo.list_for_perfume(db_session, perfume.id)
    assert len(aliases) == 1
    assert aliases[0].alias == "XJ 1861 Naxos"
    assert aliases[0].normalized_alias == "xj 1861 naxos"


def test_confirm_match_persists_offer_immediately(db_session):
    perfume, store = _perfume_and_store(db_session)
    match = _pending_match(db_session, perfume, store)

    match_review_service.confirm_match(db_session, match)

    variants = variants_repo.list_for_perfume(db_session, perfume.id)
    assert len(variants) == 1
    assert variants[0].concentration == "EDP"
    assert variants[0].volume_ml == 100

    store_products = store_products_repo.list_for_variant(db_session, variants[0].id)
    assert len(store_products) == 1
    assert store_products[0].current_price == Decimal("899.00")
    assert store_products[0].availability == Availability.IN_STOCK
    assert store_products[0].product_url == "https://fake.test/xj-1861-naxos"

    history = prices_repo.list_for_store_product(db_session, store_products[0].id)
    assert len(history) == 1


def test_confirm_match_marks_status_confirmed(db_session):
    perfume, store = _perfume_and_store(db_session)
    match = _pending_match(db_session, perfume, store)

    match_review_service.confirm_match(db_session, match)

    refreshed = match_review_repo.get(db_session, match.id)
    assert refreshed.status == MatchReviewStatus.CONFIRMED
    assert refreshed.resolved_at is not None


def test_confirm_match_triggers_a_qualifying_alert(db_session):
    perfume, store = _perfume_and_store(db_session)
    match = _pending_match(db_session, perfume, store, price=Decimal("799.00"))
    variant = variants_repo.get_or_create(
        db_session, perfume_id=perfume.id, concentration="EDP", volume_ml=100, tester=False
    )
    alerts_repo.create(db_session, perfume_variant_id=variant.id, target_price=Decimal("850.00"), currency="RON")

    match_review_service.confirm_match(db_session, match)

    alert = alerts_repo.list_for_variant(db_session, variant.id)[0]
    assert alert.last_triggered_price == Decimal("799.00")


def test_reject_match_marks_status_rejected_without_persisting_anything(db_session):
    perfume, store = _perfume_and_store(db_session)
    match = _pending_match(db_session, perfume, store)

    match_review_service.reject_match(db_session, match)

    refreshed = match_review_repo.get(db_session, match.id)
    assert refreshed.status == MatchReviewStatus.REJECTED
    assert refreshed.resolved_at is not None

    assert variants_repo.list_for_perfume(db_session, perfume.id) == []
    assert name_aliases_repo.list_for_perfume(db_session, perfume.id) == []
