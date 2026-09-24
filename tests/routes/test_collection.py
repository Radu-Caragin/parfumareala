"""Integration tests for the personal Collection tab.

fragrantica.fetch_page (the only network call involved) is monkeypatched
per test - parse_page itself runs for real against the fixture HTML, so
these tests still exercise the real parsing path end to end.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from app.database.repositories import collection as collection_repo
from app.scrapers import fragrantica
from app.scrapers import fragrantica_wardrobe
from app.scrapers.exceptions import RequestError
from app.services import collection_service
from app.services.collection_service import CollectionImportResult, CollectionSimilarRefreshResult

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "fragrantica"
URL = "https://www.fragrantica.com/perfume/Initio-Parfums-Prives/Narcotic-Delight-89368.html"


def _fixture_html() -> str:
    return (FIXTURES_DIR / "narcotic_delight.html").read_text(encoding="utf-8")


@pytest.fixture()
def mock_fetch(monkeypatch):
    async def fake_fetch_page(url: str) -> str:
        return _fixture_html()

    monkeypatch.setattr(fragrantica, "fetch_page", fake_fetch_page)
    return fake_fetch_page


def test_collection_page_shows_empty_state(client):
    response = client.get("/collection")

    assert response.status_code == 200
    assert "Your collection is empty" in response.text
    assert '<strong>0</strong>\n        <span>perfumes</span>' in response.text


def test_collection_page_shows_wardrobe_import_form(client):
    response = client.get("/collection")

    assert 'action="/collection/import-fragrantica"' in response.text
    assert 'placeholder="https://www.fragrantica.com/@username"' in response.text


def test_collection_page_shows_refresh_all_button_when_collection_has_items(client, mock_fetch):
    client.post("/collection", data={"url": URL})

    response = client.get("/collection")

    assert 'action="/collection/refresh-similar"' in response.text
    assert "Refresh all similar perfumes" in response.text


def test_refresh_all_similar_perfumes_shows_summary(client, monkeypatch):
    async def fake_refresh_all(db):
        return CollectionSimilarRefreshResult(
            total=5,
            updated=[],
            failed_urls=["one", "two"],
        )

    monkeypatch.setattr(collection_service, "refresh_all_similar_perfumes", fake_refresh_all)

    response = client.post("/collection/refresh-similar", data={"sort": "name"})

    assert response.status_code == 200
    assert "Similar perfumes refreshed for 0 of" in response.text
    assert "5 collection perfumes" in response.text
    assert "2 failed" in response.text


def test_add_from_fragrantica_url_persists_perfume_accords_and_notes(client, db_session, mock_fetch):
    response = client.post("/collection", data={"url": URL}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/collection?sort=brand"

    items = collection_repo.list_all(db_session)
    assert len(items) == 1
    item = items[0]
    assert item.brand == "Initio Parfums Prives"
    assert item.name == "Narcotic Delight"
    assert item.fragrantica_url == URL
    assert {a.name for a in item.accords} == {"sweet", "vanilla", "cherry"}
    assert {n.name for n in item.notes} == {"Cherry", "Pink Pepper", "Cognac", "Tobacco", "Vanilla"}


def test_collection_page_lists_added_perfume_with_notes_and_accords(client, mock_fetch):
    client.post("/collection", data={"url": URL})

    response = client.get("/collection")

    assert "Initio Parfums Prives Narcotic Delight" in response.text
    assert "sweet" in response.text
    assert "Cherry" in response.text
    assert '<strong>1</strong>\n        <span>perfume</span>' in response.text


def test_add_persists_and_displays_fragrantica_similar_perfumes(client, db_session, mock_fetch, monkeypatch):
    async def fake_decode(url: str, html: str):
        assert url == URL
        return [
            fragrantica.FragranticaSimilarPerfume(
                brand="Parfums de Marly",
                name="Althaïr",
                url="https://www.fragrantica.com/perfume/Parfums-de-Marly/Althair-84109.html",
            ),
            fragrantica.FragranticaSimilarPerfume(
                brand="Lattafa Perfumes",
                name="Art Of Nature II",
                url="https://www.fragrantica.com/perfume/Lattafa-Perfumes/Art-Of-Nature-II-98242.html",
            ),
        ]

    monkeypatch.setattr(fragrantica, "decode_similar_perfumes", fake_decode)

    response = client.post("/collection", data={"url": URL}, follow_redirects=False)

    assert response.status_code == 303
    item = collection_repo.list_all(db_session)[0]
    assert [(similar.brand, similar.name) for similar in item.similar_perfumes] == [
        ("Parfums de Marly", "Althaïr"),
        ("Lattafa Perfumes", "Art Of Nature II"),
    ]

    page = client.get("/collection")
    assert "This perfume reminds me of" in page.text
    assert "Parfums de Marly Althaïr" in page.text
    assert "Lattafa Perfumes Art Of Nature II" in page.text


def test_refresh_similar_perfumes_updates_an_existing_collection_item(
    client, db_session, mock_fetch, monkeypatch
):
    client.post("/collection", data={"url": URL})
    item = collection_repo.list_all(db_session)[0]

    async def fake_decode(url: str, html: str):
        return [
            fragrantica.FragranticaSimilarPerfume(
                brand="Khadlaj Perfumes",
                name="Island Vanilla Dunes",
                url="https://www.fragrantica.com/perfume/Khadlaj-Perfumes/Island-Vanilla-Dunes-106802.html",
            )
        ]

    monkeypatch.setattr(fragrantica, "decode_similar_perfumes", fake_decode)

    response = client.post(
        f"/collection/{item.id}/refresh-similar",
        data={"sort": "name"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/collection?sort=name"
    refreshed = collection_repo.list_all(db_session)[0]
    assert [(similar.brand, similar.name) for similar in refreshed.similar_perfumes] == [
        ("Khadlaj Perfumes", "Island Vanilla Dunes")
    ]


def test_refresh_similar_perfumes_can_replace_an_existing_url_twice(
    client, db_session, mock_fetch, monkeypatch
):
    client.post("/collection", data={"url": URL})
    item = collection_repo.list_all(db_session)[0]

    async def fake_decode(url: str, html: str):
        return [
            fragrantica.FragranticaSimilarPerfume(
                brand="Parfums de Marly",
                name="Althaïr",
                url="https://www.fragrantica.com/perfume/Parfums-de-Marly/Althair-84109.html",
            )
        ]

    monkeypatch.setattr(fragrantica, "decode_similar_perfumes", fake_decode)

    first = client.post(f"/collection/{item.id}/refresh-similar", follow_redirects=False)
    second = client.post(f"/collection/{item.id}/refresh-similar", follow_redirects=False)

    assert first.status_code == 303
    assert second.status_code == 303
    refreshed = collection_repo.list_all(db_session)[0]
    assert [(similar.brand, similar.name) for similar in refreshed.similar_perfumes] == [
        ("Parfums de Marly", "Althaïr")
    ]


def test_refresh_similar_perfumes_reports_fragrantica_failure(client, db_session, mock_fetch, monkeypatch):
    client.post("/collection", data={"url": URL})
    item = collection_repo.list_all(db_session)[0]

    async def failing_fetch(url: str):
        raise RequestError("temporary failure")

    monkeypatch.setattr(fragrantica, "fetch_page", failing_fetch)

    response = client.post(f"/collection/{item.id}/refresh-similar")

    assert response.status_code == 502
    assert "Couldn&#39;t refresh similar perfumes" in response.text or "Couldn't refresh similar perfumes" in response.text


def test_add_rejects_non_fragrantica_url(client, db_session):
    response = client.post("/collection", data={"url": "https://example.com/foo"})

    assert response.status_code == 400
    assert "doesn&#39;t look like a Fragrantica" in response.text or "doesn't look like a Fragrantica" in response.text
    assert collection_repo.list_all(db_session) == []


def test_add_rejects_duplicate_url(client, db_session, mock_fetch):
    client.post("/collection", data={"url": URL})

    response = client.post("/collection", data={"url": URL})

    assert response.status_code == 400
    assert "Already in your collection" in response.text
    assert len(collection_repo.list_all(db_session)) == 1


def test_add_shows_error_when_fetch_fails(client, db_session, monkeypatch):
    async def failing_fetch(url: str) -> str:
        raise RequestError("boom")

    monkeypatch.setattr(fragrantica, "fetch_page", failing_fetch)

    response = client.post("/collection", data={"url": URL})

    assert response.status_code == 400
    assert "Couldn" in response.text
    assert collection_repo.list_all(db_session) == []


def test_import_wardrobe_shows_summary(client, monkeypatch):
    async def fake_import(db, profile_url):
        assert profile_url == "https://www.fragrantica.com/@profunote"
        return CollectionImportResult(
            discovered=5,
            added=[],
            skipped_urls=["one", "two", "three"],
            failed_urls=["four", "five"],
        )

    monkeypatch.setattr(collection_service, "import_from_fragrantica_profile", fake_import)

    response = client.post(
        "/collection/import-fragrantica",
        data={"profile_url": "https://www.fragrantica.com/@profunote"},
    )

    assert response.status_code == 200
    assert "Found 5 perfumes" in response.text
    assert "0 added" in response.text
    assert "3 already in collection" in response.text
    assert "2 failed" in response.text


def test_import_wardrobe_rejects_invalid_profile(client, monkeypatch):
    async def fake_import(db, profile_url):
        raise fragrantica_wardrobe.InvalidFragranticaProfileUrl(profile_url)

    monkeypatch.setattr(collection_service, "import_from_fragrantica_profile", fake_import)

    response = client.post("/collection/import-fragrantica", data={"profile_url": "https://example.com/me"})

    assert response.status_code == 400
    assert "Enter a Fragrantica profile URL" in response.text


def test_update_ownership_sets_price_and_volume(client, db_session, mock_fetch):
    client.post("/collection", data={"url": URL})
    item = collection_repo.list_all(db_session)[0]

    response = client.post(
        f"/collection/{item.id}/ownership",
        data={"price": "450.50", "volume_ml": "30"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    updated = collection_repo.get(db_session, item.id)
    assert updated.price == Decimal("450.50")
    assert updated.volume_ml == 30


def test_update_ownership_accepts_comma_decimal_price(client, db_session, mock_fetch):
    client.post("/collection", data={"url": URL})
    item = collection_repo.list_all(db_session)[0]

    client.post(f"/collection/{item.id}/ownership", data={"price": "450,50", "volume_ml": ""})

    updated = collection_repo.get(db_session, item.id)
    assert updated.price == Decimal("450.50")


def test_update_ownership_blank_clears_price_and_volume(client, db_session, mock_fetch):
    client.post("/collection", data={"url": URL})
    item = collection_repo.list_all(db_session)[0]
    client.post(f"/collection/{item.id}/ownership", data={"price": "450.50", "volume_ml": "30"})

    client.post(f"/collection/{item.id}/ownership", data={"price": "", "volume_ml": ""})

    updated = collection_repo.get(db_session, item.id)
    assert updated.price is None
    assert updated.volume_ml is None


def test_update_ownership_ignores_invalid_input(client, db_session, mock_fetch):
    client.post("/collection", data={"url": URL})
    item = collection_repo.list_all(db_session)[0]

    client.post(f"/collection/{item.id}/ownership", data={"price": "not-a-number", "volume_ml": "not-a-number"})

    updated = collection_repo.get(db_session, item.id)
    assert updated.price is None
    assert updated.volume_ml is None


def test_update_ownership_ignores_non_positive_volume(client, db_session, mock_fetch):
    client.post("/collection", data={"url": URL})
    item = collection_repo.list_all(db_session)[0]

    client.post(f"/collection/{item.id}/ownership", data={"price": "", "volume_ml": "0"})

    updated = collection_repo.get(db_session, item.id)
    assert updated.volume_ml is None


def test_update_ownership_404_for_missing_item(client):
    response = client.post("/collection/999/ownership", data={"price": "10", "volume_ml": "30"})

    assert response.status_code == 404


def test_collection_page_shows_saved_volume(client, db_session, mock_fetch):
    client.post("/collection", data={"url": URL})
    item = collection_repo.list_all(db_session)[0]
    client.post(f"/collection/{item.id}/ownership", data={"price": "", "volume_ml": "50"})

    response = client.get("/collection")

    assert 'name="volume_ml" placeholder="Quantity" value="50"' in response.text


def test_delete_removes_item(client, db_session, mock_fetch):
    client.post("/collection", data={"url": URL})
    item = collection_repo.list_all(db_session)[0]

    response = client.post(f"/collection/{item.id}/delete", follow_redirects=False)

    assert response.status_code == 303
    assert collection_repo.list_all(db_session) == []


def test_delete_404_for_missing_item(client):
    response = client.post("/collection/999/delete")

    assert response.status_code == 404


def test_default_sort_orders_by_brand(client, db_session):
    collection_repo.create(db_session, brand="Xerjoff", name="Alexandria II", fragrantica_url="https://x/1", accords=[], notes=[])
    collection_repo.create(db_session, brand="Dior", name="Zephyr", fragrantica_url="https://x/2", accords=[], notes=[])

    response = client.get("/collection")

    assert response.text.index("Dior Zephyr") < response.text.index("Xerjoff Alexandria II")


def test_sort_by_name_ignores_brand(client, db_session):
    collection_repo.create(db_session, brand="Xerjoff", name="Alexandria II", fragrantica_url="https://x/1", accords=[], notes=[])
    collection_repo.create(db_session, brand="Dior", name="Zephyr", fragrantica_url="https://x/2", accords=[], notes=[])

    response = client.get("/collection?sort=name")

    assert response.text.index("Xerjoff Alexandria II") < response.text.index("Dior Zephyr")
    assert 'class="active"' in response.text


def test_invalid_sort_falls_back_to_brand(client, db_session):
    response = client.get("/collection?sort=nonsense")

    assert response.status_code == 200
    assert 'href="/collection?sort=brand" class="active"' in response.text


def test_insights_shows_empty_state_with_no_accords(client, db_session, mock_fetch):
    response = client.get("/collection/insights")

    assert response.status_code == 200
    assert "Add a few perfumes with accords" in response.text


def test_insights_shows_family_breakdown(client, db_session):
    collection_repo.create(
        db_session, brand="A", name="One", fragrantica_url="https://x/1",
        accords=[("woody", 80), ("citrus", 20)], notes=[],
    )

    response = client.get("/collection/insights")

    assert response.status_code == 200
    assert "Add a few perfumes with accords" not in response.text
    assert "Woods" in response.text
    assert "Citrus" in response.text
    assert "(Woody)" in response.text
    assert "(Fresh)" in response.text
    assert "80.0%" in response.text
    assert "A One" in response.text
