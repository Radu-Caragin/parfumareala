"""Data-access functions for StoreProduct - the current offer per store+variant.

upsert_offer only writes the "current state" fields. Whether a PriceHistory
row should also be written is a separate decision the caller makes (see
repositories/prices.py), since that depends on whether anything changed.
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Availability, PerfumeVariant, StoreProduct
from app.utils.helpers import utcnow


def get(db: Session, store_product_id: int) -> StoreProduct | None:
    return db.get(StoreProduct, store_product_id)


def get_for_store_and_variant(db: Session, *, store_id: int, variant_id: int) -> StoreProduct | None:
    return db.scalar(
        select(StoreProduct).where(
            StoreProduct.store_id == store_id,
            StoreProduct.perfume_variant_id == variant_id,
        )
    )


def upsert_offer(
    db: Session,
    *,
    store_id: int,
    variant_id: int,
    product_url: str,
    store_product_identifier: str | None,
    product_title: str,
    price: Decimal,
    old_price: Decimal | None,
    currency: str,
    discount_percentage: int | None,
    availability: Availability,
    coupon_code: str | None = None,
    coupon_price: Decimal | None = None,
) -> StoreProduct:
    now = utcnow()
    store_product = get_for_store_and_variant(db, store_id=store_id, variant_id=variant_id)

    if store_product is None:
        store_product = StoreProduct(
            store_id=store_id,
            perfume_variant_id=variant_id,
            first_seen_at=now,
        )
        db.add(store_product)

    store_product.product_url = product_url
    store_product.store_product_identifier = store_product_identifier
    store_product.product_title = product_title
    store_product.current_price = price
    store_product.current_old_price = old_price
    store_product.currency = currency
    store_product.discount_percentage = discount_percentage
    store_product.availability = availability
    # Always overwritten (not left alone when None) so a coupon from a
    # previous check that's no longer on the page doesn't linger forever.
    store_product.coupon_code = coupon_code
    store_product.coupon_price = coupon_price
    store_product.last_checked_at = now
    store_product.last_seen_at = now

    db.commit()
    db.refresh(store_product)
    return store_product


def list_for_variant(db: Session, variant_id: int) -> list[StoreProduct]:
    return list(db.scalars(select(StoreProduct).where(StoreProduct.perfume_variant_id == variant_id)))


def list_for_perfume_and_store(db: Session, perfume_id: int, store_id: int) -> list[StoreProduct]:
    return list(
        db.scalars(
            select(StoreProduct)
            .join(PerfumeVariant, StoreProduct.perfume_variant_id == PerfumeVariant.id)
            .where(PerfumeVariant.perfume_id == perfume_id, StoreProduct.store_id == store_id)
        )
    )


def mark_out_of_stock(db: Session, store_product: StoreProduct) -> None:
    store_product.availability = Availability.OUT_OF_STOCK
    db.commit()
