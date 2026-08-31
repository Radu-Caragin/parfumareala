"""Business logic for the "needs review" queue - confirming or rejecting
an AmbiguousMatch (see app.database.models.AmbiguousMatch for the full
rationale). Data access lives in app.database.repositories.match_review;
this module is what app.routes.match_review calls.
"""

from sqlalchemy.orm import Session

from app.database.models import AmbiguousMatch
from app.database.repositories import match_review as match_review_repo
from app.database.repositories import name_aliases as name_aliases_repo
from app.database.repositories import prices as prices_repo
from app.database.repositories import store_products as store_products_repo
from app.database.repositories import variants as variants_repo
from app.normalization.price import compute_discount_percentage
from app.services import alert_service


def confirm_match(db: Session, match: AmbiguousMatch) -> None:
    """The human has confirmed this candidate is genuinely the monitored
    perfume under a different name. Remembers that (a PerfumeNameAlias, so
    every future scrape treats this exact wording as EXACT automatically -
    see matching_service.validate_candidate) and immediately persists the
    offer itself, using the price/availability already captured when this
    was first surfaced - no need to wait for the next check to see it.
    """
    name_aliases_repo.get_or_create(db, perfume_id=match.perfume_id, alias=match.candidate_name)

    variant = variants_repo.get_or_create(
        db,
        perfume_id=match.perfume_id,
        concentration=match.concentration,
        volume_ml=match.volume_ml,
        tester=match.tester,
    )

    discount_percentage = compute_discount_percentage(match.price, match.old_price)
    store_product = store_products_repo.upsert_offer(
        db,
        store_id=match.store_id,
        variant_id=variant.id,
        product_url=match.product_url,
        store_product_identifier=match.store_product_identifier,
        product_title=match.raw_title,
        price=match.price,
        old_price=match.old_price,
        currency=match.currency,
        discount_percentage=discount_percentage,
        availability=match.availability,
    )
    prices_repo.record_if_changed(
        db,
        store_product_id=store_product.id,
        scrape_run_id=None,
        price=match.price,
        old_price=match.old_price,
        currency=match.currency,
        discount_percentage=discount_percentage,
        availability=match.availability,
    )

    match_review_repo.mark_confirmed(db, match)
    alert_service.evaluate_variant_alerts(db, variant)


def reject_match(db: Session, match: AmbiguousMatch) -> None:
    """The human has confirmed this candidate is NOT the monitored perfume
    - remembered so the exact same (perfume, store, product_url) is never
    re-surfaced (see match_review_repo.upsert_pending)."""
    match_review_repo.mark_rejected(db, match)
