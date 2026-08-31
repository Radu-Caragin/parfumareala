"""Tests for price_chart_service - the price-history chart's coordinate
math and the "real discount" comparison, both built from real, persisted
PriceHistory rows (via prices_repo.record_if_changed, same as production)
rather than hand-built in-memory objects, so the .price_history
relationship behaves exactly as it does for real data.
"""

from decimal import Decimal

from app.database.models import Availability, Store
from app.database.repositories import perfumes as perfumes_repo
from app.database.repositories import prices as prices_repo
from app.database.repositories import store_products as store_products_repo
from app.database.repositories import variants as variants_repo
from app.services.price_chart_service import build_variant_price_chart, real_price_drop


def _store(db_session, slug="fragranza"):
    store = Store(name="Fragranza.ro", slug=slug, base_url="https://fragranza.ro", enabled=True, scraper_identifier=slug)
    db_session.add(store)
    db_session.commit()
    return store


def _store_product(db_session, store, *, price=Decimal("799.00")):
    perfume = perfumes_repo.create(
        db_session, brand="Xerjoff", name="Erba Gold", normalized_brand="xerjoff", normalized_name="erba gold"
    )
    variant = variants_repo.get_or_create(
        db_session, perfume_id=perfume.id, concentration="EDP", volume_ml=100, tester=False
    )
    return store_products_repo.upsert_offer(
        db_session, store_id=store.id, variant_id=variant.id,
        product_url="https://fragranza.ro/x", store_product_identifier=None, product_title="x",
        price=price, old_price=None, currency="RON",
        discount_percentage=None, availability=Availability.IN_STOCK,
    )


def _record(db_session, store_product, price, *, availability=Availability.IN_STOCK):
    prices_repo.record_if_changed(
        db_session, store_product_id=store_product.id, scrape_run_id=None,
        price=price, old_price=None, currency="RON", discount_percentage=None, availability=availability,
    )


def test_build_variant_price_chart_empty_when_no_history(db_session):
    store = _store(db_session)
    sp = _store_product(db_session, store)

    chart = build_variant_price_chart([sp])

    assert chart.has_data is False
    assert chart.series == []


def test_build_variant_price_chart_single_point_does_not_crash(db_session):
    store = _store(db_session)
    sp = _store_product(db_session, store, price=Decimal("799.00"))
    _record(db_session, sp, Decimal("799.00"))
    db_session.refresh(sp)

    chart = build_variant_price_chart([sp])

    assert chart.has_data is True
    assert len(chart.series) == 1
    assert len(chart.series[0].points) == 1
    assert chart.min_price == Decimal("799.00")
    assert chart.max_price == Decimal("799.00")
    assert chart.avg_price == Decimal("799.00")


def test_build_variant_price_chart_computes_min_max_avg_across_all_stores(db_session):
    store_a = _store(db_session, slug="fragranza")
    store_b = _store(db_session, slug="parfimo")
    sp_a = _store_product(db_session, store_a, price=Decimal("799.00"))
    sp_b = store_products_repo.upsert_offer(
        db_session, store_id=store_b.id, variant_id=sp_a.perfume_variant_id,
        product_url="https://parfimo.ro/x", store_product_identifier=None, product_title="x",
        price=Decimal("699.00"), old_price=None, currency="RON",
        discount_percentage=None, availability=Availability.IN_STOCK,
    )
    _record(db_session, sp_a, Decimal("799.00"))
    _record(db_session, sp_a, Decimal("749.00"))
    _record(db_session, sp_b, Decimal("699.00"))
    db_session.refresh(sp_a)
    db_session.refresh(sp_b)

    chart = build_variant_price_chart([sp_a, sp_b])

    assert chart.has_data is True
    assert len(chart.series) == 2
    assert chart.min_price == Decimal("699.00")
    assert chart.max_price == Decimal("799.00")
    assert chart.avg_price == Decimal("749.00")  # (799 + 749 + 699) / 3


def test_build_variant_price_chart_marks_each_stores_own_low_point(db_session):
    store = _store(db_session)
    sp = _store_product(db_session, store, price=Decimal("799.00"))
    _record(db_session, sp, Decimal("799.00"))
    _record(db_session, sp, Decimal("699.00"))
    _record(db_session, sp, Decimal("749.00"))
    db_session.refresh(sp)

    chart = build_variant_price_chart([sp])

    low_flags = {p.price: p.is_store_low for p in chart.series[0].points}
    assert low_flags[Decimal("699.00")] is True
    assert low_flags[Decimal("799.00")] is False
    assert low_flags[Decimal("749.00")] is False


def test_build_variant_price_chart_handles_all_identical_prices(db_session):
    # Same price recorded across an availability flip - price_span is
    # zero, must not raise ZeroDivisionError.
    store = _store(db_session)
    sp = _store_product(db_session, store, price=Decimal("799.00"))
    _record(db_session, sp, Decimal("799.00"))
    _record(db_session, sp, Decimal("799.00"), availability=Availability.OUT_OF_STOCK)
    db_session.refresh(sp)

    chart = build_variant_price_chart([sp])

    assert chart.has_data is True
    assert chart.min_price == chart.max_price == Decimal("799.00")


def test_real_price_drop_none_with_no_history(db_session):
    store = _store(db_session)
    sp = _store_product(db_session, store)

    assert real_price_drop(sp) is None


def test_real_price_drop_none_with_only_one_recorded_price(db_session):
    store = _store(db_session)
    sp = _store_product(db_session, store, price=Decimal("799.00"))
    _record(db_session, sp, Decimal("799.00"))
    db_session.refresh(sp)

    assert real_price_drop(sp) is None


def test_real_price_drop_negative_when_price_decreased(db_session):
    store = _store(db_session)
    sp = _store_product(db_session, store, price=Decimal("799.00"))
    _record(db_session, sp, Decimal("799.00"))
    _record(db_session, sp, Decimal("749.00"))
    db_session.refresh(sp)

    assert real_price_drop(sp) == Decimal("-50.00")


def test_real_price_drop_none_when_price_increased(db_session):
    store = _store(db_session)
    sp = _store_product(db_session, store, price=Decimal("699.00"))
    _record(db_session, sp, Decimal("699.00"))
    _record(db_session, sp, Decimal("749.00"))
    db_session.refresh(sp)

    assert real_price_drop(sp) is None
