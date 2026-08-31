"""Builds the price-history chart shown on a perfume's page (one per
variant, one line per store that has ever had a recorded price for it),
plus the "real discount" comparison for each store's current price.

Rendered as plain, pre-computed SVG coordinates - no JS charting library.
The rest of this app is server-rendered Jinja + a bit of htmx, and price
history here is small enough (a personal tracker, checked manually, only
ever grows on an actual price/stock change - see PriceHistory's own
docstring) that a heavier client-side charting stack would be adding a
dependency for no real benefit.

"Real discount" is deliberately never based on a store's own old_price/
discount_percentage fields - those are the store's own claim, sometimes an
inflated "was" price that was never actually charged (see StoreProduct's
own docstring on why old_price is kept only as secondary display info,
never as a comparison basis). What we can actually vouch for is our own
tracked history: has this store's *own* price for this *exact* offer
genuinely dropped since the last time we recorded it changing at all.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.database.models import StoreProduct

_CHART_WIDTH = 640
_CHART_HEIGHT = 200
_PAD_LEFT = 60
_PAD_RIGHT = 16
_PAD_TOP = 16
_PAD_BOTTOM = 28

# Cycled per store, not reused from the app's own single --color-primary -
# several lines need to stay visually distinct from each other, which one
# accent color can't do on its own.
_SERIES_COLORS = [
    "#9c3b56", "#3b6b9c", "#3b9c6b", "#c98a2e",
    "#6b3b9c", "#c9463b", "#2e9ca8", "#7a7a52",
]


@dataclass(frozen=True)
class ChartPoint:
    x: float
    y: float
    price: Decimal
    recorded_at: datetime
    is_store_low: bool  # this store's own cheapest recorded price for this offer


@dataclass(frozen=True)
class ChartSeries:
    store_name: str
    color: str
    points: list[ChartPoint]
    polyline: str  # "x1,y1 x2,y2 ..." ready for <polyline points="...">


@dataclass(frozen=True)
class VariantPriceChart:
    has_data: bool
    series: list[ChartSeries]
    min_price: Decimal | None
    max_price: Decimal | None
    avg_price: Decimal | None
    min_y: float | None
    max_y: float | None
    width: int = _CHART_WIDTH
    height: int = _CHART_HEIGHT

    @property
    def plot_left(self) -> int:
        return _PAD_LEFT

    @property
    def plot_right(self) -> int:
        return self.width - _PAD_RIGHT


_EMPTY_CHART = VariantPriceChart(
    has_data=False, series=[], min_price=None, max_price=None, avg_price=None, min_y=None, max_y=None
)


def build_variant_price_chart(store_products: list[StoreProduct]) -> VariantPriceChart:
    all_entries = [entry for sp in store_products for entry in sp.price_history]
    if not all_entries:
        return _EMPTY_CHART

    all_prices = [entry.price for entry in all_entries]
    all_times = [entry.recorded_at for entry in all_entries]
    min_price = min(all_prices)
    max_price = max(all_prices)
    avg_price = (sum(all_prices, Decimal(0)) / len(all_prices)).quantize(Decimal("0.01"))
    min_time = min(all_times)
    max_time = max(all_times)

    # Both spans can legitimately be zero - a single data point overall,
    # or every recorded price happening to be identical - guarded so a
    # real (if visually flat/single-dot) chart is still produced instead
    # of a ZeroDivisionError.
    price_span = (max_price - min_price) or Decimal("1")
    time_span = (max_time - min_time).total_seconds() or 1.0

    def to_x(t: datetime) -> float:
        return _PAD_LEFT + (t - min_time).total_seconds() / time_span * (_CHART_WIDTH - _PAD_LEFT - _PAD_RIGHT)

    def to_y(p: Decimal) -> float:
        # Inverted on purpose: a higher price sits nearer the top (a
        # smaller pixel y), matching how a price chart is normally read.
        return _PAD_TOP + float((max_price - p) / price_span) * (_CHART_HEIGHT - _PAD_TOP - _PAD_BOTTOM)

    series = []
    for i, sp in enumerate(store_products):
        history = sorted(sp.price_history, key=lambda e: e.recorded_at)
        if not history:
            continue
        store_min = min(e.price for e in history)
        points = [
            ChartPoint(
                x=to_x(entry.recorded_at),
                y=to_y(entry.price),
                price=entry.price,
                recorded_at=entry.recorded_at,
                is_store_low=(entry.price == store_min),
            )
            for entry in history
        ]
        series.append(
            ChartSeries(
                store_name=sp.store.name,
                color=_SERIES_COLORS[i % len(_SERIES_COLORS)],
                points=points,
                polyline=" ".join(f"{p.x:.1f},{p.y:.1f}" for p in points),
            )
        )

    return VariantPriceChart(
        has_data=True,
        series=series,
        min_price=min_price,
        max_price=max_price,
        avg_price=avg_price,
        min_y=to_y(min_price),
        max_y=to_y(max_price),
    )


def real_price_drop(store_product: StoreProduct) -> Decimal | None:
    """How much this store's own price for this exact offer dropped
    since the last time we recorded it changing at all - None if there's
    no earlier price to compare against yet (first-ever observation) or
    the most recent change wasn't a decrease. Always negative when
    present (a drop), so callers don't need their own sign check.
    """
    history = sorted(store_product.price_history, key=lambda e: e.recorded_at)
    if len(history) < 2:
        return None
    delta = history[-1].price - history[-2].price
    return delta if delta < 0 else None
