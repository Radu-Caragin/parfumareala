from app.database.models import CollectionAccord, CollectionNote, CollectionPerfume, CollectionSimilarPerfume, NoteTier
from app.services.collection_insights_service import build_collection_insights


def _perfume(
    id_: int,
    brand: str,
    name: str,
    *,
    accords: list[tuple[str, int]] | None = None,
    notes: list[str] | None = None,
) -> CollectionPerfume:
    perfume = CollectionPerfume(
        id=id_,
        brand=brand,
        name=name,
        fragrantica_url=f"https://www.fragrantica.com/perfume/{brand}/{name}-{id_}.html",
    )
    perfume.accords = [
        CollectionAccord(name=accord_name, strength=strength, position=index)
        for index, (accord_name, strength) in enumerate(accords or [])
    ]
    perfume.notes = [
        CollectionNote(tier=NoteTier.TOP, name=note_name, position=index)
        for index, note_name in enumerate(notes or [])
    ]
    perfume.similar_perfumes = []
    return perfume


def test_build_collection_insights_ranks_accords_and_notes():
    perfumes = [
        _perfume(1, "A", "One", accords=[("amber", 100), ("citrus", 30)], notes=["Vanilla", "Musk"]),
        _perfume(2, "B", "Two", accords=[("amber", 80)], notes=["Vanilla"]),
    ]

    insights = build_collection_insights(perfumes)

    assert insights.perfume_count == 2
    assert insights.brand_count == 2
    assert insights.top_accords[0].name == "amber"
    assert insights.top_accords[0].perfume_count == 2
    assert insights.top_notes[0].name == "Vanilla"
    assert insights.top_notes[0].collection_percentage == 100
    assert round(sum(segment.percentage for segment in insights.dna)) == 100


def test_similarity_clusters_prefer_mutual_owned_relations():
    first = _perfume(1, "A", "One")
    second = _perfume(2, "B", "Two")
    third = _perfume(3, "C", "Three")
    first.similar_perfumes = [
        CollectionSimilarPerfume(brand=second.brand, name=second.name, fragrantica_url=second.fragrantica_url)
    ]
    second.similar_perfumes = [
        CollectionSimilarPerfume(brand=first.brand, name=first.name, fragrantica_url=first.fragrantica_url)
    ]
    third.similar_perfumes = [
        CollectionSimilarPerfume(brand=first.brand, name=first.name, fragrantica_url=first.fragrantica_url)
    ]

    insights = build_collection_insights([first, second, third])

    assert len(insights.clusters) == 1
    assert insights.clusters[0].total_members == 2
    assert insights.clusters[0].connection_count == 1
    assert {node.label for node in insights.clusters[0].nodes} == {"A One", "B Two"}
