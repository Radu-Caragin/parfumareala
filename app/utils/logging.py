"""Logging setup for the application.

Logs go to both the console and a rotating file under logs/app.log.
DEBUG level is only enabled when the DEBUG setting is on, to avoid
filling the logs with unnecessary noise during normal usage.
"""

import logging
from logging.handlers import RotatingFileHandler

from app.config.settings import get_settings

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def configure_logging() -> None:
    settings = get_settings()
    settings.ensure_directories()

    root_logger = logging.getLogger()

    if root_logger.handlers:
        # Already configured in this process (e.g. called from both run.py
        # and app.main during import) - avoid duplicate log lines.
        return

    root_logger.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)
    formatter = logging.Formatter(_LOG_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    file_handler = RotatingFileHandler(
        settings.logs_dir / "app.log",
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Third-party libraries are noisy at INFO/DEBUG; keep them quiet by default.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
