"""FastAPI application entry point.

This module builds and configures the FastAPI app instance: lifespan
(directory/database setup), static files, templates, and route mounting.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config.settings import get_settings
from app.database.database import init_db
from app.routes import alerts, dashboard, perfumes, stores
from app.utils.logging import configure_logging
from app.utils.templates import templates

configure_logging()
logger = logging.getLogger(__name__)

settings = get_settings()

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_directories()
    init_db()
    logger.info("Perfume Price Tracker starting up (debug=%s)", settings.DEBUG)
    yield
    logger.info("Perfume Price Tracker shutting down")


app = FastAPI(title="Perfume Price Tracker", debug=settings.DEBUG, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(dashboard.router)
app.include_router(perfumes.router)
app.include_router(stores.router)
app.include_router(alerts.router)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return templates.TemplateResponse(
        request,
        "error.html",
        {"status_code": exc.status_code, "detail": exc.detail},
        status_code=exc.status_code,
    )


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})
