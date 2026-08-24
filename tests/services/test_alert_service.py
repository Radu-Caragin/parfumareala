"""Tests for alert_service: local price alerts, no external notifications.

instructions.md section 38: an alert triggers when at least one currently
available (in-stock) store offer is <= the target price - an out-of-stock
offer never counts, even if cheaper.
"""

from decimal import Decimal

from app.database.models import Availability, Store
from app.database.repositories import alerts as alerts_repo
from app.database.repositories import perfumes as perfumes_repo
from app.database.repositories import store_products as store_products_repo
from app.database.repositories import variants as variants_repo
from app.services.alert_service import current_alert_status, evaluate_variant_alerts


def _store(db_session, slug="store-a", name="Store A"):
    store = Store(name=name, slug=slug, base_url="https://example.test", enabled=True, scraper_identifier=slug)
    db_session.add(store)
    db_session.commit()
    db_session.refresh(store)
    return store


def _perfume_and_variant(db_session):
    perfume = perfumes_repo.create(
        db_session, brand="Xerjoff", name="Erba Gold", normalized_brand="xerjoff", normalized_name="erba gold"
    )
    variant = variants_repo.get_or_create(
        db_session, perfume_id=perfume.id, concentration="EDP", volume_ml=100, tester=False
    )
    return perfume, variant


def _add_offer(db_session, *, store, variant, price, availability):
    return store_products_repo.upsert_offer(
        db_session, store_id=store.id, variant_id=variant.id,
        product_url=f"https://{store.slug}.test/x", store_product_identifier=None, product_title="x",
        price=price, old_price=None, currency="RON",
        discount_percentage=None, availability=availability,
    )


def test_alert_triggers_when_in_stock_offer_at_or_below_target(db_session):
    _, variant = _perfume_and_variant(db_session)
    store = _store(db_session)
    _add_offer(db_session, store=store, variant=variant, price=Decimal("729.00"), availability=Availability.IN_STOCK)
    alert = alerts_repo.create(db_session, perfume_variant_id=variant.id, target_price=Decimal("750.00"), currency="RON")
    db_session.refresh(variant)

    triggered = evaluate_variant_alerts(db_session, variant)

    assert len(triggered) == 1
    assert triggered[0].alert.id == alert.id
    assert triggered[0].matching_offers[0].current_price == Decimal("729.00")

    refreshed = alerts_repo.get(db_session, alert.id)
    assert refreshed.last_triggered_price == Decimal("729.00")
    assert refreshed.last_triggered_at is not None


def test_alert_does_not_trigger_when_price_above_target(db_session):
    _, variant = _perfume_and_variant(db_session)
    store = _store(db_session)
    _add_offer(db_session, store=store, variant=variant, price=Decimal("799.00"), availability=Availability.IN_STOCK)
    alerts_repo.create(db_session, perfume_variant_id=variant.id, target_price=Decimal("750.00"), currency="RON")
    db_session.refresh(variant)

    triggered = evaluate_variant_alerts(db_session, variant)

    assert triggered == []


def test_out_of_stock_offer_never_triggers_alert(db_session):
    _, variant = _perfume_and_variant(db_session)
    store = _store(db_session)
    _add_offer(db_session, store=store, variant=variant, price=Decimal("500.00"), availability=Availability.OUT_OF_STOCK)
    alerts_repo.create(db_session, perfume_variant_id=variant.id, target_price=Decimal("750.00"), currency="RON")
    db_session.refresh(variant)

    triggered = evaluate_variant_alerts(db_session, variant)

    assert triggered == []


def test_disabled_alert_never_triggers(db_session):
    _, variant = _perfume_and_variant(db_session)
    store = _store(db_session)
    _add_offer(db_session, store=store, variant=variant, price=Decimal("500.00"), availability=Availability.IN_STOCK)
    alert = alerts_repo.create(db_session, perfume_variant_id=variant.id, target_price=Decimal("750.00"), currency="RON")
    alerts_repo.set_enabled(db_session, alert, False)
    db_session.refresh(variant)

    triggered = evaluate_variant_alerts(db_session, variant)

    assert triggered == []


def test_current_alert_status_is_live_without_persisting(db_session):
    _, variant = _perfume_and_variant(db_session)
    store = _store(db_session)
    _add_offer(db_session, store=store, variant=variant, price=Decimal("729.00"), availability=Availability.IN_STOCK)
    alert = alerts_repo.create(db_session, perfume_variant_id=variant.id, target_price=Decimal("750.00"), currency="RON")
    db_session.refresh(variant)

    assert alert.last_triggered_at is None  # never evaluated/persisted

    status = current_alert_status(variant)

    assert len(status) == 1
    assert status[0].alert.id == alert.id
    # current_alert_status must not write to the database
    assert alerts_repo.get(db_session, alert.id).last_triggered_at is None


def test_alert_triggers_at_exactly_the_target_price(db_session):
    _, variant = _perfume_and_variant(db_session)
    store = _store(db_session)
    _add_offer(db_session, store=store, variant=variant, price=Decimal("750.00"), availability=Availability.IN_STOCK)
    alerts_repo.create(db_session, perfume_variant_id=variant.id, target_price=Decimal("750.00"), currency="RON")
    db_session.refresh(variant)

    triggered = evaluate_variant_alerts(db_session, variant)

    assert len(triggered) == 1
