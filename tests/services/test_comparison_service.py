"""Tests for comparison_service: best price selection per variant.

instructions.md section 36: only in-stock offers may win the "best price"
comparison, even if an out-of-stock offer is cheaper. Variants are never
mixed - comparison always happens within a single PerfumeVariant.
"""

from decimal import Decimal

from app.database.models import Availability, Store
from app.database.repositories import perfumes as perfumes_repo
from app.database.repositories import store_products as store_products_repo
from app.database.repositories import variants as variants_repo
from app.services.comparison_service import compare_perfume, compare_variant


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
        db_session,
        store_id=store.id,
        variant_id=variant.id,
        product_url=f"https://{store.slug}.test/product",
        store_product_identifier=None,
        product_title="Xerjoff Erba Gold EDP 100 ml",
        price=price,
        old_price=None,
        currency="RON",
        discount_percentage=None,
        availability=availability,
    )


def test_best_offer_is_cheapest_in_stock(db_session):
    _, variant = _perfume_and_variant(db_session)
    store_a = _store(db_session, "store-a", "Store A")
    store_b = _store(db_session, "store-b", "Store B")

    _add_offer(db_session, store=store_a, variant=variant, price=Decimal("850.00"), availability=Availability.IN_STOCK)
    _add_offer(db_session, store=store_b, variant=variant, price=Decimal("799.00"), availability=Availability.IN_STOCK)
    db_session.refresh(variant)

    comparison = compare_variant(variant)

    assert comparison.best_offer is not None
    assert comparison.best_offer.store_id == store_b.id
    assert comparison.best_offer.current_price == Decimal("799.00")


def test_out_of_stock_offer_never_wins_even_if_cheaper(db_session):
    _, variant = _perfume_and_variant(db_session)
    store_a = _store(db_session, "store-a", "Store A")
    store_b = _store(db_session, "store-b", "Store B")

    _add_offer(db_session, store=store_a, variant=variant, price=Decimal("500.00"), availability=Availability.OUT_OF_STOCK)
    _add_offer(db_session, store=store_b, variant=variant, price=Decimal("799.00"), availability=Availability.IN_STOCK)
    db_session.refresh(variant)

    comparison = compare_variant(variant)

    assert comparison.best_offer.store_id == store_b.id
    assert comparison.best_offer.current_price == Decimal("799.00")


def test_no_best_offer_when_all_out_of_stock(db_session):
    _, variant = _perfume_and_variant(db_session)
    store_a = _store(db_session)

    _add_offer(db_session, store=store_a, variant=variant, price=Decimal("500.00"), availability=Availability.OUT_OF_STOCK)
    db_session.refresh(variant)

    comparison = compare_variant(variant)

    assert comparison.best_offer is None


def test_no_best_offer_when_no_stores_carry_it(db_session):
    _, variant = _perfume_and_variant(db_session)

    comparison = compare_variant(variant)

    assert comparison.best_offer is None
    assert comparison.store_products == []


def test_compare_perfume_returns_one_comparison_per_variant(db_session):
    perfume, variant = _perfume_and_variant(db_session)
    variant2 = variants_repo.get_or_create(
        db_session, perfume_id=perfume.id, concentration="EDP", volume_ml=50, tester=False
    )

    comparisons = compare_perfume(variants_repo.list_for_perfume(db_session, perfume.id))

    assert len(comparisons) == 2
    assert {c.variant.id for c in comparisons} == {variant.id, variant2.id}


def test_comparisons_never_mix_variants(db_session):
    perfume, variant_100 = _perfume_and_variant(db_session)
    variant_50 = variants_repo.get_or_create(
        db_session, perfume_id=perfume.id, concentration="EDP", volume_ml=50, tester=False
    )
    store_a = _store(db_session)

    _add_offer(db_session, store=store_a, variant=variant_100, price=Decimal("900.00"), availability=Availability.IN_STOCK)
    _add_offer(db_session, store=store_a, variant=variant_50, price=Decimal("500.00"), availability=Availability.IN_STOCK)
    db_session.refresh(variant_100)
    db_session.refresh(variant_50)

    comparison_100 = compare_variant(variant_100)
    comparison_50 = compare_variant(variant_50)

    assert comparison_100.best_offer.current_price == Decimal("900.00")
    assert comparison_50.best_offer.current_price == Decimal("500.00")
