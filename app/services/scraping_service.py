"""Orchestrates price-checking: connects scrapers, exclusion filtering,
normalization, matching, and persistence.

See instructions.md sections 67-69 for the expected "Check prices" /
"Check all perfumes" behavior. One failing store must never cancel results
from other stores or other perfumes (section 43) - every store call is
isolated in its own try/except, and results already saved for successful
stores are never rolled back because of a later failure.

Per perfume, every store's *scraping* (the slow, network-bound part -
discover_offers) runs concurrently via asyncio.gather - see
_scrape_store_offers. Every store's *persistence* (writing offers to the
DB) then happens afterward, sequentially - see _persist_scrape_result -
because a single SQLAlchemy Session is not safe for concurrent use from
multiple coroutines at once. This split is why _check_perfume_at_store
from earlier became two functions: one that only awaits network I/O and
returns a plain result object, one that only touches the DB and never
awaits anything.

check_all_perfumes goes a level further and gathers perfumes themselves
too, not just stores within one perfume - see its docstring for why that
stays safe on the same shared Session (short version: nothing that
touches `db` ever awaits, so asyncio never actually interleaves two
perfumes' database work). Each pooled store scraper's own request lock
(app/scrapers/pool.py) is what keeps that store's real HTTP requests
serialized regardless of how many perfumes are asking at once.

_scrape_store_offers gets its scraper from app.scrapers.pool instead of
constructing (and, on exit, tearing down) a fresh one for every single
(perfume, store) pair - a pooled instance's connection and any cache it
builds (a brand directory, a sitemap) live for the app process's whole
lifetime, reused across every check against that store.

An optional progress_key threads through check_perfume/
check_all_perfumes/_check_perfume_against_stores so a caller (a route
running this in a background task) can have per-store "checking.../done"
state show up in app.services.progress for the UI to poll - see
routes/dashboard.py and routes/perfumes.py. It's optional and defaults to
None (no tracking) specifically so every existing call site/test that
doesn't care about live progress needs no changes.
"""

import asyncio
import logging
from dataclasses import dataclass
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
from app.scrapers import pool as scraper_pool
from app.scrapers import stores as _store_scrapers  # noqa: F401 - side effect: registers store scrapers
from app.scrapers.exceptions import StoreUnavailable
from app.services import alert_service
from app.services import progress as progress_service
from app.services.matching_service import MatchCandidate, resolve_variant, validate_candidate

logger = logging.getLogger(__name__)


async def check_perfume(
    db: Session, perfume: Perfume, stores: list[Store], *, progress_key: str | None = None
) -> None:
    """Check one monitored perfume against the given (enabled) stores."""
    run = scrape_runs_repo.start_run(db, run_type=RunType.SINGLE, perfume_count=1, store_count=len(stores))

    if progress_key is not None:
        progress_service.start_run(progress_key, stores=stores, perfume_count=1)

    had_errors = await _check_perfume_against_stores(db, run.id, perfume, stores, progress_key=progress_key)

    perfumes_repo.mark_checked(db, perfume)
    _evaluate_alerts_for_perfume(db, perfume)
    scrape_runs_repo.finish_run(
        db, run, status=RunStatus.COMPLETED_WITH_ERRORS if had_errors else RunStatus.COMPLETED
    )

    if progress_key is not None:
        progress_service.finish(progress_key)


