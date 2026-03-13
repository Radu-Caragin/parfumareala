from dataclasses import dataclass
from typing import Optional


@dataclass
class ScrapeResult:
    shop_name: str
    url: str
    title: Optional[str]
    price: Optional[float]
    currency: str = "RON"
    in_stock: bool = False
    volume_ml: Optional[int] = None
    raw_text: Optional[str] = None


class BaseScraper:
    shop_name = "base"

    def can_handle(self, url: str) -> bool:
        raise NotImplementedError

    def scrape(self, url: str, expected_volume_ml: int | None = None) -> ScrapeResult:
        raise NotImplementedError