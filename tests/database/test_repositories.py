"""Tests for the database repository layer."""

from decimal import Decimal

from app.database.models import Availability
from app.database.repositories import alerts as alerts_repo
from app.database.repositories import perfumes as perfumes_repo
from app.database.repositories import prices as prices_repo
from app.database.repositories import store_products as store_products_repo
from app.database.repositories import stores as stores_repo
from app.database.repositories import variants as variants_repo
from app.database.seed import seed_initial_stores


def test_seed_creates_known_stores(db_session):
    seed_initial_stores(db_session)

    stores = stores_repo.list_all(db_session)
    slugs = {s.slug for s in stores}

    assert slugs == {"fragranza", "parfimo", "esentedelux"}
    assert all(s.enabled is True for s in stores)


def test_seed_is_idempotent(db_session):
    seed_initial_stores(db_session)
    seed_initial_stores(db_session)

    assert len(stores_repo.list_all(db_session)) == 3


def test_create_perfume_and_variant(db_session):
    perfume = perfumes_repo.create(
        db_session, brand="Xerjoff", name="Erba Gold", normalized_brand="xerjoff", normalized_name="erba gold"
    )

    variant = variants_repo.get_or_create(
        db_session, perfume_id=perfume.id, concentration="EDP", volume_ml=100, tester=False
    )
    same_variant = variants_repo.get_or_create(
        db_session, perfume_id=perfume.id, concentration="EDP", volume_ml=100, tester=False
    )

    assert variant.perfume_id == perfume.id
    assert same_variant.id == variant.id  # not duplicated


def test_variant_identity_is_distinct(db_session):
    perfume = perfumes_repo.create(
        db_session, brand="Xerjoff", name="Erba Gold", normalized_brand="xerjoff", normalized_name="erba gold"
    )

    v_normal = variants_repo.get_or_create(
        db_session, perfume_id=perfume.id, concentration="EDP", volume_ml=100, tester=False
    )
    v_tester = variants_repo.get_or_create(
        db_session, perfume_id=perfume.id, concentration="EDP", volume_ml=100, tester=True
    )
    v_smaller = variants_repo.get_or_create(
        db_session, perfume_id=perfume.id, concentration="EDP", volume_ml=50, tester=False
    )
    v_edt = variants_repo.get_or_create(
        db_session, perfume_id=perfume.id, concentration="EDT", volume_ml=100, tester=False
    )

    ids = {v_normal.id, v_tester.id, v_smaller.id, v_edt.id}
    assert len(ids) == 4  # concentration, volume and tester status must never collapse together


def test_price_history_only_recorded_on_change(db_session):
    seed_initial_stores(db_session)
    store = stores_repo.get_by_slug(db_session, "fragranza")
    perfume = perfumes_repo.create(
        db_session, brand="Xerjoff", name="Erba Gold", normalized_brand="xerjoff", normalized_name="erba gold"
    )
    variant = variants_repo.get_or_create(
        db_session, perfume_id=perfume.id, concentration="EDP", volume_ml=100, tester=False
    )

    store_product = store_products_repo.upsert_offer(
        db_session,
        store_id=store.id,
        variant_id=variant.id,
        product_url="https://fragranza.ro/example",
        store_product_identifier=None,
        product_title="Xerjoff Erba Gold EDP 100ml",
        price=Decimal("799.00"),
        old_price=Decimal("899.00"),
        currency="RON",
        discount_percentage=11,
        availability=Availability.IN_STOCK,
    )

    first = prices_repo.record_if_changed(
        db_session,
        store_product_id=store_product.id,
        scrape_run_id=None,
        price=Decimal("799.00"),
        old_price=Decimal("899.00"),
        currency="RON",
        discount_percentage=11,
        availability=Availability.IN_STOCK,
    )
    assert first is not None

    unchanged = prices_repo.record_if_changed(
        db_session,
        store_product_id=store_product.id,
        scrape_run_id=None,
        price=Decimal("799.00"),
        old_price=Decimal("899.00"),
        currency="RON",
        discount_percentage=11,
        availability=Availability.IN_STOCK,
    )
    assert unchanged is None  # same price/availability -> no new row

    dropped = prices_repo.record_if_changed(
        db_session,
        store_product_id=store_product.id,
        scrape_run_id=None,
        price=Decimal("749.00"),
        old_price=Decimal("899.00"),
        currency="RON",
        discount_percentage=17,
        availability=Availability.IN_STOCK,
    )
    assert dropped is not None

    history = prices_repo.list_for_store_product(db_session, store_product.id)
    assert len(history) == 2


def test_alert_lifecycle(db_session):
    perfume = perfumes_repo.create(
        db_session, brand="Xerjoff", name="Erba Gold", normalized_brand="xerjoff", normalized_name="erba gold"
    )
    variant = variants_repo.get_or_create(
        db_session, perfume_id=perfume.id, concentration="EDP", volume_ml=100, tester=False
    )

    alert = alerts_repo.create(db_session, perfume_variant_id=variant.id, target_price=Decimal("750.00"), currency="RON")

    assert alert in alerts_repo.list_enabled(db_session)

    alerts_repo.mark_triggered(db_session, alert, price=Decimal("729.00"))
    assert alert.last_triggered_price == Decimal("729.00")

    alerts_repo.set_enabled(db_session, alert, False)
    assert alert not in alerts_repo.list_enabled(db_session)
