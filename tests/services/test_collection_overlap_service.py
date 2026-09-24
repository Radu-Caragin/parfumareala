"""Tests for detecting owned perfumes with a strongly overlapping accord
profile (see app/services/collection_overlap_service.py)."""

from app.database.models import CollectionAccord, CollectionPerfume
from app.services.collection_overlap_service import find_overlapping_pairs


def _perfume(id_: int, brand: str, name: str, accords: list[tuple[str, int]]):
    perfume = CollectionPerfume(id=id_, brand=brand, name=name, fragrantica_url=f"https://x/{id_}")
    perfume.accords = [
        CollectionAccord(name=accord_name, strength=strength, position=i)
        for i, (accord_name, strength) in enumerate(accords)
    ]
    return perfume


def test_empty_collection_returns_no_pairs():
    assert find_overlapping_pairs([]) == []


def test_single_perfume_returns_no_pairs():
    perfumes = [_perfume(1, "A", "One", accords=[("citrus", 80)])]
    assert find_overlapping_pairs(perfumes) == []


def test_identical_accord_profiles_flagged_as_fully_overlapping():
    perfumes = [
        _perfume(1, "A", "One", accords=[("citrus", 80), ("woody", 40)]),
        _perfume(2, "B", "Two", accords=[("citrus", 80), ("woody", 40)]),
    ]

    pairs = find_overlapping_pairs(perfumes)

    assert len(pairs) == 1
    assert pairs[0].percentage == 100.0
    assert set(pairs[0].shared_accords) == {"citrus", "woody"}


def test_completely_different_profiles_not_flagged():
    perfumes = [
        _perfume(1, "A", "One", accords=[("citrus", 90)]),
        _perfume(2, "B", "Two", accords=[("vanilla", 90)]),
    ]

    assert find_overlapping_pairs(perfumes) == []


def test_perfume_with_no_accords_is_skipped_without_crashing():
    perfumes = [
        _perfume(1, "A", "One", accords=[]),
        _perfume(2, "B", "Two", accords=[("citrus", 80)]),
    ]

    assert find_overlapping_pairs(perfumes) == []


def test_shared_accords_ranked_by_combined_strength():
    perfumes = [
        _perfume(1, "A", "One", accords=[("citrus", 90), ("musky", 10)]),
        _perfume(2, "B", "Two", accords=[("citrus", 85), ("musky", 15)]),
    ]

    pairs = find_overlapping_pairs(perfumes)

    assert pairs[0].shared_accords[0] == "citrus"


def test_results_sorted_by_percentage_descending_and_capped():
    perfumes = [_perfume(1, "A", "One", accords=[("citrus", 80), ("woody", 40)])]
    for i in range(2, 20):
        perfumes.append(_perfume(i, "Brand", f"Twin{i}", accords=[("citrus", 80), ("woody", 40)]))

    pairs = find_overlapping_pairs(perfumes)

    assert len(pairs) == 15
    percentages = [pair.percentage for pair in pairs]
    assert percentages == sorted(percentages, reverse=True)
