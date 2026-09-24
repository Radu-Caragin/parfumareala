"""Price comparison: for each exact perfume variant, determine the best
currently available offer across all stores.

Only in-stock offers qualify as the best price (instructions.md section
36) - an out-of-stock offer is never chosen, even if it is cheaper.
Variants are never mixed: each PerfumeVariant (concentration + volume +
tester) is compared strictly against its own StoreProduct rows.
"""

from dataclasses import dataclass
from decimal import Decimal

from app.database.models import Availability, Perfume, PerfumeVariant, StoreProduct


@dataclass(frozen=True)
class VariantComparison:
    variant: PerfumeVariant
    store_products: list[StoreProduct]
    best_offer: StoreProduct | None


def compare_variant(variant: PerfumeVariant) -> VariantComparison:
    in_stock_offers = [
        sp
        for sp in variant.store_products
        if sp.availability == Availability.IN_STOCK and sp.current_price is not None
    ]
    best_offer = min(in_stock_offers, key=lambda sp: sp.current_price) if in_stock_offers else None

    return VariantComparison(variant=variant, store_products=variant.store_products, best_offer=best_offer)


def compare_perfume(variants: list[PerfumeVariant]) -> list[VariantComparison]:
    return [compare_variant(variant) for variant in variants]


def best_value_offer_for_perfume(perfume: Perfume) -> StoreProduct | None:
    """Whichever in-stock variant offers the best value per ml (any
    concentration/volume/tester combination), for the dashboard card and
    its "sort by best price" - or None if nothing is currently in stock
    anywhere. This picks by price/ml but returns the offer itself (its
    .current_price is the actual price to pay, not a price/ml figure): a
    100ml bottle at 500 RON (5 RON/ml) is picked over a 30ml bottle at 200
    RON (6.67 RON/ml), even though 200 is the lower absolute price. Never
    mixes variants together for matching purposes (that rule is about
    which offers can be merged into one price - this only picks the
    best-value one across already-separate variant results).
    """
    best_offers = (compare_variant(variant).best_offer for variant in perfume.variants)
    priced_offers = [offer for offer in best_offers if offer is not None]
    if not priced_offers:
        return None
    return min(priced_offers, key=lambda offer: offer.current_price / offer.variant.volume_ml)


def cheapest_price_for_perfume(perfume: Perfume) -> Decimal | None:
    """The price component of best_value_offer_for_perfume() - see there
    for the selection rule."""
    offer = best_value_offer_for_perfume(perfume)
    return offer.current_price if offer is not None else None
