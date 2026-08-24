"""Combines the individual field detectors to extract structured data from a
raw product title. This is the primitive the matching layer (Phase 4) and
the scraping integration (later phases) build on to interpret scraped
titles before comparing them against a monitored perfume.
"""

from dataclasses import dataclass

from app.normalization.concentration import extract_concentration
from app.normalization.tester import is_tester
from app.normalization.volume import extract_volume_ml


@dataclass(frozen=True)
class ExtractedFields:
    concentration: str | None
    volume_ml: int | None
    tester: bool


def extract_fields_from_title(raw_title: str, *, structured_volume_ml: int | None = None) -> ExtractedFields:
    return ExtractedFields(
        concentration=extract_concentration(raw_title),
        volume_ml=extract_volume_ml(raw_title, structured_volume_ml=structured_volume_ml),
        tester=is_tester(raw_title),
    )
