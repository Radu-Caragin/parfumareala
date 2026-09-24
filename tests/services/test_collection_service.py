import asyncio

from app.database.repositories import collection as collection_repo
from app.scrapers import fragrantica, fragrantica_wardrobe
from app.scrapers.exceptions import RequestError
from app.services import collection_service

URL_1 = "https://www.fragrantica.com/perfume/Initio-Parfums-Prives/Narcotic-Delight-89368.html"
URL_2 = "https://www.fragrantica.com/perfume/Xerjoff/XJ-1861-Naxos-30537.html"
URL_3 = "https://www.fragrantica.com/perfume/Dior/Sauvage-31861.html"


def test_profile_import_adds_skips_and_records_individual_failures(db_session, monkeypatch):
    collection_repo.create(
        db_session,
        brand="Xerjoff",
        name="XJ 1861 Naxos",
        fragrantica_url=URL_2,
        accords=[],
        notes=[],
    )

    async def fake_discovery(profile_url):
        assert profile_url == "https://www.fragrantica.com/@profunote"
        return [URL_1, URL_2, URL_3]

    async def fake_fetch(url):
        if url == URL_3:
            raise RequestError("temporary failure")
        return "<html></html>"

    monkeypatch.setattr(fragrantica_wardrobe, "fetch_owned_perfume_urls", fake_discovery)
    monkeypatch.setattr(fragrantica, "fetch_page", fake_fetch)

    result = asyncio.run(
        collection_service.import_from_fragrantica_profile(
            db_session, "https://www.fragrantica.com/@profunote", delay_seconds=0
        )
    )

    assert result.discovered == 3
    assert [item.fragrantica_url for item in result.added] == [URL_1]
    assert result.skipped_urls == [URL_2]
    assert result.failed_urls == [URL_3]
    assert len(collection_repo.list_all(db_session)) == 2


def test_refresh_all_similar_perfumes_continues_after_an_individual_failure(db_session, monkeypatch):
    first = collection_repo.create(
        db_session, brand="Initio", name="One", fragrantica_url=URL_1, accords=[], notes=[]
    )
    second = collection_repo.create(
        db_session, brand="Xerjoff", name="Two", fragrantica_url=URL_2, accords=[], notes=[]
    )
    third = collection_repo.create(
        db_session, brand="Dior", name="Three", fragrantica_url=URL_3, accords=[], notes=[]
    )
    refreshed_ids = []

    async def fake_refresh(db, item):
        if item.id == second.id:
            raise RequestError("temporary failure")
        refreshed_ids.append(item.id)
        return item

    monkeypatch.setattr(collection_service, "refresh_similar_perfumes", fake_refresh)

    result = asyncio.run(
        collection_service.refresh_all_similar_perfumes(db_session, delay_seconds=0)
    )

    assert result.total == 3
    assert [item.id for item in result.updated] == refreshed_ids
    assert set(refreshed_ids) == {first.id, third.id}
    assert result.failed_urls == [URL_2]
