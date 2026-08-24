"""Database engine/session setup and initialization."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import get_settings
from app.database.models import Base

settings = get_settings()

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    """Create all tables if they don't exist yet, and seed initial data.

    Safe to call on every startup - create_all is a no-op for existing
    tables, and seeding is idempotent (checks for existing slugs first).
    """
    settings.ensure_directories()
    Base.metadata.create_all(bind=engine)

    from app.database.seed import seed_initial_stores

    with SessionLocal() as session:
        seed_initial_stores(session)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
