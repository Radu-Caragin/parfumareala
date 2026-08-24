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
