from pathlib import Path

import pytest

from app.scrapers.fragrantica_wardrobe import (
    InvalidFragranticaProfileUrl,
    WardrobeScrapingError,
    parse_owned_perfume_urls,
    parse_owned_shelf_payload,
    validate_profile_url,
)

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "fragrantica" / "wardrobe_rendered.html"


def test_validate_profile_url_normalizes_host_and_removes_query():
    assert validate_profile_url(" http://fragrantica.com/@profunote/?tab=wardrobe ") == (
        "https://www.fragrantica.com/@profunote"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/@profunote",
        "https://www.fragrantica.com/perfume/Brand/Name-1.html",
        "javascript:alert(1)",
        "",
    ],
)
def test_validate_profile_url_rejects_non_profile_urls(url):
    with pytest.raises(InvalidFragranticaProfileUrl):
        validate_profile_url(url)


def test_parse_owned_perfume_urls_returns_only_have_shelf_and_deduplicates():
    urls = parse_owned_perfume_urls(FIXTURE.read_text(encoding="utf-8"))

    assert urls == [
        "https://www.fragrantica.com/perfume/Initio-Parfums-Prives/Narcotic-Delight-89368.html",
        "https://www.fragrantica.com/perfume/Xerjoff/XJ-1861-Naxos-30537.html",
    ]


def test_parse_owned_perfume_urls_accepts_label_in_component_attribute():
    html = """
    <shelf-grid title="Perfumes I Have">
      <a href="/perfume/Dior/Sauvage-31861.html">Sauvage</a>
    </shelf-grid>
    """

    assert parse_owned_perfume_urls(html) == [
        "https://www.fragrantica.com/perfume/Dior/Sauvage-31861.html"
    ]


def test_parse_owned_perfume_urls_fails_when_owned_shelf_is_missing():
    with pytest.raises(WardrobeScrapingError):
        parse_owned_perfume_urls('<a href="/perfume/Dior/Sauvage-31861.html">feed item</a>')


def test_parse_owned_shelf_payload_ignores_want_and_had():
    payload = [
        {
            "field": "relation",
            "value": "want",
            "type": "wardrobe",
            "perfumes": [{"url": "/perfume/Dior/Sauvage-31861.html"}],
        },
        {
            "field": "relation",
            "value": "have",
            "type": "wardrobe",
            "perfumes": [
                {"url": "/perfume/Xerjoff/XJ-1861-Naxos-30537.html"},
                {"url": "/perfume/Xerjoff/XJ-1861-Naxos-30537.html?duplicate=1"},
                {"url": "/not-a-perfume"},
            ],
        },
        {
            "field": "relation",
            "value": "had",
            "type": "wardrobe",
            "perfumes": [{"url": "/perfume/Chanel/Bleu-de-Chanel-9099.html"}],
        },
    ]

    assert parse_owned_shelf_payload(payload) == [
        "https://www.fragrantica.com/perfume/Xerjoff/XJ-1861-Naxos-30537.html"
    ]


def test_parse_owned_shelf_payload_requires_have_shelf():
    with pytest.raises(WardrobeScrapingError):
        parse_owned_shelf_payload([])
