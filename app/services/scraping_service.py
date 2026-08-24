"""Orchestrates price-checking: connects scrapers, exclusion filtering,
normalization, matching, and persistence.

See instructions.md sections 67-69 for the expected "Check prices" /
"Check all perfumes" behavior. One failing store must never cancel results
from other stores or other perfumes (section 43) - every store call is
isolated in its own try/except, and results already saved for successful
stores are never rolled back because of a later failure.

Stores are checked sequentially for now (there is currently only one).
Each store call is already independent and awaitable on its own, so
switching to concurrent `asyncio.gather` per perfume is a local change
here if/when a second store is added - no restructuring needed elsewhere.
"""

import logging
from decimal import Decimal

from sqlalchemy.orm import Session

from app.database.models import (
    Availability,
    Perfume,
    PerfumeVariant,
    RunStatus,
    RunType,
    ScrapeResultStatus,
    Store,
)
from app.database.repositories import perfumes as perfumes_repo
from app.database.repositories import prices as prices_repo
from app.database.repositories import scrape_runs as scrape_runs_repo
from app.database.repositories import store_products as store_products_repo
from app.database.repositories import stores as stores_repo
from app.database.repositories import variants as variants_repo
from app.normalization.concentration import extract_concentration
from app.normalization.exclusions import check_exclusion
from app.normalization.volume import extract_volume_ml
from app.schemas.scraping import ScrapedOffer
from app.scrapers import stores as _store_scrapers  # noqa: F401 - side effect: registers store scrapers
from app.scrapers.exceptions import StoreUnavailable
from app.scrapers.registry import get_scraper_class
from app.services import alert_service
from app.services.matching_service import MatchCandidate, resolve_variant, validate_candidate

logger = logging.getLogger(__name__)


async def check_perfume(db: Session, perfume: Perfume, stores: list[Store]) -> None:
    """Check one monitored perfume against the given (enabled) stores."""
    run = scrape_runs_repo.start_run(db, run_type=RunType.SINGLE, perfume_count=1, store_count=len(stores))

    had_errors = False
    for store in stores:
        if not await _check_perfume_at_store(db, run.id, perfume, store):
            had_errors = True

    perfumes_repo.mark_checked(db, perfume)
    _evaluate_alerts_for_perfume(db, perfume)
    scrape_runs_repo.finish_run(
        db, run, status=RunStatus.COMPLETED_WITH_ERRORS if had_errors else RunStatus.COMPLETED
    )


async def check_all_perfumes(db: Session, perfumes: list[Perfume], stores: list[Store]) -> None:
    """Check every monitored perfume against the given (enabled) stores."""
    run = scrape_runs_repo.start_run(
        db, run_type=RunType.ALL, perfume_count=len(perfumes), store_count=len(stores)
    )

    had_errors = False
    for perfume in perfumes:
        for store in stores:
            if not await _check_perfume_at_store(db, run.id, perfume, store):
                had_errors = True
        perfumes_repo.mark_checked(db, perfume)
        _evaluate_alerts_for_perfume(db, perfume)

    scrape_runs_repo.finish_run(
        db, run, status=RunStatus.COMPLETED_WITH_ERRORS if had_errors else RunStatus.COMPLETED
    )


def _evaluate_alerts_for_perfume(db: Session, perfume: Perfume) -> None:
    for variant in variants_repo.list_for_perfume(db, perfume.id):
        alert_service.evaluate_variant_alerts(db, variant)


async def _check_perfume_at_store(db: Session, scrape_run_id: int, perfume: Perfume, store: Store) -> bool:
    """Returns True if the store was queried successfully (found or not),
    False if the store call itself failed."""
    scraper_cls = get_scraper_class(store.scraper_identifier)
    if scraper_cls is None:
        message = f"No scraper registered for '{store.scraper_identifier}'"
        logger.error("%s: %s", store.slug, message)
        stores_repo.record_error(db, store, error_message=message)
        scrape_runs_repo.add_result(
            db,
            scrape_run_id=scrape_run_id,
            perfume_id=perfume.id,
            store_id=store.id,
            status=ScrapeResultStatus.SCRAPING_ERROR,
            error_message=message,
        )
        return False

    try:
        async with scraper_cls() as scraper:
            offers = await scraper.discover_offers(perfume.brand, perfume.name)
    except StoreUnavailable as exc:
        logger.warning("%s: store unavailable for '%s': %s", store.slug, perfume.name, exc)
        stores_repo.record_error(db, store, error_message=str(exc))
        scrape_runs_repo.add_result(
            db,
            scrape_run_id=scrape_run_id,
            perfume_id=perfume.id,
            store_id=store.id,
            status=ScrapeResultStatus.STORE_UNAVAILABLE,
            error_message=str(exc),
        )
        return False
    except Exception as exc:  # noqa: BLE001 - isolate store failures per section 43
        logger.exception("%s: scraping error for '%s'", store.slug, perfume.name)
        stores_repo.record_error(db, store, error_message=str(exc))
        scrape_runs_repo.add_result(
            db,
            scrape_run_id=scrape_run_id,
            perfume_id=perfume.id,
            store_id=store.id,
            status=ScrapeResultStatus.SCRAPING_ERROR,
            error_message=str(exc),
        )
        return False

    offers_saved = 0
    any_in_stock = False
    touched_variant_ids: set[int] = set()

    for offer in offers:
        variant = _process_offer(db, perfume, store, offer, scrape_run_id)
        if variant is not None:
            offers_saved += 1
            touched_variant_ids.add(variant.id)
            if offer.availability == "in_stock":
                any_in_stock = True

    if any_in_stock:
        status = ScrapeResultStatus.IN_STOCK
    elif offers_saved > 0:
        status = ScrapeResultStatus.OUT_OF_STOCK
    else:
        status = ScrapeResultStatus.NOT_FOUND

    _mark_delisted_products_out_of_stock(db, perfume, store, touched_variant_ids, scrape_run_id)
    stores_repo.record_success(db, store)
    scrape_runs_repo.add_result(
        db,
        scrape_run_id=scrape_run_id,
        perfume_id=perfume.id,
        store_id=store.id,
        status=status,
        offers_found=offers_saved,
    )
    return True


