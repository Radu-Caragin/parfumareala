"""Tests for scraping_service - orchestrates scraper + exclusion filtering
+ matching + persistence. Uses a fake in-memory scraper registered
temporarily, so these stay fast and deterministic (no real store is hit).
"""

import asyncio
from decimal import Decimal

import pytest

from app.database.models import Availability, RunStatus, Store
from app.database.repositories import perfumes as perfumes_repo
from app.database.repositories import prices as prices_repo
from app.database.repositories import scrape_runs as scrape_runs_repo
from app.database.repositories import store_products as store_products_repo
from app.database.repositories import variants as variants_repo
from app.schemas.scraping import ScrapedOffer
from app.scrapers.base import BaseScraper
from app.scrapers.exceptions import RequestError, StoreUnavailable
from app.scrapers.registry import SCRAPER_REGISTRY
from app.services import scraping_service


class _FakeScraper(BaseScraper):
    store_name = "Fake Store"
    store_slug = "fake-store"
    base_url = "https://fake.test"

    offers: list[ScrapedOffer] = []
    error: Exception | None = None

    async def search_perfume(self, brand, perfume_name):
        return []

    async def fetch_product(self, candidate):
        return None

    async def parse_product(self, raw_product):
        return []

    async def discover_offers(self, brand, perfume_name):
        if self.error is not None:
            raise self.error
        return self.offers


@pytest.fixture()
def fake_store(db_session):
    SCRAPER_REGISTRY["fake-store"] = _FakeScraper
    store = Store(
        name="Fake Store", slug="fake-store", base_url="https://fake.test",
        enabled=True, scraper_identifier="fake-store",
    )
    db_session.add(store)
    db_session.commit()
    db_session.refresh(store)

    yield store

    SCRAPER_REGISTRY.pop("fake-store", None)
    _FakeScraper.offers = []
    _FakeScraper.error = None


def _perfume(db_session):
    return perfumes_repo.create(
        db_session, brand="Xerjoff", name="Erba Gold", normalized_brand="xerjoff", normalized_name="erba gold"
    )


def _offer(**overrides) -> ScrapedOffer:
    defaults = dict(
        store_slug="fake-store",
        raw_title="Xerjoff Erba Gold Eau de Parfum 100 ml",
        product_url="https://fake.test/erba-gold",
        brand="Xerjoff",
        perfume_name="Erba Gold",
        concentration="EDP",
        volume_ml=100,
        tester=False,
        price=Decimal("799.00"),
        old_price=None,
        currency="RON",
        availability="in_stock",
    )
    defaults.update(overrides)
    return ScrapedOffer(**defaults)


def test_check_perfume_saves_matching_offer(db_session, fake_store):
    perfume = _perfume(db_session)
    _FakeScraper.offers = [_offer()]

    asyncio.run(scraping_service.check_perfume(db_session, perfume, [fake_store]))

    variants = variants_repo.list_for_perfume(db_session, perfume.id)
    assert len(variants) == 1
    assert variants[0].concentration == "EDP"
    assert variants[0].volume_ml == 100

    store_products = store_products_repo.list_for_variant(db_session, variants[0].id)
    assert len(store_products) == 1
    assert store_products[0].current_price == Decimal("799.00")
    assert store_products[0].availability == Availability.IN_STOCK

    refreshed_perfume = perfumes_repo.get(db_session, perfume.id)
    assert refreshed_perfume.last_checked_at is not None


def test_check_perfume_records_in_stock_result(db_session, fake_store):
    perfume = _perfume(db_session)
    _FakeScraper.offers = [_offer()]

    asyncio.run(scraping_service.check_perfume(db_session, perfume, [fake_store]))

    results = scrape_runs_repo.get_latest_results_for_perfume(db_session, perfume.id)
    assert len(results) == 1
    assert results[0].status.value == "in_stock"
    assert results[0].offers_found == 1


def test_check_perfume_with_no_offers_is_not_found(db_session, fake_store):
    perfume = _perfume(db_session)
    _FakeScraper.offers = []

    asyncio.run(scraping_service.check_perfume(db_session, perfume, [fake_store]))

    results = scrape_runs_repo.get_latest_results_for_perfume(db_session, perfume.id)
    assert results[0].status.value == "not_found"
    assert variants_repo.list_for_perfume(db_session, perfume.id) == []


