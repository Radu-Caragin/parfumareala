"""Integration tests for local price alert routes."""

from decimal import Decimal

from app.database.models import Availability, Store
from app.database.repositories import alerts as alerts_repo
from app.database.repositories import perfumes as perfumes_repo
from app.database.repositories import store_products as store_products_repo
from app.database.repositories import variants as variants_repo


def _perfume_and_variant(db_session):
    perfume = perfumes_repo.create(
        db_session, brand="Xerjoff", name="Erba Gold", normalized_brand="xerjoff", normalized_name="erba gold"
    )
    variant = variants_repo.get_or_create(
        db_session, perfume_id=perfume.id, concentration="EDP", volume_ml=100, tester=False
    )
    return perfume, variant


def test_create_alert_redirects_to_perfume(client, db_session):
    perfume, variant = _perfume_and_variant(db_session)

    response = client.post(
        f"/perfumes/{perfume.id}/variants/{variant.id}/alerts",
        data={"target_price": "750"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/perfumes/{perfume.id}"
    alerts = alerts_repo.list_for_variant(db_session, variant.id)
    assert len(alerts) == 1
    assert alerts[0].target_price == Decimal("750.00")


def test_create_alert_accepts_comma_decimal(client, db_session):
    perfume, variant = _perfume_and_variant(db_session)

    client.post(f"/perfumes/{perfume.id}/variants/{variant.id}/alerts", data={"target_price": "749,50"})

    alerts = alerts_repo.list_for_variant(db_session, variant.id)
    assert alerts[0].target_price == Decimal("749.50")


def test_create_alert_ignores_invalid_price(client, db_session):
    perfume, variant = _perfume_and_variant(db_session)

    client.post(f"/perfumes/{perfume.id}/variants/{variant.id}/alerts", data={"target_price": "not-a-number"})

    assert alerts_repo.list_for_variant(db_session, variant.id) == []


def test_create_alert_404_for_variant_from_other_perfume(client, db_session):
    perfume_a, variant_a = _perfume_and_variant(db_session)
    perfume_b = perfumes_repo.create(
        db_session, brand="Dior", name="Sauvage", normalized_brand="dior", normalized_name="sauvage"
    )

    response = client.post(
        f"/perfumes/{perfume_b.id}/variants/{variant_a.id}/alerts", data={"target_price": "750"}
    )

    assert response.status_code == 404


def test_delete_alert_removes_it_and_redirects(client, db_session):
    perfume, variant = _perfume_and_variant(db_session)
    alert = alerts_repo.create(db_session, perfume_variant_id=variant.id, target_price=Decimal("750.00"), currency="RON")

    response = client.post(f"/alerts/{alert.id}/delete", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == f"/perfumes/{perfume.id}"
    assert alerts_repo.get(db_session, alert.id) is None


def test_delete_missing_alert_404(client):
    response = client.post("/alerts/999/delete")

    assert response.status_code == 404


def test_detail_page_shows_existing_alert(client, db_session):
    perfume, variant = _perfume_and_variant(db_session)
    alerts_repo.create(db_session, perfume_variant_id=variant.id, target_price=Decimal("750.00"), currency="RON")

    response = client.get(f"/perfumes/{perfume.id}")

    assert "Alert: price" in response.text
    assert "750.00" in response.text


def test_detail_page_shows_triggered_alert_banner(client, db_session):
    perfume, variant = _perfume_and_variant(db_session)
    store = Store(name="Fragranza.ro", slug="fragranza", base_url="https://fragranza.ro", enabled=True, scraper_identifier="fragranza")
    db_session.add(store)
    db_session.commit()

    store_products_repo.upsert_offer(
        db_session, store_id=store.id, variant_id=variant.id,
        product_url="https://fragranza.ro/x", store_product_identifier=None, product_title="x",
        price=Decimal("729.00"), old_price=None, currency="RON",
        discount_percentage=None, availability=Availability.IN_STOCK,
    )
    alerts_repo.create(db_session, perfume_variant_id=variant.id, target_price=Decimal("750.00"), currency="RON")

    response = client.get(f"/perfumes/{perfume.id}")

    assert "Price alert triggered" in response.text
    assert "729.00" in response.text


def test_detail_page_no_banner_when_no_alert_triggered(client, db_session):
    perfume, variant = _perfume_and_variant(db_session)

    response = client.get(f"/perfumes/{perfume.id}")

    assert "Price alert triggered" not in response.text
