"""The common result shape every store scraper must return.

Store-specific scrapers extract as much structured data as reliably
possible (brand, perfume_name, concentration, volume_ml from the site's
own structured fields when available). Fields left as None
(concentration/volume_ml) are filled in by the normalization pipeline from
raw_title as a fallback - see app/normalization/pipeline.py. Scrapers must
never return arbitrary dicts with store-specific shapes (instructions.md
section 40).
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.utils.helpers import utcnow


class ScrapedOffer(BaseModel):
    store_slug: str
    raw_title: str
    product_url: str
    store_product_identifier: str | None = None

    brand: str | None = None
    perfume_name: str | None = None
    concentration: str | None = None
    volume_ml: int | None = None
    tester: bool = False

    price: Decimal | None = None
    old_price: Decimal | None = None
    currency: str = "RON"
    availability: Literal["in_stock", "out_of_stock"]

    # A store-specific coupon code unlocking a lower price than `price`
    # (see StoreProduct.coupon_code for why this is kept separate from
    # price/old_price rather than folded into them).
    coupon_code: str | None = None
    coupon_price: Decimal | None = None

    scraped_at: datetime = Field(default_factory=utcnow)
