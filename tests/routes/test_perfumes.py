"""Integration tests for perfume management routes: add, edit, delete,
detail page.
"""

from decimal import Decimal

from app.database.models import Availability, Store
from app.database.repositories import perfumes as perfumes_repo
from app.database.repositories import prices as prices_repo
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
    # The check now runs in a background task on its own DB session (see
    # routes/perfumes.py) - it commits its changes, but db_session's own
    # identity map still holds the pre-check `perfume` object it loaded
    # above via _create_perfume(), so a plain re-fetch would silently
    # return that same stale in-memory copy instead of re-querying.
    # expire_all() forces the next access to hit the database again.
    db_session.expire_all()
    assert perfumes_repo.get(db_session, perfume.id).last_checked_at is not None


def test_check_perfume_route_skips_scheduling_when_already_active_for_this_perfume(client, db_session):
    # Simulates a second click on the same perfume's "Check prices" while
    # a check for it is already in flight (TestClient runs a scheduled
    # background task to completion before client.post() itself returns,
    # so a literal second post() here would find the first run already
    # finished and released - the claim is taken directly instead, the
    # same state an overlapping request would find it in).
    from app.services import progress as progress_service

    perfume = _create_perfume(db_session)
    progress_service.claim_check_perfume(perfume.id)

    response = client.post(f"/perfumes/{perfume.id}/check", follow_redirects=False)

    assert response.status_code == 303
    db_session.expire_all()
    assert perfumes_repo.get(db_session, perfume.id).last_checked_at is None


def test_check_perfume_route_skips_scheduling_while_check_all_is_active(client, db_session):
    from app.services import progress as progress_service

    perfume = _create_perfume(db_session)
    progress_service.claim_check_all()

    response = client.post(f"/perfumes/{perfume.id}/check", follow_redirects=False)

    assert response.status_code == 303
    db_session.expire_all()
    assert perfumes_repo.get(db_session, perfume.id).last_checked_at is None


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


def test_perfume_detail_shows_price_chart_with_stats(client, db_session):
    perfume = _create_perfume(db_session)
    variant = variants_repo.get_or_create(
        db_session, perfume_id=perfume.id, concentration="EDP", volume_ml=100, tester=False
    )
    store = Store(name="Fragranza.ro", slug="fragranza", base_url="https://fragranza.ro", enabled=True, scraper_identifier="fragranza")
    db_session.add(store)
    db_session.commit()
    sp = store_products_repo.upsert_offer(
        db_session, store_id=store.id, variant_id=variant.id,
        product_url="https://fragranza.ro/x", store_product_identifier=None, product_title="x",
        price=Decimal("799.00"), old_price=None, currency="RON",
        discount_percentage=None, availability=Availability.IN_STOCK,
    )
    prices_repo.record_if_changed(
        db_session, store_product_id=sp.id, scrape_run_id=None,
        price=Decimal("799.00"), old_price=None, currency="RON",
        discount_percentage=None, availability=Availability.IN_STOCK,
    )
    prices_repo.record_if_changed(
        db_session, store_product_id=sp.id, scrape_run_id=None,
        price=Decimal("749.00"), old_price=None, currency="RON",
        discount_percentage=None, availability=Availability.IN_STOCK,
    )

    response = client.get(f"/perfumes/{perfume.id}")

    assert 'class="price-chart"' in response.text
    assert "749.00 RON" in response.text
    assert "799.00 RON" in response.text
    assert "Fragranza.ro" in response.text
    # The price dropped from 799 to 749 since the last recorded change -
    # a real, tracked drop, shown regardless of any store-claimed old price.
    assert "real-drop-badge" in response.text
    assert "50.00 RON real" in response.text


def test_perfume_detail_store_table_always_visible_history_collapsed_per_store(client, db_session):
    # The store/price list must stay visible exactly as before, with the
    # "Price history" toggle sitting right next to "View product" - only
    # each store's own history content (in the row right below) is
    # tucked away, collapsed by default, never one shared table/chart
    # for every store.
    perfume = _create_perfume(db_session)
    variant = variants_repo.get_or_create(
        db_session, perfume_id=perfume.id, concentration="EDP", volume_ml=100, tester=False
    )
    store = Store(name="Fragranza.ro", slug="fragranza", base_url="https://fragranza.ro", enabled=True, scraper_identifier="fragranza")
    db_session.add(store)
    db_session.commit()
    store_products_repo.upsert_offer(
        db_session, store_id=store.id, variant_id=variant.id,
        product_url="https://fragranza.ro/x", store_product_identifier=None, product_title="x",
        price=Decimal("799.00"), old_price=None, currency="RON",
        discount_percentage=None, availability=Availability.IN_STOCK,
    )

    response = client.get(f"/perfumes/{perfume.id}")

    # Store name and price are directly in the response, before the
    # collapsed history content.
    content_start = response.text.index('class="store-history-content"')
    assert response.text.index("Fragranza.ro") < content_start
    assert response.text.index("799.00") < content_start
    # "Price history" sits next to "View product" in the same cell.
    view_product_idx = response.text.index("View product")
    price_history_idx = response.text.index(">Price history<")
    assert view_product_idx < price_history_idx < content_start
    # The history row itself is collapsed by default (no is-open class).
    assert 'class="store-history-row is-open"' not in response.text
    assert 'class="store-history-content"' in response.text


def test_perfume_detail_no_chart_when_no_price_history_yet(client, db_session):
    perfume = _create_perfume(db_session)
    variants_repo.get_or_create(db_session, perfume_id=perfume.id, concentration="EDP", volume_ml=100, tester=False)

    response = client.get(f"/perfumes/{perfume.id}")

    assert 'class="price-chart"' not in response.text
