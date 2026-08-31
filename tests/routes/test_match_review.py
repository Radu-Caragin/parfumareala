"""Integration tests for the /match-review routes."""

from decimal import Decimal

from app.database.models import Availability, MatchReviewStatus, Store
from app.database.repositories import match_review as match_review_repo
from app.database.repositories import name_aliases as name_aliases_repo
from app.database.repositories import perfumes as perfumes_repo
from app.database.repositories import variants as variants_repo


def _pending_match(db_session):
    store = Store(name="Fake Store", slug="fake-store", base_url="https://fake.test", enabled=True, scraper_identifier="fake-store")
    db_session.add(store)
    db_session.commit()
    perfume = perfumes_repo.create(
        db_session, brand="Xerjoff", name="Naxos", normalized_brand="xerjoff", normalized_name="naxos"
    )
    match = match_review_repo.upsert_pending(
        db_session,
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
    return perfume, store, match


def test_match_review_shows_empty_state_when_nothing_pending(client):
    response = client.get("/match-review")

    assert response.status_code == 200
    assert "Nothing to review right now." in response.text


def test_match_review_lists_pending_match(client, db_session):
    perfume, store, match = _pending_match(db_session)

    response = client.get("/match-review")

    assert "Xerjoff Naxos" in response.text
    assert "Fake Store" in response.text
    assert "XJ 1861 Naxos" in response.text
    assert "899.00 RON" in response.text


def test_confirm_route_creates_alias_and_removes_from_queue(client, db_session):
    perfume, store, match = _pending_match(db_session)

    response = client.post(f"/match-review/{match.id}/confirm", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/match-review"
    assert match_review_repo.list_pending(db_session) == []
    aliases = name_aliases_repo.list_for_perfume(db_session, perfume.id)
    assert len(aliases) == 1
    variants = variants_repo.list_for_perfume(db_session, perfume.id)
    assert len(variants) == 1


def test_reject_route_removes_from_queue_without_creating_alias(client, db_session):
    perfume, store, match = _pending_match(db_session)

    response = client.post(f"/match-review/{match.id}/reject", follow_redirects=False)

    assert response.status_code == 303
    assert match_review_repo.list_pending(db_session) == []
    assert name_aliases_repo.list_for_perfume(db_session, perfume.id) == []

    refreshed = match_review_repo.get(db_session, match.id)
    assert refreshed.status == MatchReviewStatus.REJECTED


def test_confirm_missing_match_404(client):
    response = client.post("/match-review/999/confirm")

    assert response.status_code == 404


def test_reject_missing_match_404(client):
    response = client.post("/match-review/999/reject")

    assert response.status_code == 404
