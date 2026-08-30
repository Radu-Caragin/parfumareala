"""Tests for the database repository layer."""

from decimal import Decimal

from app.database.models import Availability, RunType
from app.database.repositories import alerts as alerts_repo
from app.database.repositories import perfumes as perfumes_repo
from app.database.repositories import prices as prices_repo
from app.database.repositories import scrape_runs as scrape_runs_repo
from app.database.repositories import store_products as store_products_repo
from app.database.repositories import stores as stores_repo
from app.database.repositories import variants as variants_repo
from app.database.seed import seed_initial_stores


def test_seed_creates_known_stores(db_session):
    seed_initial_stores(db_session)

    stores = stores_repo.list_all(db_session)
    slugs = {s.slug for s in stores}

    assert slugs == {"fragranza", "parfimo", "esentedelux", "vivantis", "notino", "parfumat", "brasty", "koku"}
    assert all(s.enabled is True for s in stores)


def test_seed_is_idempotent(db_session):
    seed_initial_stores(db_session)
    seed_initial_stores(db_session)

    assert len(stores_repo.list_all(db_session)) == 8


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


def test_list_for_perfume_orders_by_volume_descending_regardless_of_concentration(db_session):
    perfume = perfumes_repo.create(
        db_session, brand="Xerjoff", name="Erba Gold", normalized_brand="xerjoff", normalized_name="erba gold"
    )
    # Created out of order and interleaved across concentrations on
    # purpose - a smaller EDT must never sort ahead of a larger EDP just
    # because "EDP" < "EDT" alphabetically.
    variants_repo.get_or_create(db_session, perfume_id=perfume.id, concentration="EDT", volume_ml=50, tester=False)
    variants_repo.get_or_create(db_session, perfume_id=perfume.id, concentration="EDP", volume_ml=100, tester=False)
    variants_repo.get_or_create(db_session, perfume_id=perfume.id, concentration="EDT", volume_ml=100, tester=False)
    variants_repo.get_or_create(db_session, perfume_id=perfume.id, concentration="EDP", volume_ml=30, tester=False)

    ordered = variants_repo.list_for_perfume(db_session, perfume.id)

    assert [(v.volume_ml, v.concentration) for v in ordered] == [
        (100, "EDP"),
        (100, "EDT"),
        (50, "EDT"),
        (30, "EDP"),
    ]


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


def test_list_price_changes_for_run_reports_delta_and_ignores_first_ever_price(db_session):
    seed_initial_stores(db_session)
    store = stores_repo.get_by_slug(db_session, "fragranza")
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

    run_1 = scrape_runs_repo.start_run(db_session, run_type=RunType.ALL, perfume_count=1, store_count=1)
    prices_repo.record_if_changed(
        db_session, store_product_id=store_product.id, scrape_run_id=run_1.id,
        price=Decimal("799.00"), old_price=None, currency="RON",
        discount_percentage=None, availability=Availability.IN_STOCK,
    )
    # First-ever observation - nothing to compare it against, so it must
    # never show up as a "change" even though it belongs to a real run.
    assert prices_repo.list_price_changes_for_run(db_session, run_1.id) == []

    run_2 = scrape_runs_repo.start_run(db_session, run_type=RunType.ALL, perfume_count=1, store_count=1)
    prices_repo.record_if_changed(
        db_session, store_product_id=store_product.id, scrape_run_id=run_2.id,
        price=Decimal("749.00"), old_price=None, currency="RON",
        discount_percentage=None, availability=Availability.IN_STOCK,
    )

    changes = prices_repo.list_price_changes_for_run(db_session, run_2.id)
    assert len(changes) == 1
    assert changes[0].previous_price == Decimal("799.00")
    assert changes[0].price == Decimal("749.00")
    assert changes[0].delta == Decimal("-50.00")

    run_3 = scrape_runs_repo.start_run(db_session, run_type=RunType.ALL, perfume_count=1, store_count=1)
    prices_repo.record_if_changed(
        db_session, store_product_id=store_product.id, scrape_run_id=run_3.id,
        price=Decimal("749.00"), old_price=None, currency="RON",
        discount_percentage=None, availability=Availability.OUT_OF_STOCK,
    )
    # Price unchanged, only availability flipped - not a price change.
    assert prices_repo.list_price_changes_for_run(db_session, run_3.id) == []


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
