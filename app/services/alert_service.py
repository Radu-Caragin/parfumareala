"""Local price alerts: notify (in the UI only) when an in-stock offer for
an exact perfume variant drops to or below a configured target price.

No email/Telegram/push/SMS/external notifications - alerts only ever
surface inside this web app (instructions.md section 37). An alert
belongs to one exact PerfumeVariant, never a whole Perfume (section 38),
and only in-stock offers can trigger it - an out-of-stock offer below the
target price does not count.
"""

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.database.models import Availability, PerfumeVariant, PriceAlert, StoreProduct
from app.database.repositories import alerts as alerts_repo

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TriggeredAlert:
    alert: PriceAlert
    matching_offers: list[StoreProduct]


def _matching_in_stock_offers(variant: PerfumeVariant, target_price) -> list[StoreProduct]:
    return [
        sp
        for sp in variant.store_products
        if sp.availability == Availability.IN_STOCK
        and sp.current_price is not None
        and sp.current_price <= target_price
    ]


def evaluate_variant_alerts(db: Session, variant: PerfumeVariant) -> list[TriggeredAlert]:
    """Check this variant's enabled alerts against its current in-stock
    offers, persisting last_triggered_at/last_triggered_price for any that
    fire. Called as part of a price check (instructions.md section 68).
    """
    triggered: list[TriggeredAlert] = []

    for alert in alerts_repo.list_for_variant(db, variant.id):
        if not alert.enabled:
            continue

        matching = _matching_in_stock_offers(variant, alert.target_price)
        if not matching:
            continue

        best = min(matching, key=lambda sp: sp.current_price)
        alerts_repo.mark_triggered(db, alert, price=best.current_price)
        logger.info(
            "Alert %s triggered for variant %s: %s %s at %s (target %s %s)",
            alert.id, variant.id, best.current_price, best.currency, best.store_id,
            alert.target_price, alert.currency,
        )
        triggered.append(TriggeredAlert(alert=alert, matching_offers=matching))

    return triggered


def current_alert_status(variant: PerfumeVariant) -> list[TriggeredAlert]:
    """Live view of which enabled alerts are currently triggered, based on
    already-loaded current offers - does not write to the database. Used
    for display, so the page always reflects the latest known state even
    between checks.
    """
    results: list[TriggeredAlert] = []

    for alert in variant.alerts:
        if not alert.enabled:
            continue
        matching = _matching_in_stock_offers(variant, alert.target_price)
        if matching:
            results.append(TriggeredAlert(alert=alert, matching_offers=matching))

    return results
