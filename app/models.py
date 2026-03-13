from datetime import datetime

from sqlalchemy import Column, Integer, String, Float, Date, Text, ForeignKey, Boolean, DateTime
from sqlalchemy.orm import relationship

from db import Base


class OwnedPerfume(Base):
    __tablename__ = "owned_perfumes"

    id = Column(Integer, primary_key=True, index=True)
    brand = Column(String(100), nullable=False)
    name = Column(String(150), nullable=False)
    concentration = Column(String(50), nullable=True)
    volume_ml = Column(Integer, nullable=True)
    store_name = Column(String(100), nullable=True)
    purchase_price = Column(Float, nullable=True)
    purchase_date = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)


class WatchedPerfume(Base):
    __tablename__ = "watched_perfumes"

    id = Column(Integer, primary_key=True, index=True)
    brand = Column(String(100), nullable=False)
    name = Column(String(150), nullable=False)
    concentration = Column(String(50), nullable=True)
    volume_ml = Column(Integer, nullable=True)
    desired_price = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)

    urls = relationship("WatchedUrl", back_populates="perfume", cascade="all, delete-orphan")


class WatchedUrl(Base):
    __tablename__ = "watched_urls"

    id = Column(Integer, primary_key=True, index=True)
    watched_perfume_id = Column(Integer, ForeignKey("watched_perfumes.id"), nullable=False)
    shop_name = Column(String(100), nullable=False)
    product_url = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)

    perfume = relationship("WatchedPerfume", back_populates="urls")
    prices = relationship("PriceHistory", back_populates="watched_url", cascade="all, delete-orphan")


class PriceHistory(Base):
    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True, index=True)
    watched_url_id = Column(Integer, ForeignKey("watched_urls.id"), nullable=False)
    check_run_id = Column(String(64), nullable=True)
    checked_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    price = Column(Float, nullable=True)
    currency = Column(String(10), nullable=True)
    in_stock = Column(Boolean, nullable=True)
    extracted_title = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)

    watched_url = relationship("WatchedUrl", back_populates="prices")