def test_check_perfume_rejects_wrong_brand(db_session, fake_store):
    perfume = _perfume(db_session)
    _FakeScraper.offers = [_offer(brand="Dior", raw_title="Dior Sauvage EDP 100 ml")]

    asyncio.run(scraping_service.check_perfume(db_session, perfume, [fake_store]))

    assert variants_repo.list_for_perfume(db_session, perfume.id) == []
    results = scrape_runs_repo.get_latest_results_for_perfume(db_session, perfume.id)
    assert results[0].status.value == "not_found"


def test_check_perfume_rejects_excluded_product(db_session, fake_store):
    perfume = _perfume(db_session)
    _FakeScraper.offers = [_offer(raw_title="Xerjoff Erba Gold Gift Set EDP 100 ml")]

    asyncio.run(scraping_service.check_perfume(db_session, perfume, [fake_store]))

    assert variants_repo.list_for_perfume(db_session, perfume.id) == []


def test_check_perfume_out_of_stock_offer_is_saved_with_out_of_stock_status(db_session, fake_store):
    perfume = _perfume(db_session)
    _FakeScraper.offers = [_offer(availability="out_of_stock")]

    asyncio.run(scraping_service.check_perfume(db_session, perfume, [fake_store]))

    variants = variants_repo.list_for_perfume(db_session, perfume.id)
    store_products = store_products_repo.list_for_variant(db_session, variants[0].id)
    assert store_products[0].availability == Availability.OUT_OF_STOCK

    results = scrape_runs_repo.get_latest_results_for_perfume(db_session, perfume.id)
    assert results[0].status.value == "out_of_stock"


def test_check_perfume_scraping_error_isolated(db_session, fake_store):
    perfume = _perfume(db_session)
    _FakeScraper.error = RequestError("boom")

    asyncio.run(scraping_service.check_perfume(db_session, perfume, [fake_store]))

    results = scrape_runs_repo.get_latest_results_for_perfume(db_session, perfume.id)
    assert results[0].status.value == "scraping_error"
    assert "boom" in results[0].error_message

    refreshed_store = db_session.get(Store, fake_store.id)
    assert refreshed_store.last_error is not None


def test_check_perfume_store_unavailable(db_session, fake_store):
    perfume = _perfume(db_session)
    _FakeScraper.error = StoreUnavailable("site is down")

    asyncio.run(scraping_service.check_perfume(db_session, perfume, [fake_store]))

    results = scrape_runs_repo.get_latest_results_for_perfume(db_session, perfume.id)
    assert results[0].status.value == "store_unavailable"


def test_check_perfume_run_status_completed_without_errors(db_session, fake_store):
    perfume = _perfume(db_session)
    _FakeScraper.offers = [_offer()]

    asyncio.run(scraping_service.check_perfume(db_session, perfume, [fake_store]))

    run = scrape_runs_repo.list_for_perfume(db_session, perfume.id)[0].scrape_run
    assert run.status == RunStatus.COMPLETED


def test_check_perfume_run_status_completed_with_errors(db_session, fake_store):
    perfume = _perfume(db_session)
    _FakeScraper.error = RequestError("boom")

    asyncio.run(scraping_service.check_perfume(db_session, perfume, [fake_store]))

    run = scrape_runs_repo.list_for_perfume(db_session, perfume.id)[0].scrape_run
    assert run.status == RunStatus.COMPLETED_WITH_ERRORS


def test_price_history_only_recorded_on_change(db_session, fake_store):
    perfume = _perfume(db_session)
    _FakeScraper.offers = [_offer(price=Decimal("799.00"))]
    asyncio.run(scraping_service.check_perfume(db_session, perfume, [fake_store]))

    _FakeScraper.offers = [_offer(price=Decimal("799.00"))]
    asyncio.run(scraping_service.check_perfume(db_session, perfume, [fake_store]))

    variants = variants_repo.list_for_perfume(db_session, perfume.id)
    store_products = store_products_repo.list_for_variant(db_session, variants[0].id)
    history = prices_repo.list_for_store_product(db_session, store_products[0].id)
    assert len(history) == 1  # unchanged price -> no second row

    _FakeScraper.offers = [_offer(price=Decimal("749.00"))]
    asyncio.run(scraping_service.check_perfume(db_session, perfume, [fake_store]))

    history = prices_repo.list_for_store_product(db_session, store_products[0].id)
    assert len(history) == 2  # price dropped -> new row


