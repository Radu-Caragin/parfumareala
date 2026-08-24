from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.scraping import ScrapedOffer


def test_scraped_offer_defaults():
    offer = ScrapedOffer(
        store_slug="fragranza",
        raw_title="Xerjoff Erba Gold EDP 100ml",
        product_url="https://fragranza.ro/example",
        price=Decimal("799.00"),
        availability="in_stock",
    )

    assert offer.currency == "RON"
    assert offer.tester is False
    assert offer.scraped_at is not None


def test_scraped_offer_rejects_invalid_availability():
    with pytest.raises(ValidationError):
        ScrapedOffer(
            store_slug="fragranza",
            raw_title="x",
            product_url="https://fragranza.ro/x",
            availability="maybe",
        )
