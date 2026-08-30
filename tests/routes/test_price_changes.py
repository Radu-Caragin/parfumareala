"""Integration tests for the /price-changes overview."""

from decimal import Decimal

from app.database.models import Availability, RunType, Store
from app.database.repositories import perfumes as perfumes_repo
from app.database.repositories import prices as prices_repo
from app.database.repositories import scrape_runs as scrape_runs_repo
from app.database.repositories import store_products as store_products_repo
from app.database.repositories import variants as variants_repo


def _perfume_variant_store_product(db_session):
    store = Store(name="Fragranza.ro", slug="fragranza", base_url="https://fragranza.ro", enabled=True, scraper_identifier="fragranza")
    db_session.add(store)
    db_session.commit()
    perfume = perfumes_repo.create(
        db_session, brand="Xerjoff", name="Erba Gold", normalized_brand="xerjoff", normalized_name="erba gold"
    )
    variant = variants_repo.get_or_create(
        db_session, perfume_id=perfume.id, concentration="EDP", volume_ml=100, tester=False
    )
    store_product = store_products_repo.upsert_offer(
        db_session, store_id=store.id, variant_id=variant.id,
        product_url="https://fragranza.ro/x", store_product_identifier=None, product_title="x",
        price=Decimal("799.00"), old_price=None, currency="RON",
        discount_percentage=None, availability=Availability.IN_STOCK,
    )
    return perfume, variant, store_product


def test_price_changes_shows_empty_state_when_no_run_yet(client):
    response = client.get("/price-changes")

    assert response.status_code == 200
    assert "No price check has been run yet." in response.text


def test_price_changes_shows_empty_state_when_last_run_had_no_changes(client, db_session):
    perfume, variant, store_product = _perfume_variant_store_product(db_session)
    run = scrape_runs_repo.start_run(db_session, run_type=RunType.ALL, perfume_count=1, store_count=1)
    prices_repo.record_if_changed(
        db_session, store_product_id=store_product.id, scrape_run_id=run.id,
        price=Decimal("799.00"), old_price=None, currency="RON",
        discount_percentage=None, availability=Availability.IN_STOCK,
    )

    response = client.get("/price-changes")

    assert "No price changes at the last check." in response.text


def test_price_changes_lists_price_drop_with_delta(client, db_session):
    perfume, variant, store_product = _perfume_variant_store_product(db_session)
    run_1 = scrape_runs_repo.start_run(db_session, run_type=RunType.ALL, perfume_count=1, store_count=1)
    prices_repo.record_if_changed(
        db_session, store_product_id=store_product.id, scrape_run_id=run_1.id,
        price=Decimal("799.00"), old_price=None, currency="RON",
        discount_percentage=None, availability=Availability.IN_STOCK,
    )
    run_2 = scrape_runs_repo.start_run(db_session, run_type=RunType.ALL, perfume_count=1, store_count=1)
    prices_repo.record_if_changed(
        db_session, store_product_id=store_product.id, scrape_run_id=run_2.id,
        price=Decimal("749.00"), old_price=None, currency="RON",
        discount_percentage=None, availability=Availability.IN_STOCK,
    )

    response = client.get("/price-changes")

    assert "Xerjoff Erba Gold" in response.text
    assert "799.00 RON" in response.text
    assert "749.00 RON" in response.text
    assert "-50.00 RON" in response.text
    assert 'href="https://fragranza.ro/x"' in response.text


def test_price_changes_shows_positive_sign_for_price_increase(client, db_session):
    perfume, variant, store_product = _perfume_variant_store_product(db_session)
    run_1 = scrape_runs_repo.start_run(db_session, run_type=RunType.ALL, perfume_count=1, store_count=1)
    prices_repo.record_if_changed(
        db_session, store_product_id=store_product.id, scrape_run_id=run_1.id,
        price=Decimal("799.00"), old_price=None, currency="RON",
        discount_percentage=None, availability=Availability.IN_STOCK,
    )
    run_2 = scrape_runs_repo.start_run(db_session, run_type=RunType.ALL, perfume_count=1, store_count=1)
    prices_repo.record_if_changed(
        db_session, store_product_id=store_product.id, scrape_run_id=run_2.id,
        price=Decimal("849.00"), old_price=None, currency="RON",
        discount_percentage=None, availability=Availability.IN_STOCK,
    )

    response = client.get("/price-changes")

    assert "+50.00 RON" in response.text