def _mark_delisted_products_out_of_stock(
    db: Session, perfume: Perfume, store: Store, touched_variant_ids: set[int], scrape_run_id: int
) -> None:
    """A successful scrape that no longer lists a previously-known variant
    for this store doesn't necessarily mean it's out of stock at that
    specific combination - it may simply no longer be offered at all
    (discontinued/delisted). Either way, it must stop showing as a stale
    "in stock" offer and must never win the best-price comparison, so it's
    marked out of stock here. Price and product_url are left untouched -
    only availability changes, and only when it actually changes.
    """
    for store_product in store_products_repo.list_for_perfume_and_store(db, perfume.id, store.id):
        if store_product.perfume_variant_id in touched_variant_ids:
            continue
        if store_product.availability != Availability.IN_STOCK:
            continue

        logger.info(
            "%s: '%s' variant %s no longer listed - marking out of stock",
            store.slug, perfume.name, store_product.perfume_variant_id,
        )
        store_products_repo.mark_out_of_stock(db, store_product)
        prices_repo.record_if_changed(
            db,
            store_product_id=store_product.id,
            scrape_run_id=scrape_run_id,
            price=store_product.current_price,
            old_price=store_product.current_old_price,
            currency=store_product.currency,
            discount_percentage=store_product.discount_percentage,
            availability=Availability.OUT_OF_STOCK,
        )


def _process_offer(
    db: Session, perfume: Perfume, store: Store, offer: ScrapedOffer, scrape_run_id: int
) -> PerfumeVariant | None:
    """Validate one scraped offer and, if it's a confident match for an
    exact variant, persist it. Returns the variant if saved, else None.
    """
    if check_exclusion(offer.raw_title) is not None:
        return None

    if offer.price is None:
        return None

    concentration = offer.concentration or extract_concentration(offer.raw_title)
    volume_ml = offer.volume_ml if offer.volume_ml is not None else extract_volume_ml(offer.raw_title)

    candidate = MatchCandidate(
        raw_title=offer.raw_title,
        brand=offer.brand or perfume.brand,
        name=offer.perfume_name or offer.raw_title,
        concentration=concentration,
        volume_ml=volume_ml,
        tester=offer.tester,
    )

    result = validate_candidate(perfume, candidate)
    if not result.is_usable:
        logger.debug(
            "%s: rejected candidate for '%s' (%s): %s",
            store.slug, perfume.name, result.confidence.value, result.reason,
        )
        return None

    variant = resolve_variant(db, perfume, candidate)
    if variant is None:
        return None

    availability = Availability(offer.availability)
    discount_percentage = _compute_discount_percentage(offer.price, offer.old_price)

    store_product = store_products_repo.upsert_offer(
        db,
        store_id=store.id,
        variant_id=variant.id,
        product_url=offer.product_url,
        store_product_identifier=offer.store_product_identifier,
        product_title=offer.raw_title,
        price=offer.price,
        old_price=offer.old_price,
        currency=offer.currency,
        discount_percentage=discount_percentage,
        availability=availability,
    )

    prices_repo.record_if_changed(
        db,
        store_product_id=store_product.id,
        scrape_run_id=scrape_run_id,
        price=offer.price,
        old_price=offer.old_price,
        currency=offer.currency,
        discount_percentage=discount_percentage,
        availability=availability,
    )

    return variant


def _compute_discount_percentage(price: Decimal, old_price: Decimal | None) -> int | None:
    if old_price is None or old_price <= 0 or price >= old_price:
        return None
    return int(round((old_price - price) / old_price * 100))
