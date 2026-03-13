import json
import sys
import traceback

from scrapers.daniel import DanielScraper
from scrapers.fragranza import FragranzaScraper
from scrapers.notino import NotinoScraper
from scrapers.vivantis import VivantisScraper


def serialize_result(result):
    return {
        "shop_name": result.shop_name,
        "url": result.url,
        "title": result.title,
        "price": result.price,
        "currency": result.currency,
        "in_stock": result.in_stock,
        "volume_ml": result.volume_ml,
        "raw_text": result.raw_text,
    }


def main():
    try:
        if len(sys.argv) < 3:
            raise ValueError("Usage: python run_scraper_subprocess.py <url> <expected_volume_ml_or_None>")

        url = sys.argv[1]
        volume_arg = sys.argv[2]
        expected_volume_ml = None if volume_arg == "None" else int(volume_arg)

        scrapers = [
            FragranzaScraper(),
            DanielScraper(),
            VivantisScraper(),
            NotinoScraper(),
        ]

        for scraper in scrapers:
            if scraper.can_handle(url):
                result = scraper.scrape(url, expected_volume_ml=expected_volume_ml)
                print(json.dumps(
                    {
                        "ok": True,
                        "data": serialize_result(result),
                    },
                    ensure_ascii=True
                ))
                return

        raise ValueError(f"Nu există scraper pentru URL-ul: {url}")

    except Exception as e:
        print(json.dumps(
            {
                "ok": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
            },
            ensure_ascii=True
        ))
        sys.exit(1)


if __name__ == "__main__":
    main()