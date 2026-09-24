"""Build presentation-ready insights from the user's perfume collection."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from urllib.parse import urlparse

from app.database.models import CollectionPerfume
from app.services.collection_family_service import build_family_breakdown


@dataclass
class DnaSegment:
    name: str
    group: str
    color: str
    percentage: float
    offset: float
    top_perfumes: list[str] = field(default_factory=list)


@dataclass
class RankedAttribute:
    name: str
    perfume_count: int
    collection_percentage: float
    bar_percentage: float
    detail: str


@dataclass
class SimilarityNode:
    number: int
    label: str
    url: str
    x: float
    y: float


@dataclass
class SimilarityEdge:
    source_number: int
    target_number: int
    x1: float
    y1: float
    x2: float
    y2: float


@dataclass
class SimilarityCluster:
    nodes: list[SimilarityNode]
    edges: list[SimilarityEdge]
    total_members: int
    connection_count: int


@dataclass
class CollectionInsights:
    perfume_count: int
    brand_count: int
    similarity_signal_count: int
    dna: list[DnaSegment]
    top_accords: list[RankedAttribute]
    top_notes: list[RankedAttribute]
    clusters: list[SimilarityCluster]


def build_collection_insights(perfumes: list[CollectionPerfume]) -> CollectionInsights:
    family_shares = build_family_breakdown(perfumes)
    offset = 0.0
    dna: list[DnaSegment] = []
    for family in family_shares:
        dna.append(
            DnaSegment(
                name=family.name,
                group=family.group,
                color=family.color,
                percentage=family.percentage,
                offset=round(offset, 1),
                top_perfumes=family.top_perfumes,
            )
        )
        offset += family.percentage

    return CollectionInsights(
        perfume_count=len(perfumes),
        brand_count=len({perfume.brand.strip().casefold() for perfume in perfumes}),
        similarity_signal_count=sum(len(perfume.similar_perfumes) for perfume in perfumes),
        dna=dna,
        top_accords=_rank_accords(perfumes),
        top_notes=_rank_notes(perfumes),
        clusters=_build_similarity_clusters(perfumes),
    )


def _rank_accords(perfumes: list[CollectionPerfume], *, limit: int = 8) -> list[RankedAttribute]:
    scores: dict[str, float] = defaultdict(float)
    perfume_ids: dict[str, set[int]] = defaultdict(set)
    labels: dict[str, str] = {}
    for perfume in perfumes:
        for accord in perfume.accords:
            key = accord.name.strip().casefold()
            if not key:
                continue
            labels.setdefault(key, accord.name.strip())
            scores[key] += accord.strength
            perfume_ids[key].add(perfume.id)

    ordered = sorted(scores, key=lambda key: (scores[key], len(perfume_ids[key])), reverse=True)[:limit]
    maximum = scores[ordered[0]] if ordered else 0
    collection_size = len(perfumes)
    return [
        RankedAttribute(
            name=labels[key],
            perfume_count=len(perfume_ids[key]),
            collection_percentage=round(len(perfume_ids[key]) / collection_size * 100) if collection_size else 0,
            bar_percentage=round(scores[key] / maximum * 100, 1) if maximum else 0,
            detail=f"{len(perfume_ids[key])} perfumes · avg intensity {round(scores[key] / len(perfume_ids[key]))}",
        )
        for key in ordered
    ]


def _rank_notes(perfumes: list[CollectionPerfume], *, limit: int = 8) -> list[RankedAttribute]:
    perfume_ids: dict[str, set[int]] = defaultdict(set)
    labels: dict[str, str] = {}
    for perfume in perfumes:
        for note in perfume.notes:
            key = note.name.strip().casefold()
            if not key:
                continue
            labels.setdefault(key, note.name.strip())
            perfume_ids[key].add(perfume.id)

    ordered = sorted(perfume_ids, key=lambda key: len(perfume_ids[key]), reverse=True)[:limit]
    maximum = len(perfume_ids[ordered[0]]) if ordered else 0
    collection_size = len(perfumes)
    return [
        RankedAttribute(
            name=labels[key],
            perfume_count=len(perfume_ids[key]),
            collection_percentage=round(len(perfume_ids[key]) / collection_size * 100) if collection_size else 0,
            bar_percentage=round(len(perfume_ids[key]) / maximum * 100, 1) if maximum else 0,
            detail=f"{len(perfume_ids[key])} perfumes · {round(len(perfume_ids[key]) / collection_size * 100) if collection_size else 0}% of collection",
        )
        for key in ordered
    ]


def _url_key(url: str) -> str:
    return urlparse(url).path.rstrip("/").casefold()


def _build_similarity_clusters(
    perfumes: list[CollectionPerfume], *, limit: int = 6, node_limit: int = 8
) -> list[SimilarityCluster]:
    by_url = {_url_key(perfume.fragrantica_url): perfume for perfume in perfumes}
    by_id = {perfume.id: perfume for perfume in perfumes}
    directed: set[tuple[int, int]] = set()
    for perfume in perfumes:
        for similar in perfume.similar_perfumes:
            owned = by_url.get(_url_key(similar.fragrantica_url))
            if owned is not None and owned.id != perfume.id:
                directed.add((perfume.id, owned.id))

    mutual_edges = {
        tuple(sorted((source, target)))
        for source, target in directed
        if (target, source) in directed
    }
    edges = mutual_edges or {tuple(sorted(edge)) for edge in directed}
    adjacency: dict[int, set[int]] = defaultdict(set)
    for source, target in edges:
        adjacency[source].add(target)
        adjacency[target].add(source)

    components: list[set[int]] = []
    remaining = set(adjacency)
    while remaining:
        seed = remaining.pop()
        component = {seed}
        stack = [seed]
        while stack:
            current = stack.pop()
            new_nodes = adjacency[current] - component
            component.update(new_nodes)
            remaining.difference_update(new_nodes)
            stack.extend(new_nodes)
        if len(component) >= 2:
            components.append(component)

    components.sort(
        key=lambda component: (
            sum(1 for edge in edges if edge[0] in component and edge[1] in component),
            len(component),
        ),
        reverse=True,
    )

    clusters: list[SimilarityCluster] = []
    for component in components[:limit]:
        ranked_ids = sorted(
            component,
            key=lambda perfume_id: (len(adjacency[perfume_id] & component), by_id[perfume_id].name),
            reverse=True,
        )[:node_limit]
        coordinates: dict[int, tuple[float, float]] = {}
        for index, perfume_id in enumerate(ranked_ids):
            angle = -math.pi / 2 + (2 * math.pi * index / len(ranked_ids))
            coordinates[perfume_id] = (
                round(120 + 88 * math.cos(angle), 1),
                round(62 + 43 * math.sin(angle), 1),
            )

        nodes = [
            SimilarityNode(
                number=index + 1,
                label=f"{by_id[perfume_id].brand} {by_id[perfume_id].name}",
                url=by_id[perfume_id].fragrantica_url,
                x=coordinates[perfume_id][0],
                y=coordinates[perfume_id][1],
            )
            for index, perfume_id in enumerate(ranked_ids)
        ]
        number_by_id = {perfume_id: index + 1 for index, perfume_id in enumerate(ranked_ids)}
        visible_edges = []
        for source, target in sorted(edges):
            if source not in coordinates or target not in coordinates:
                continue
            visible_edges.append(
                SimilarityEdge(
                    source_number=number_by_id[source],
                    target_number=number_by_id[target],
                    x1=coordinates[source][0],
                    y1=coordinates[source][1],
                    x2=coordinates[target][0],
                    y2=coordinates[target][1],
                )
            )

        clusters.append(
            SimilarityCluster(
                nodes=nodes,
                edges=visible_edges,
                total_members=len(component),
                connection_count=sum(
                    1 for source, target in edges if source in component and target in component
                ),
            )
        )
    return clusters
