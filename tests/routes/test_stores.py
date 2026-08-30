"""Integration tests for store management routes: list, enable/disable,
and the "by store" catalog view.
"""

from decimal import Decimal

from app.database.models import Availability
from app.database.repositories import perfumes as perfumes_repo
from app.database.repositories import store_products as store_products_repo
from app.database.repositories import stores as stores_repo
from app.database.repositories import variants as variants_repo
from app.database.seed import seed_initial_stores


def test_stores_list_shows_seeded_fragranza(client, db_session):
    seed_initial_stores(db_session)

    response = client.get("/stores")

    assert response.status_code == 200
    assert "Fragranza.ro" in response.text
    assert "Enabled" in response.text


def test_toggle_disables_enabled_store(client, db_session):
    seed_initial_stores(db_session)
    store = stores_repo.get_by_slug(db_session, "fragranza")

    response = client.post(f"/stores/{store.id}/toggle", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/stores"
    assert stores_repo.get(db_session, store.id).enabled is False


def test_toggle_re_enables_disabled_store(client, db_session):
    seed_initial_stores(db_session)
    store = stores_repo.get_by_slug(db_session, "fragranza")
    stores_repo.set_enabled(db_session, store, False)

    client.post(f"/stores/{store.id}/toggle")

    assert stores_repo.get(db_session, store.id).enabled is True


def test_toggle_missing_store_returns_404(client):
    response = client.post("/stores/999/toggle")

    assert response.status_code == 404


def test_disabling_store_does_not_delete_it(client, db_session):
    # Disabling must never remove the store row - only flip `enabled`.
    seed_initial_stores(db_session)
    store = stores_repo.get_by_slug(db_session, "fragranza")

    client.post(f"/stores/{store.id}/toggle")

    assert stores_repo.get_by_slug(db_session, "fragranza") is not None


def test_disabled_store_still_listed(client, db_session):
    seed_initial_stores(db_session)
    store = stores_repo.get_by_slug(db_session, "fragranza")
    stores_repo.set_enabled(db_session, store, False)

    response = client.get("/stores")

    assert "Fragranza.ro" in response.text
    assert "Disabled" in response.text


def test_nav_has_stores_link(client):
    response = client.get("/")

    assert 'href="/stores"' in response.text


def test_catalog_shows_empty_state_when_no_stores(client):
    response = client.get("/stores/catalog")

    assert response.status_code == 200
    assert "No stores configured yet." in response.text


def test_catalog_groups_in_stock_offers_by_store_and_perfume(client, db_session):
    seed_initial_stores(db_session)
    store = stores_repo.get_by_slug(db_session, "fragranza")
    perfume = perfumes_repo.create(
        db_session, brand="Xerjoff", name="Erba Gold", normalized_brand="xerjoff", normalized_name="erba gold"
    )
    variant_100 = variants_repo.get_or_create(
        db_session, perfume_id=perfume.id, concentration="EDP", volume_ml=100, tester=False
    )
    variant_50 = variants_repo.get_or_create(
        db_session, perfume_id=perfume.id, concentration="EDP", volume_ml=50, tester=False
    )
    store_products_repo.upsert_offer(
        db_session, store_id=store.id, variant_id=variant_100.id,
        product_url="https://fragranza.ro/x", store_product_identifier=None, product_title="x",
        price=Decimal("866.00"), old_price=None, currency="RON",
        discount_percentage=None, availability=Availability.IN_STOCK,
    )
    store_products_repo.upsert_offer(
        db_session, store_id=store.id, variant_id=variant_50.id,
        product_url="https://fragranza.ro/y", store_product_identifier=None, product_title="y",
        price=Decimal("600.00"), old_price=None, currency="RON",
        discount_percentage=None, availability=Availability.IN_STOCK,
    )

    response = client.get("/stores/catalog")

    assert response.status_code == 200
    assert "Fragranza.ro" in response.text
    assert "Xerjoff Erba Gold" in response.text
    assert "600.00" in response.text
    assert "866.00" in response.text
    # Both variants must appear once under one perfume entry, not as two
    # separate "Xerjoff Erba Gold" rows.
    assert response.text.count("Xerjoff Erba Gold") == 1


def test_catalog_excludes_out_of_stock_offers(client, db_session):
    seed_initial_stores(db_session)
    store = stores_repo.get_by_slug(db_session, "fragranza")
    perfume = perfumes_repo.create(
        db_session, brand="Dior", name="Sauvage", normalized_brand="dior", normalized_name="sauvage"
    )
    variant = variants_repo.get_or_create(
        db_session, perfume_id=perfume.id, concentration="EDT", volume_ml=100, tester=False
    )
    store_products_repo.upsert_offer(
        db_session, store_id=store.id, variant_id=variant.id,
        product_url="https://fragranza.ro/z", store_product_identifier=None, product_title="z",
        price=Decimal("400.00"), old_price=None, currency="RON",
        discount_percentage=None, availability=Availability.OUT_OF_STOCK,
    )

    response = client.get("/stores/catalog")

    assert "Dior Sauvage" not in response.text
    assert "Nothing currently in stock here." in response.text


def test_sidebar_has_by_store_link(client):
    response = client.get("/")

    assert 'href="/stores/catalog"' in response.text
