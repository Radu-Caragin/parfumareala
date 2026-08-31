"""Integration tests for the price history route."""

from decimal import Decimal

from app.database.models import Availability, Store
from app.database.repositories import perfumes as perfumes_repo
from app.database.repositories import prices as prices_repo
from app.database.repositories import store_products as store_products_repo
from app.database.repositories import variants as variants_repo


def _setup_store_product(db_session):
    perfume = perfumes_repo.create(
        db_session, brand="Xerjoff", name="Erba Gold", normalized_brand="xerjoff", normalized_name="erba gold"
    )
    variant = variants_repo.get_or_create(
        db_session, perfume_id=perfume.id, concentration="EDP", volume_ml=100, tester=False
    )
    store = Store(name="Fragranza.ro", slug="fragranza", base_url="https://fragranza.ro", enabled=True, scraper_identifier="fragranza")
    db_session.add(store)
    db_session.commit()

    store_product = store_products_repo.upsert_offer(
        db_session, store_id=store.id, variant_id=variant.id,
        product_url="https://fragranza.ro/x", store_product_identifier=None, product_title="x",
        price=Decimal("849.00"), old_price=None, currency="RON",
        discount_percentage=None, availability=Availability.IN_STOCK,
    )
    return perfume, store_product


def test_price_history_empty_state(client, db_session):
    perfume, store_product = _setup_store_product(db_session)

    response = client.get(f"/perfumes/{perfume.id}/history/{store_product.id}")

    assert response.status_code == 200
    assert "No price history recorded yet." in response.text


def test_price_history_shows_entries_oldest_first(client, db_session):
    perfume, store_product = _setup_store_product(db_session)

    prices_repo.record_if_changed(
        db_session, store_product_id=store_product.id, scrape_run_id=None,
        price=Decimal("849.00"), old_price=None, currency="RON",
        discount_percentage=None, availability=Availability.IN_STOCK,
    )
    prices_repo.record_if_changed(
        db_session, store_product_id=store_product.id, scrape_run_id=None,
        price=Decimal("819.00"), old_price=None, currency="RON",
        discount_percentage=None, availability=Availability.IN_STOCK,
    )
    prices_repo.record_if_changed(
        db_session, store_product_id=store_product.id, scrape_run_id=None,
        price=Decimal("799.00"), old_price=None, currency="RON",
        discount_percentage=None, availability=Availability.IN_STOCK,
    )

    response = client.get(f"/perfumes/{perfume.id}/history/{store_product.id}")

    assert response.status_code == 200
    first = response.text.find("849.00")
    second = response.text.find("819.00")
    third = response.text.find("799.00")
    assert first < second < third  # oldest-first order


def test_price_history_404_for_unrelated_perfume(client, db_session):
    perfume, store_product = _setup_store_product(db_session)
    other_perfume = perfumes_repo.create(
        db_session, brand="Dior", name="Sauvage", normalized_brand="dior", normalized_name="sauvage"
    )

    response = client.get(f"/perfumes/{other_perfume.id}/history/{store_product.id}")

    assert response.status_code == 404


def test_price_history_404_for_missing_store_product(client, db_session):
    perfume, _ = _setup_store_product(db_session)

    response = client.get(f"/perfumes/{perfume.id}/history/999")

    assert response.status_code == 404


def test_detail_page_shows_history_inline_per_store_instead_of_linking_out(client, db_session):
    # Price history is now shown inline, in its own dropdown per store
    # row (see perfumes/detail.html) - the detail page no longer links
    # out to this module's own standalone page (still reachable directly
    # if navigated to, just not linked from there anymore).
    perfume, store_product = _setup_store_product(db_session)

    response = client.get(f"/perfumes/{perfume.id}")

    assert f'href="/perfumes/{perfume.id}/history/{store_product.id}"' not in response.text
    assert "Price history" in response.text
    assert 'class="store-history-content"' in response.text