async def check_all_perfumes(
    db: Session, perfumes: list[Perfume], stores: list[Store], *, progress_key: str | None = None
) -> None:
    """Check every monitored perfume against the given (enabled) stores.

    Perfumes are checked concurrently, not one after another. The old
    sequential loop meant every store waited for the *whole run's*
    slowest store to finish the current perfume before any of them could
    start the next one - a store that finished in 0.1s could sit idle for
    seconds because a different store was still working through search
    result pages for that same perfume. Gathering perfumes together lets
    each store instead work through its own queue independently, so the
    run's wall-clock time is bounded by the slowest store's own total
    work across every perfume, not by the sum of per-perfume stalls.

    This is safe on one shared, non-async-safe Session because nothing
    that touches `db` ever awaits: _check_perfume_against_stores's
    concurrency is confined to its own inner store-gather (network-only,
    see _scrape_store_offers), and the persistence/mark_checked/alert
    calls below are all plain synchronous calls with no `await` inside
    them - asyncio's cooperative scheduler can only switch to another
    coroutine at an `await` point, so once one of these gathered
    check_one() calls resumes from its store-gather and starts running
    that synchronous tail, it runs to completion uninterrupted before any
    other perfume's coroutine can touch the session.
    """
    run = scrape_runs_repo.start_run(
        db, run_type=RunType.ALL, perfume_count=len(perfumes), store_count=len(stores)
    )

    if progress_key is not None:
        progress_service.start_run(progress_key, stores=stores, perfume_count=len(perfumes))

    async def check_one(perfume: Perfume) -> bool:
        had_errors = await _check_perfume_against_stores(db, run.id, perfume, stores, progress_key=progress_key)
        perfumes_repo.mark_checked(db, perfume)
        _evaluate_alerts_for_perfume(db, perfume)
        return had_errors

    results = await asyncio.gather(*(check_one(perfume) for perfume in perfumes))
    had_errors = any(results)

    scrape_runs_repo.finish_run(
        db, run, status=RunStatus.COMPLETED_WITH_ERRORS if had_errors else RunStatus.COMPLETED
    )

    if progress_key is not None:
        progress_service.finish(progress_key)


async def _check_perfume_against_stores(
    db: Session, scrape_run_id: int, perfume: Perfume, stores: list[Store], *, progress_key: str | None = None
) -> bool:
    """Scrapes every store concurrently, then writes results sequentially.
    Returns True if any store's call failed outright (a store failing
    never stops the others - see _scrape_store_offers).

    This function itself may now run concurrently for several perfumes at
    once (see check_all_perfumes) - a store can therefore be hit by
    several perfumes' worth of calls to this at the same time. That's
    fine: the pooled scraper's own request lock (see app/scrapers/pool.py)
    is what actually serializes that store's real HTTP requests, whether
    the concurrent callers are different perfumes from one check_all_perfumes
    run or two separate browser tabs triggering checks at once.
    """

    async def scrape_and_report(store: Store) -> _ScrapeOutcome:
        if progress_key is not None:
            progress_service.mark_checking(progress_key, store.id, f"{perfume.brand} {perfume.name}")
        outcome = await _scrape_store_offers(perfume, store)
        if progress_key is not None:
            progress_service.mark_store_progress(progress_key, store.id)
        return outcome

    outcomes = await asyncio.gather(*(scrape_and_report(store) for store in stores))

    had_errors = False
    for store, outcome in zip(stores, outcomes):
        if not _persist_scrape_result(db, scrape_run_id, perfume, store, outcome):
            had_errors = True
    return had_errors


def _evaluate_alerts_for_perfume(db: Session, perfume: Perfume) -> None:
    for variant in variants_repo.list_for_perfume(db, perfume.id):
        alert_service.evaluate_variant_alerts(db, variant)


@dataclass
class _ScrapeOutcome:
    """Result of the network-only phase for one (perfume, store) pair - no
    database access happens while producing this, so many of these can
    run concurrently via asyncio.gather without touching the shared
    Session. `offers` is None exactly when the store call itself failed
    (as opposed to succeeding with zero offers, which is a legitimate
    "not found" result, not a failure)."""

    offers: list[ScrapedOffer] | None
    error_status: ScrapeResultStatus | None = None
    error_message: str | None = None


async def _scrape_store_offers(perfume: Perfume, store: Store) -> _ScrapeOutcome:
    """Network-only: looks up the pooled scraper and calls discover_offers.
    Never touches the database - safe to run concurrently with the same
    call for other stores (see _check_perfume_against_stores)."""
    scraper = await scraper_pool.get_scraper(store)
    if scraper is None:
        message = f"No scraper registered for '{store.scraper_identifier}'"
        logger.error("%s: %s", store.slug, message)
        return _ScrapeOutcome(offers=None, error_status=ScrapeResultStatus.SCRAPING_ERROR, error_message=message)

    try:
        offers = await scraper.discover_offers(perfume.brand, perfume.name)
        return _ScrapeOutcome(offers=offers)
    except StoreUnavailable as exc:
        logger.warning("%s: store unavailable for '%s': %s", store.slug, perfume.name, exc)
        return _ScrapeOutcome(offers=None, error_status=ScrapeResultStatus.STORE_UNAVAILABLE, error_message=str(exc))
    except Exception as exc:  # noqa: BLE001 - isolate store failures per section 43
        logger.exception("%s: scraping error for '%s'", store.slug, perfume.name)
        return _ScrapeOutcome(offers=None, error_status=ScrapeResultStatus.SCRAPING_ERROR, error_message=str(exc))


