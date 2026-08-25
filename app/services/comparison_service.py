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


def cheapest_price_for_perfume(perfume: Perfume) -> Decimal | None:
    """The lowest in-stock price across every one of a perfume's variants
    (any concentration/volume/tester combination), for the dashboard's
    "sort by best price" - or None if nothing is currently in stock
    anywhere. Never mixes variants together for matching purposes (that
    rule is about which offers can be merged into one price - this only
    picks the smallest number across already-separate variant results).
    """
    best_offers = (compare_variant(variant).best_offer for variant in perfume.variants)
    prices = [offer.current_price for offer in best_offers if offer is not None]
    return min(prices) if prices else None
