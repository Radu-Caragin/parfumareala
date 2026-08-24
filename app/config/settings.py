"""Application configuration, loaded from environment variables and .env.

Paths are computed relative to the project root so the application works
regardless of where the project folder is cloned or moved.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# app/config/settings.py -> app/config -> app -> project root
BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_PATH: str = "data/perfume_tracker.db"

    REQUEST_TIMEOUT: float = 15.0
    REQUEST_DELAY: float = 1.0
    MAX_RETRIES: int = 3
    USER_AGENT: str = "Mozilla/5.0 (compatible; PerfumePriceTracker/1.0; personal use)"

    DEBUG: bool = False
    HOST: str = "127.0.0.1"
    PORT: int = 8000

    # Fuzzy name-matching thresholds (0-100, rapidfuzz token_sort_ratio).
    # Never applied to brand/concentration/volume/tester - those stay exact.
    MATCH_NAME_HIGH_CONFIDENCE_THRESHOLD: int = 90
    MATCH_NAME_AMBIGUOUS_THRESHOLD: int = 70

    @property
    def base_dir(self) -> Path:
        return BASE_DIR

    @property
    def data_dir(self) -> Path:
        return BASE_DIR / "data"

    @property
    def logs_dir(self) -> Path:
        return BASE_DIR / "logs"

    @property
    def database_file(self) -> Path:
        path = Path(self.DATABASE_PATH)
        return path if path.is_absolute() else BASE_DIR / path

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_file}"

    def ensure_directories(self) -> None:
        """Create the data/ and logs/ directories if they don't exist yet."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
