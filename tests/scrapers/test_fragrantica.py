"""Tests for the Fragrantica URL parser and page parser, using a trimmed
real-structure fixture (see tests/fixtures/fragrantica/narcotic_delight.html) -
no live requests are made.
"""

from pathlib import Path

import pytest

from app.scrapers.fragrantica import InvalidFragranticaUrl, parse_page, parse_url

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "fragrantica"
URL = "https://www.fragrantica.com/perfume/Initio-Parfums-Prives/Narcotic-Delight-89368.html"


def _fixture_html() -> str:
    return (FIXTURES_DIR / "narcotic_delight.html").read_text(encoding="utf-8")


def test_parse_url_extracts_brand_and_name():
    brand, name = parse_url(URL)

    assert brand == "Initio Parfums Prives"
    assert name == "Narcotic Delight"


def test_parse_url_accepts_bare_domain_without_www():
    brand, name = parse_url("https://fragrantica.com/perfume/Dior/Sauvage-31861.html")

    assert brand == "Dior"
    assert name == "Sauvage"


def test_parse_url_accepts_trailing_query_string():
    brand, name = parse_url(URL + "?ref=test")

    assert brand == "Initio Parfums Prives"


def test_parse_url_rejects_non_fragrantica_host():
    with pytest.raises(InvalidFragranticaUrl):
        parse_url("https://evil.example.com/perfume/Dior/Sauvage-31861.html")


def test_parse_url_rejects_non_perfume_path():
    with pytest.raises(InvalidFragranticaUrl):
        parse_url("https://www.fragrantica.com/notes/Cherry-297.html")


def test_parse_url_rejects_garbage():
    with pytest.raises(InvalidFragranticaUrl):
        parse_url("not a url at all")


def test_parse_page_extracts_brand_and_name_from_url_not_heading():
    perfume = parse_page(URL, _fixture_html())

    assert perfume.brand == "Initio Parfums Prives"
    assert perfume.name == "Narcotic Delight"


def test_parse_page_extracts_accords_with_strength():
    perfume = parse_page(URL, _fixture_html())

    accords = {a.name: a.strength for a in perfume.accords}
    assert accords == {"sweet": 100, "vanilla": 76, "cherry": 74}


def test_parse_page_extracts_notes_by_tier():
    perfume = parse_page(URL, _fixture_html())

    by_tier: dict[str, list[str]] = {"top": [], "middle": [], "base": []}
    for note in perfume.notes:
        by_tier[note.tier].append(note.name)

    assert by_tier["top"] == ["Cherry", "Pink Pepper"]
    assert by_tier["middle"] == ["Cognac"]
    assert by_tier["base"] == ["Tobacco", "Vanilla"]


def test_parse_page_returns_empty_lists_when_sections_missing():
    perfume = parse_page(URL, "<html><body>nothing here</body></html>")

    assert perfume.accords == []
    assert perfume.notes == []
