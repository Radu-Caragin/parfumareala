"""Database engine/session setup and initialization."""

from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import get_settings
from app.database.models import Base

settings = get_settings()

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

# Columns added to an already-shipped table after its initial release.
# Base.metadata.create_all() only creates missing *tables*, never adds
# columns to one that already exists - with no migration tool (Alembic
# would be overkill for a single-file personal SQLite app), a new nullable
# column has to be added by hand like this or every existing store_products
# row on someone's real, already-populated database would break on the
# next read.
_ADDED_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "store_products": [
        ("coupon_code", "VARCHAR(50)"),
        ("coupon_price", "NUMERIC(10, 2)"),
    ],
}


def _apply_added_columns() -> None:
    inspector = inspect(engine)
    with engine.begin() as connection:
        for table_name, columns in _ADDED_COLUMNS.items():
            if not inspector.has_table(table_name):
                continue
            existing = {col["name"] for col in inspector.get_columns(table_name)}
            for column_name, column_type in columns:
                if column_name not in existing:
                    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))


def init_db() -> None:
    """Create all tables if they don't exist yet, and seed initial data.

    Safe to call on every startup - create_all is a no-op for existing
    tables, _apply_added_columns() is a no-op once a column exists, and
    seeding is idempotent (checks for existing slugs first).
    """
    settings.ensure_directories()
    Base.metadata.create_all(bind=engine)
    _apply_added_columns()

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


def get_background_session() -> Session:
    """Creates a session for code that runs outside a normal request (a
    FastAPI BackgroundTasks callback, e.g. a price check kicked off by a
    route and continuing after that route's response was already sent) -
    the request-scoped session from get_db() is already closed by the
    time such code runs, so it needs its own.

    A thin wrapper around SessionLocal() rather than calling it directly
    so tests can monkeypatch just this one function to redirect
    background-task DB access to an isolated test database, mirroring how
    get_db() is already overridden via FastAPI's dependency_overrides for
    request-scoped access - see tests/conftest.py's `client` fixture.
    """
    return SessionLocal()
