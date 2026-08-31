"""SQLAlchemy ORM models.

Entity responsibilities (see architecture discussion for full reasoning):

- Perfume: the abstract monitored perfume (brand + name), no bottle info.
- PerfumeVariant: the exact comparable unit - concentration + volume_ml +
  tester. This is what must never be mixed together during comparison.
- Store: a supported perfume store (currently only Fragranza.ro).
- StoreProduct: "this exact variant, as sold by this store" - holds both
  the persistent link (product_url) AND the current price/availability,
  updated in place on every check. This avoids a separate near-duplicate
  "CurrentOffer" table.
- ScrapeRun / ScrapeResult: one manual price-check operation, and its
  per (perfume, store) outcome - including failures and "not found",
  so a store is never silently omitted from the UI.
- PriceHistory: append-only log, one row per store_product only when the
  price or availability actually changed.
- PriceAlert: a target price tied to one exact PerfumeVariant.
"""

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Availability(str, enum.Enum):
    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"


class ScrapeResultStatus(str, enum.Enum):
    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    NOT_FOUND = "not_found"
    SCRAPING_ERROR = "scraping_error"
    STORE_UNAVAILABLE = "store_unavailable"


class RunType(str, enum.Enum):
    SINGLE = "single"
    ALL = "all"


class RunStatus(str, enum.Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"


class MatchReviewStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class Perfume(Base):
    __tablename__ = "perfumes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    brand: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_brand: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    variants: Mapped[list["PerfumeVariant"]] = relationship(
        back_populates="perfume", cascade="all, delete-orphan"
    )
    scrape_results: Mapped[list["ScrapeResult"]] = relationship(
        back_populates="perfume", cascade="all, delete-orphan"
    )
    name_aliases: Mapped[list["PerfumeNameAlias"]] = relationship(
        back_populates="perfume", cascade="all, delete-orphan"
    )
    ambiguous_matches: Mapped[list["AmbiguousMatch"]] = relationship(
        back_populates="perfume", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Perfume {self.brand} {self.name}>"


class PerfumeVariant(Base):
    __tablename__ = "perfume_variants"
    __table_args__ = (
        UniqueConstraint("perfume_id", "concentration", "volume_ml", "tester", name="uq_variant_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    perfume_id: Mapped[int] = mapped_column(ForeignKey("perfumes.id", ondelete="CASCADE"), nullable=False)
    concentration: Mapped[str] = mapped_column(String(50), nullable=False)
    volume_ml: Mapped[int] = mapped_column(Integer, nullable=False)
    tester: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    perfume: Mapped["Perfume"] = relationship(back_populates="variants")
    store_products: Mapped[list["StoreProduct"]] = relationship(
        back_populates="variant", cascade="all, delete-orphan"
    )
    alerts: Mapped[list["PriceAlert"]] = relationship(back_populates="variant", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        tester_label = " Tester" if self.tester else ""
        return f"<PerfumeVariant {self.concentration} {self.volume_ml}ml{tester_label}>"


class Store(Base):
    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    scraper_identifier: Mapped[str] = mapped_column(String(100), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_successful_check: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    store_products: Mapped[list["StoreProduct"]] = relationship(
        back_populates="store", cascade="all, delete-orphan"
    )
    scrape_results: Mapped[list["ScrapeResult"]] = relationship(
        back_populates="store", cascade="all, delete-orphan"
    )
    ambiguous_matches: Mapped[list["AmbiguousMatch"]] = relationship(
        back_populates="store", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Store {self.name} enabled={self.enabled}>"


class StoreProduct(Base):
    __tablename__ = "store_products"
    __table_args__ = (UniqueConstraint("store_id", "perfume_variant_id", name="uq_store_variant"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    perfume_variant_id: Mapped[int] = mapped_column(
        ForeignKey("perfume_variants.id", ondelete="CASCADE"), nullable=False
    )

    product_url: Mapped[str] = mapped_column(String(500), nullable=False)
    store_product_identifier: Mapped[str | None] = mapped_column(String(100), nullable=True)
    product_title: Mapped[str] = mapped_column(String(500), nullable=False)

    current_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    current_old_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="RON")
    discount_percentage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    availability: Mapped[Availability] = mapped_column(SAEnum(Availability), nullable=False)

    # A store-specific coupon code that unlocks a lower price than
    # current_price (e.g. Parfimo's "Cu codul X reducere Y%" widget) -
    # shown as secondary info, never as the tracked/compared price: the
    # code requires manual entry at checkout and the campaign behind it
    # can change or disappear at any time, so it isn't a stable value to
    # base price history or alerts on.
    coupon_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    coupon_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)

    last_checked_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    store: Mapped["Store"] = relationship(back_populates="store_products")
    variant: Mapped["PerfumeVariant"] = relationship(back_populates="store_products")
    price_history: Mapped[list["PriceHistory"]] = relationship(
        back_populates="store_product", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<StoreProduct store_id={self.store_id} variant_id={self.perfume_variant_id}>"


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_type: Mapped[RunType] = mapped_column(SAEnum(RunType), nullable=False)
    status: Mapped[RunStatus] = mapped_column(SAEnum(RunStatus), nullable=False, default=RunStatus.RUNNING)

    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    perfume_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    store_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    results: Mapped[list["ScrapeResult"]] = relationship(back_populates="scrape_run", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<ScrapeRun {self.run_type} status={self.status}>"


class ScrapeResult(Base):
    __tablename__ = "scrape_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scrape_run_id: Mapped[int] = mapped_column(ForeignKey("scrape_runs.id", ondelete="CASCADE"), nullable=False)
    perfume_id: Mapped[int] = mapped_column(ForeignKey("perfumes.id", ondelete="CASCADE"), nullable=False)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)

    status: Mapped[ScrapeResultStatus] = mapped_column(SAEnum(ScrapeResultStatus), nullable=False)
    offers_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    scrape_run: Mapped["ScrapeRun"] = relationship(back_populates="results")
    perfume: Mapped["Perfume"] = relationship(back_populates="scrape_results")
    store: Mapped["Store"] = relationship(back_populates="scrape_results")

    def __repr__(self) -> str:
        return f"<ScrapeResult perfume_id={self.perfume_id} store_id={self.store_id} status={self.status}>"


class PriceHistory(Base):
    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_product_id: Mapped[int] = mapped_column(
        ForeignKey("store_products.id", ondelete="CASCADE"), nullable=False
    )
    scrape_run_id: Mapped[int | None] = mapped_column(ForeignKey("scrape_runs.id", ondelete="SET NULL"), nullable=True)

    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    old_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="RON")
    discount_percentage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    availability: Mapped[Availability] = mapped_column(SAEnum(Availability), nullable=False)

    recorded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    store_product: Mapped["StoreProduct"] = relationship(back_populates="price_history")

    def __repr__(self) -> str:
        return f"<PriceHistory store_product_id={self.store_product_id} price={self.price}>"


class PriceAlert(Base):
    __tablename__ = "price_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    perfume_variant_id: Mapped[int] = mapped_column(
        ForeignKey("perfume_variants.id", ondelete="CASCADE"), nullable=False
    )

    target_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="RON")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_triggered_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)

    variant: Mapped["PerfumeVariant"] = relationship(back_populates="alerts")

    def __repr__(self) -> str:
        return f"<PriceAlert variant_id={self.perfume_variant_id} target={self.target_price}>"


class PerfumeNameAlias(Base):
    """A confirmed alternate name for a monitored Perfume - e.g. a store
    lists Xerjoff's "Naxos" as "XJ 1861 Naxos". Added only when a human
    confirms a pending AmbiguousMatch is genuinely the same perfume, never
    guessed automatically. Once added, a future scraped candidate whose
    extracted name matches this alias exactly is treated the same as
    matching Perfume.normalized_name (see matching_service.validate_candidate).
    """

    __tablename__ = "perfume_name_aliases"
    __table_args__ = (UniqueConstraint("perfume_id", "normalized_alias", name="uq_perfume_name_alias"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    perfume_id: Mapped[int] = mapped_column(ForeignKey("perfumes.id", ondelete="CASCADE"), nullable=False)

    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    perfume: Mapped["Perfume"] = relationship(back_populates="name_aliases")

    def __repr__(self) -> str:
        return f"<PerfumeNameAlias perfume_id={self.perfume_id} alias={self.alias!r}>"


class AmbiguousMatch(Base):
    """A scraped candidate that plausibly refers to a monitored Perfume but
    whose extracted name didn't score high enough to trust automatically
    (the AMBIGUOUS tier from matching_service.validate_candidate, name-
    fuzzy-score reason specifically - not a missing-variant-fields or
    brand-mismatch rejection, both of which stay silently dropped as
    before). Surfaced for a human to confirm or reject once, instead of
    either silently discarding it (the old behavior) or auto-accepting it
    (risky - the exact same shape of mismatch can just as easily be a
    genuinely different flanker product, e.g. Nishane's "Hacivat" vs
    "Hacivat X", confirmed live to be different fragrances).

    One row per (perfume, store, product_url) - re-scraping the same
    still-undecided candidate updates price/last_seen_at in place rather
    than piling up duplicates (see match_review_service). Confirming adds
    a PerfumeNameAlias and immediately persists the offer; rejecting is
    remembered so the same candidate is never re-surfaced.
    """

    __tablename__ = "ambiguous_matches"
    __table_args__ = (UniqueConstraint("perfume_id", "store_id", "product_url", name="uq_ambiguous_match"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    perfume_id: Mapped[int] = mapped_column(ForeignKey("perfumes.id", ondelete="CASCADE"), nullable=False)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)

    raw_title: Mapped[str] = mapped_column(String(500), nullable=False)
    candidate_brand: Mapped[str] = mapped_column(String(255), nullable=False)
    candidate_name: Mapped[str] = mapped_column(String(255), nullable=False)
    concentration: Mapped[str] = mapped_column(String(50), nullable=False)
    volume_ml: Mapped[int] = mapped_column(Integer, nullable=False)
    tester: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    old_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="RON")
    availability: Mapped[Availability] = mapped_column(SAEnum(Availability), nullable=False)
    product_url: Mapped[str] = mapped_column(String(500), nullable=False)
    store_product_identifier: Mapped[str | None] = mapped_column(String(100), nullable=True)

    match_score: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[MatchReviewStatus] = mapped_column(
        SAEnum(MatchReviewStatus), nullable=False, default=MatchReviewStatus.PENDING
    )

    first_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    perfume: Mapped["Perfume"] = relationship(back_populates="ambiguous_matches")
    store: Mapped["Store"] = relationship(back_populates="ambiguous_matches")

    def __repr__(self) -> str:
        return f"<AmbiguousMatch perfume_id={self.perfume_id} store_id={self.store_id} status={self.status}>"
