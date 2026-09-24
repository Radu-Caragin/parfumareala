"""Finds pairs of owned perfumes with a strongly overlapping accord
profile - "do I already own something like this?" - using cosine
similarity over each perfume's {accord name: strength} vector. Cosine is
used rather than a simple shared-accord count because it accounts for
*how much* each accord contributes (a perfume that's 90% vanilla and one
that's 5% vanilla shouldn't be called similar just for both mentioning it).
"""

import math
from dataclasses import dataclass
from itertools import combinations

from app.database.models import CollectionPerfume

# Below this, two perfumes just happen to share a couple of common
# accords (e.g. both have some "woody") rather than actually smelling
# alike - not worth surfacing as a "you already own this" flag.
_SIMILARITY_THRESHOLD = 0.72
_MAX_RESULTS = 15


@dataclass
class OverlapPair:
    perfume_a: CollectionPerfume
    perfume_b: CollectionPerfume
    percentage: float
    shared_accords: list[str]


def _accord_vector(perfume: CollectionPerfume) -> dict[str, float]:
    vector: dict[str, float] = {}
    for accord in perfume.accords:
        vector[accord.name.strip().lower()] = float(accord.strength)
    return vector


def _cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    shared_keys = a.keys() & b.keys()
    if not shared_keys:
        return 0.0
    dot = sum(a[k] * b[k] for k in shared_keys)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def find_overlapping_pairs(perfumes: list[CollectionPerfume]) -> list[OverlapPair]:
    vectors = {perfume.id: _accord_vector(perfume) for perfume in perfumes if perfume.accords}
    eligible = [p for p in perfumes if p.id in vectors]

    pairs: list[OverlapPair] = []
    for perfume_a, perfume_b in combinations(eligible, 2):
        vector_a = vectors[perfume_a.id]
        vector_b = vectors[perfume_b.id]
        similarity = _cosine_similarity(vector_a, vector_b)
        if similarity < _SIMILARITY_THRESHOLD:
            continue
        shared_accords = sorted(vector_a.keys() & vector_b.keys(), key=lambda k: vector_a[k] + vector_b[k], reverse=True)
        pairs.append(
            OverlapPair(
                perfume_a=perfume_a,
                perfume_b=perfume_b,
                percentage=round(similarity * 100, 1),
                shared_accords=shared_accords[:4],
            )
        )

    pairs.sort(key=lambda pair: pair.percentage, reverse=True)
    return pairs[:_MAX_RESULTS]
