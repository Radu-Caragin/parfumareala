"""Integration tests for the dashboard route, using an isolated in-memory
database via dependency override - never touches the real data/*.db file.
"""

from app.database.repositories import perfumes as perfumes_repo


def test_health_endpoint(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_dashboard_shows_empty_state_when_no_perfumes(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "No perfumes are being monitored yet." in response.text


def test_dashboard_lists_monitored_perfumes(client, db_session):
    perfumes_repo.create(
        db_session, brand="Xerjoff", name="Erba Gold", normalized_brand="xerjoff", normalized_name="erba gold"
    )

    response = client.get("/")

    assert response.status_code == 200
    assert "Xerjoff" in response.text
    assert "Erba Gold" in response.text


def test_dashboard_shows_never_checked_when_no_last_checked_at(client, db_session):
    perfumes_repo.create(
        db_session, brand="Dior", name="Sauvage", normalized_brand="dior", normalized_name="sauvage"
    )

    response = client.get("/")

    assert "Never" in response.text


def test_dashboard_has_add_perfume_button(client):
    response = client.get("/")

    assert 'href="/perfumes/new"' in response.text


def test_dashboard_perfume_card_links_to_detail_and_edit(client, db_session):
    perfume = perfumes_repo.create(
        db_session, brand="Xerjoff", name="Erba Gold", normalized_brand="xerjoff", normalized_name="erba gold"
    )

    response = client.get("/")

    assert f'href="/perfumes/{perfume.id}"' in response.text
    assert f'href="/perfumes/{perfume.id}/edit"' in response.text
    assert f'/perfumes/{perfume.id}/delete' in response.text
    assert f'action="/perfumes/{perfume.id}/check"' in response.text


def test_dashboard_hides_check_all_when_no_perfumes(client):
    response = client.get("/")

    assert 'action="/check-all"' not in response.text


def test_dashboard_shows_check_all_when_perfumes_exist(client, db_session):
    perfumes_repo.create(
        db_session, brand="Xerjoff", name="Erba Gold", normalized_brand="xerjoff", normalized_name="erba gold"
    )

    response = client.get("/")

    assert 'action="/check-all"' in response.text


def test_check_all_with_no_stores_still_marks_perfumes_checked(client, db_session):
    # No stores are seeded/enabled in this isolated test DB, so this never
    # touches the network - it only verifies the route wiring.
    perfume = perfumes_repo.create(
        db_session, brand="Xerjoff", name="Erba Gold", normalized_brand="xerjoff", normalized_name="erba gold"
    )

    response = client.post("/check-all", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert perfumes_repo.get(db_session, perfume.id).last_checked_at is not None
