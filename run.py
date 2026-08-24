"""Start the Perfume Price Tracker locally.

Usage:
    python run.py

Then open http://127.0.0.1:8000 in your browser (host/port configurable
via .env).
"""

import uvicorn

from app.config.settings import get_settings


def main() -> None:
    settings = get_settings()
    settings.ensure_directories()

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )


if __name__ == "__main__":
    main()
