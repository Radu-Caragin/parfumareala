"""Shared pytest fixtures."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.database import get_db
from app.database.models import Base


@pytest.fixture()
def db_session():
    """An isolated in-memory SQLite session, never touching the real DB file.

    StaticPool keeps a single shared connection for the whole engine instead
    of one per thread - required here because TestClient (used by the
    `client` fixture) runs requests in a separate thread, and a plain
    sqlite:///:memory: engine would otherwise hand that thread a fresh,
    empty database.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = testing_session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db_session):
    """A TestClient wired to the isolated db_session via dependency override.

    Deliberately not used as a context manager, so the app's lifespan (which
    calls init_db() against the real data/*.db file) never runs during tests.
    """
    from app.main import app

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
