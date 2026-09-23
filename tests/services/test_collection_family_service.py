"""Tests for grouping Collection accords into olfactory subfamilies (see
app/services/collection_family_service.py)."""

from app.database.models import CollectionAccord, CollectionPerfume
from app.services.collection_family_service import (
    build_family_breakdown,
    group_for_subfamily,
    subfamily_for_accord,
)


def _perfume(id_: int, brand: str, name: str, accords: list[tuple[str, int]]):
    perfume = CollectionPerfume(id=id_, brand=brand, name=name, fragrantica_url=f"https://x/{id_}")
    perfume.accords = [
        CollectionAccord(name=accord_name, strength=strength, position=i)
        for i, (accord_name, strength) in enumerate(accords)
    ]
    perfume.notes = []
    return perfume


def test_subfamily_for_known_accords():
    assert subfamily_for_accord("citrus") == "Citrus"
    assert subfamily_for_accord("Musky") == "Musk/Powdery"
    assert subfamily_for_accord("vanilla") == "Gourmand"
    assert subfamily_for_accord("amber") == "Amber"
    assert subfamily_for_accord("rose") == "Floral"


def test_subfamily_for_unknown_accord_falls_back_to_other():
    assert subfamily_for_accord("some-brand-new-accord") == "Other"


def test_group_for_subfamily_rolls_up_correctly():
    assert group_for_subfamily("Citrus") == "Fresh"
    assert group_for_subfamily("Aquatic") == "Fresh"
    assert group_for_subfamily("Amber") == "Oriental"
    assert group_for_subfamily("Gourmand") == "Gourmand"
    assert group_for_subfamily("nonsense") == "Other"


def test_empty_collection_returns_no_families():
    assert build_family_breakdown([]) == []


def test_percentages_sum_to_roughly_100():
    perfumes = [
        _perfume(1, "A", "One", accords=[("citrus", 80), ("woody", 40)]),
        _perfume(2, "B", "Two", accords=[("vanilla", 60)]),
    ]

    families = build_family_breakdown(perfumes)

    total = sum(f.percentage for f in families)
    assert abs(total - 100.0) < 0.5


def test_finer_subfamilies_kept_distinct_within_same_group():
    # Citrus and Green are both "Fresh", but should show as separate
    # rows, not merged - that's the whole point of the finer breakdown.
    perfumes = [_perfume(1, "A", "One", accords=[("citrus", 50), ("green", 50)])]

    families = build_family_breakdown(perfumes)

    names = {f.name for f in families}
    assert names == {"Citrus", "Green"}
    assert all(f.group == "Fresh" for f in families)


def test_families_sorted_by_strength_descending():
    perfumes = [_perfume(1, "A", "One", accords=[("citrus", 90), ("woody", 10)])]

    families = build_family_breakdown(perfumes)

    assert [f.name for f in families] == ["Citrus", "Woods"]
    assert families[0].percentage == 90.0
    assert families[1].percentage == 10.0


def test_top_perfumes_ranked_by_contribution():
    perfumes = [
        _perfume(1, "A", "One", accords=[("citrus", 90)]),
        _perfume(2, "B", "Two", accords=[("citrus", 10)]),
    ]

    families = build_family_breakdown(perfumes)

    assert families[0].top_perfumes == ["A One", "B Two"]


def test_unmapped_accord_grouped_under_other():
    perfumes = [_perfume(1, "A", "One", accords=[("brand-new-thing", 50)])]

    families = build_family_breakdown(perfumes)

    assert len(families) == 1
    assert families[0].name == "Other"
    assert families[0].group == "Other"
    assert families[0].percentage == 100.0
