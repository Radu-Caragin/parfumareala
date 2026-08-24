"""Integration tests for perfume management routes: add, edit, delete,
detail page.
"""

from decimal import Decimal

from app.database.models import Availability, Store
from app.database.repositories import perfumes as perfumes_repo
from app.database.repositories import store_products as store_products_repo
from app.database.repositories import variants as variants_repo


def _create_perfume(db_session, brand="Xerjoff", name="Erba Gold"):
    return perfumes_repo.create(
        db_session,
        brand=brand,
        name=name,
        normalized_brand=brand.lower(),
        normalized_name=name.lower(),
    )


def test_new_perfume_form_renders(client):
    response = client.get("/perfumes/new")

    assert response.status_code == 200
    assert "Add perfume" in response.text


def test_create_perfume_redirects_to_detail_page(client, db_session):
    response = client.post(
        "/perfumes", data={"brand": "Xerjoff", "name": "Erba Gold"}, follow_redirects=False
    )

    assert response.status_code == 303
    perfumes = perfumes_repo.list_all(db_session)
    assert len(perfumes) == 1
    assert response.headers["location"] == f"/perfumes/{perfumes[0].id}"
    assert perfumes[0].normalized_brand == "xerjoff"
    assert perfumes[0].normalized_name == "erba gold"


def test_create_perfume_rejects_empty_fields(client, db_session):
    response = client.post("/perfumes", data={"brand": "   ", "name": "Erba Gold"})

    assert response.status_code == 400
    assert "required" in response.text
    assert perfumes_repo.list_all(db_session) == []


def test_perfume_detail_shows_brand_and_name(client, db_session):
    perfume = _create_perfume(db_session)

    response = client.get(f"/perfumes/{perfume.id}")

    assert response.status_code == 200
    assert "Xerjoff" in response.text
    assert "Erba Gold" in response.text


def test_perfume_detail_404_for_missing_perfume(client):
    response = client.get("/perfumes/999")

    assert response.status_code == 404


def test_404_renders_styled_html_page_not_raw_json(client):
    response = client.get("/perfumes/999")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert "Perfume not found" in response.text
    assert "Back to dashboard" in response.text
    assert 'class="error-page"' in response.text


def test_edit_form_prefills_existing_values(client, db_session):
    perfume = _create_perfume(db_session)

    response = client.get(f"/perfumes/{perfume.id}/edit")

    assert response.status_code == 200
    assert 'value="Xerjoff"' in response.text
    assert 'value="Erba Gold"' in response.text


def test_edit_form_404_for_missing_perfume(client):
    response = client.get("/perfumes/999/edit")

    assert response.status_code == 404


def test_update_perfume_changes_name_and_redirects(client, db_session):
    perfume = _create_perfume(db_session)

    response = client.post(
        f"/perfumes/{perfume.id}/edit", data={"brand": "Xerjoff", "name": "Naxos"}, follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/perfumes/{perfume.id}"
    updated = perfumes_repo.get(db_session, perfume.id)
    assert updated.name == "Naxos"
    assert updated.normalized_name == "naxos"


def test_update_perfume_rejects_empty_fields(client, db_session):
    perfume = _create_perfume(db_session)

    response = client.post(f"/perfumes/{perfume.id}/edit", data={"brand": "", "name": "Naxos"})

    assert response.status_code == 400
    unchanged = perfumes_repo.get(db_session, perfume.id)
    assert unchanged.name == "Erba Gold"


def test_delete_perfume_removes_it_and_redirects_to_dashboard(client, db_session):
    perfume = _create_perfume(db_session)

    response = client.post(f"/perfumes/{perfume.id}/delete", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert perfumes_repo.get(db_session, perfume.id) is None


def test_delete_missing_perfume_returns_404(client):
    response = client.post("/perfumes/999/delete")

    assert response.status_code == 404


def test_check_perfume_with_no_enabled_stores_still_marks_checked(client, db_session):
    # No stores are seeded/enabled in this isolated test DB, so this never
    # touches the network - it only verifies the route wiring.
    perfume = _create_perfume(db_session)

    response = client.post(f"/perfumes/{perfume.id}/check", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == f"/perfumes/{perfume.id}"
    assert perfumes_repo.get(db_session, perfume.id).last_checked_at is not None


def test_check_perfume_missing_returns_404(client):
    response = client.post("/perfumes/999/check")

    assert response.status_code == 404


def test_perfume_detail_shows_check_prices_button(client, db_session):
    perfume = _create_perfume(db_session)

    response = client.get(f"/perfumes/{perfume.id}")

    assert f'action="/perfumes/{perfume.id}/check"' in response.text
    assert "Check prices" in response.text


def test_perfume_detail_shows_best_price_across_stores(client, db_session):
    perfume = _create_perfume(db_session)
    variant = variants_repo.get_or_create(
        db_session, perfume_id=perfume.id, concentration="EDP", volume_ml=100, tester=False
    )
    store_a = Store(name="Store A", slug="store-a", base_url="https://a.test", enabled=True, scraper_identifier="store-a")
    store_b = Store(name="Store B", slug="store-b", base_url="https://b.test", enabled=True, scraper_identifier="store-b")
    db_session.add_all([store_a, store_b])
    db_session.commit()

    store_products_repo.upsert_offer(
        db_session, store_id=store_a.id, variant_id=variant.id,
        product_url="https://a.test/x", store_product_identifier=None, product_title="x",
        price=Decimal("850.00"), old_price=None, currency="RON",
        discount_percentage=None, availability=Availability.OUT_OF_STOCK,
    )
    store_products_repo.upsert_offer(
        db_session, store_id=store_b.id, variant_id=variant.id,
        product_url="https://b.test/x", store_product_identifier=None, product_title="x",
        price=Decimal("799.00"), old_price=None, currency="RON",
        discount_percentage=None, availability=Availability.IN_STOCK,
    )

    response = client.get(f"/perfumes/{perfume.id}")

    assert "Best price" in response.text
    assert "Store B" in response.text
    assert "799.00" in response.text
    assert "best-price-row" in response.text
