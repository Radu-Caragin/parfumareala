"""Integration tests for store management routes: list, enable/disable."""

from app.database.repositories import stores as stores_repo
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