def test_check_all_perfumes_updates_every_perfume(db_session, fake_store):
    perfume_a = _perfume(db_session)
    perfume_b = perfumes_repo.create(
        db_session, brand="Dior", name="Sauvage", normalized_brand="dior", normalized_name="sauvage"
    )
    _FakeScraper.offers = [_offer()]  # only matches perfume_a's brand/name

    asyncio.run(scraping_service.check_all_perfumes(db_session, [perfume_a, perfume_b], [fake_store]))

    assert perfumes_repo.get(db_session, perfume_a.id).last_checked_at is not None
    assert perfumes_repo.get(db_session, perfume_b.id).last_checked_at is not None
    assert len(variants_repo.list_for_perfume(db_session, perfume_a.id)) == 1
    assert len(variants_repo.list_for_perfume(db_session, perfume_b.id)) == 0


def test_delisted_variant_marked_out_of_stock_on_next_successful_check(db_session, fake_store):
    # First check: two variants found (100ml and 50ml), both in stock.
    perfume = _perfume(db_session)
    _FakeScraper.offers = [
        _offer(volume_ml=100, product_url="https://fake.test/100ml"),
        _offer(volume_ml=50, product_url="https://fake.test/50ml", raw_title="Xerjoff Erba Gold Eau de Parfum 50 ml"),
    ]
    asyncio.run(scraping_service.check_perfume(db_session, perfume, [fake_store]))

    variants = {v.volume_ml: v for v in variants_repo.list_for_perfume(db_session, perfume.id)}
    assert len(variants) == 2
    sp_100 = store_products_repo.list_for_variant(db_session, variants[100].id)[0]
    sp_50 = store_products_repo.list_for_variant(db_session, variants[50].id)[0]
    assert sp_100.availability == Availability.IN_STOCK
    assert sp_50.availability == Availability.IN_STOCK

    # Second check: store no longer lists the 50ml variant at all (delisted,
    # not just out of stock - it's simply absent from the fresh results).
    _FakeScraper.offers = [_offer(volume_ml=100, product_url="https://fake.test/100ml")]
    asyncio.run(scraping_service.check_perfume(db_session, perfume, [fake_store]))

    refreshed_100 = store_products_repo.get(db_session, sp_100.id)
    refreshed_50 = store_products_repo.get(db_session, sp_50.id)
    assert refreshed_100.availability == Availability.IN_STOCK  # still found - untouched
    assert refreshed_50.availability == Availability.OUT_OF_STOCK  # no longer found - marked stale

    # The staleness flip is itself a change, so it must appear in history.
    history = prices_repo.list_for_store_product(db_session, sp_50.id)
    assert len(history) == 2
    assert history[0].availability == Availability.OUT_OF_STOCK


def test_delisted_variant_from_other_store_is_not_touched(db_session, fake_store):
    # A store's scrape must only ever mark ITS OWN store_products as
    # delisted, never another store's rows for the same perfume/variant.
    perfume = _perfume(db_session)
    other_store = Store(
        name="Other Store", slug="other-store", base_url="https://other.test",
        enabled=True, scraper_identifier="other-store",
    )
    db_session.add(other_store)
    db_session.commit()
    db_session.refresh(other_store)

    _FakeScraper.offers = [_offer()]
    asyncio.run(scraping_service.check_perfume(db_session, perfume, [fake_store]))
    variant = variants_repo.list_for_perfume(db_session, perfume.id)[0]

    other_sp = store_products_repo.upsert_offer(
        db_session, store_id=other_store.id, variant_id=variant.id,
        product_url="https://other.test/x", store_product_identifier=None, product_title="x",
        price=Decimal("700.00"), old_price=None, currency="RON",
        discount_percentage=None, availability=Availability.IN_STOCK,
    )

    # Re-check only fake_store; other_store's row must remain untouched.
    _FakeScraper.offers = []
    asyncio.run(scraping_service.check_perfume(db_session, perfume, [fake_store]))

    assert store_products_repo.get(db_session, other_sp.id).availability == Availability.IN_STOCK