def _persist_scrape_result(
    db: Session, scrape_run_id: int, perfume: Perfume, store: Store, outcome: _ScrapeOutcome
) -> bool:
    """Database-only: writes one store's already-scraped result. Never
    awaits anything - all these calls for a perfume's stores run one
    after another, never concurrently, since a single SQLAlchemy Session
    isn't safe for concurrent use. Returns True if the store was queried
    successfully (found or not), False if the store call itself failed.
    """
    if outcome.offers is None:
        stores_repo.record_error(db, store, error_message=outcome.error_message)
        scrape_runs_repo.add_result(
            db,
            scrape_run_id=scrape_run_id,
            perfume_id=perfume.id,
            store_id=store.id,
            status=outcome.error_status,
            error_message=outcome.error_message,
        )
        return False

    # A store can genuinely list the exact same variant twice under two
    # different product URLs (confirmed live on Koku.ro: the same Serge
    # Lutens Santal Majuscule EDP 50ml has two separate catalog entries at
    # two different prices) - only one StoreProduct row can exist per
    # (store, variant) though, so persisting every matching offer in turn
    # would just make the price flip-flop on every single check with no
    # real change ever happening (visible as spurious back-to-back +/-
    # entries on the same run in the price-changes view). Resolved first,
    # deduplicated by variant, before anything is written.
    resolved: dict[int, tuple[PerfumeVariant, ScrapedOffer]] = {}
    for offer in outcome.offers:
        result = _resolve_offer(db, perfume, store, offer)
        if result is None:
            continue
        variant, resolved_offer = result
        existing = resolved.get(variant.id)
        if existing is None or _offer_is_better(resolved_offer, existing[1]):
            resolved[variant.id] = (variant, resolved_offer)

    offers_saved = 0
    any_in_stock = False
    touched_variant_ids: set[int] = set()

    for variant, offer in resolved.values():
        _persist_offer(db, store, variant, offer, scrape_run_id)
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


def _resolve_offer(
    db: Session, perfume: Perfume, store: Store, offer: ScrapedOffer
) -> tuple[PerfumeVariant, ScrapedOffer] | None:
    """Validate one scraped offer against the monitored perfume. Returns
    the (variant, offer) pair if it's a confident match for an exact
    variant, else None. Never persists a store_product/price_history row -
    see _persist_offer for that; kept separate so _persist_scrape_result
    can resolve every offer first and deduplicate by variant before
    writing anything (see its own comment for why that matters).
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

    return variant, offer


def _offer_is_better(candidate: ScrapedOffer, current: ScrapedOffer) -> bool:
    """Tie-break when two of this check's offers resolved to the exact
    same variant (see _persist_scrape_result). An in-stock listing beats
    an out-of-stock one - it's actually buyable; between two offers with
    the same availability, the cheaper one wins."""
    candidate_in_stock = candidate.availability == "in_stock"
    current_in_stock = current.availability == "in_stock"
    if candidate_in_stock != current_in_stock:
        return candidate_in_stock
    return candidate.price < current.price


def _persist_offer(db: Session, store: Store, variant: PerfumeVariant, offer: ScrapedOffer, scrape_run_id: int) -> None:
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
        coupon_code=offer.coupon_code,
        coupon_price=offer.coupon_price,
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


def _compute_discount_percentage(price: Decimal, old_price: Decimal | None) -> int | None:
    if old_price is None or old_price <= 0 or price >= old_price:
        return None
    return int(round((old_price - price) / old_price * 100))
