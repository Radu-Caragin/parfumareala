"""Shared pytest fixtures."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import database as database_module
from app.database.database import get_db
from app.database.models import Base
from app.scrapers import pool as scraper_pool


@pytest.fixture(autouse=True)
def _reset_scraper_pool():
    """scraping_service pulls scrapers from a process-lifetime pool
    (app/scrapers/pool.py) instead of a fresh instance per call. Each test
    that exercises the app runs its own asyncio.run()/TestClient event
    loop, but the pool is a plain module-level dict with no lifetime tied
    to any of them - a pooled instance left over from one test's loop
    (curl_cffi's AsyncSession schedules timers on whatever loop was
    active when it was built) breaks with "Event loop is closed" if a
    later test's loop ever touches it. The app's own lifespan would
    normally close the pool on shutdown, but `client` deliberately never
    runs TestClient as a context manager (see its docstring) so that
    never fires in tests either - this fixture is the test-suite's stand-in
    for that cleanup, run after every single test regardless of whether
    it happens to touch the pool.
    """
    yield
    scraper_pool.reset_pool()


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

    A route's BackgroundTasks callback (e.g. a price check continuing
    after the triggering request already redirected) can't use the
    request-scoped db_session - FastAPI's dependency_overrides only apply
    to Depends(get_db), and the request-scoped session is closed by the
    time a background task runs anyway. It gets its own session instead,
    via database.get_background_session() - monkeypatched here to build
    from the SAME isolated engine as db_session (so writes are visible
    when the test queries db_session afterward - StaticPool means they
    share one underlying connection) but as a genuinely separate Session
    object, since the background task closes whatever it's handed when
    it's done, and that must not be db_session itself.
    """
    from app.main import app

    def override_get_db():
        yield db_session

    background_sessionmaker = sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False)

    def override_get_background_session():
        return background_sessionmaker()

    app.dependency_overrides[get_db] = override_get_db
    original_get_background_session = database_module.get_background_session
    database_module.get_background_session = override_get_background_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        database_module.get_background_session = original_get_background_session
