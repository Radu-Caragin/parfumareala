"""Buckets the user's Collection accords into olfactory subfamilies (e.g.
Citrus, Aromatic, White Floral, Woods, Amber, Musk, Gourmand) to answer
"what kind of perfumes make up my collection" - tried first as a network
graph of individual accords, then as 5 broad families (Fresh, Floral,
Woody, Oriental/Amber, Gourmand), both rejected as either unreadable or
too coarse to say anything useful. These finer subfamilies still roll up
into the same 5 broad groups (used only to color related subfamilies
alike), but are specific enough to actually distinguish a citrus-heavy
collection from a green one, or an amber-heavy one from a musky one.

The accord-to-subfamily mapping is not sourced from Fragrantica - its
pages classify a whole perfume (e.g. "Woody Floral Musk"), never an
individual accord - so this is a fixed lookup table here, based on
standard perfume-industry vocabulary. It's a judgment call, not an
authoritative source; an accord not in the table falls into "Other"
rather than raising, since new accords will keep showing up as more
perfumes get added.
"""

from collections import defaultdict
from dataclasses import dataclass, field

from app.database.models import CollectionPerfume

_ACCORD_TO_SUBFAMILY: dict[str, str] = {
    # Fresh
    "citrus": "Citrus",
    "green": "Green",
    "herbal": "Green",
    "marine": "Aquatic",
    "aquatic": "Aquatic",
    "ozonic": "Aquatic",
    "mineral": "Aquatic",
    "salty": "Aquatic",
    "aromatic": "Aromatic",
    "fresh": "Aromatic",
    "fresh spicy": "Aromatic",
    "lavender": "Aromatic",
    "aldehydic": "Aromatic",
    # Floral
    "white floral": "White Floral",
    "tuberose": "White Floral",
    "floral": "Floral",
    "yellow floral": "Floral",
    "rose": "Floral",
    "iris": "Floral",
    "violet": "Floral",
    # Woody
    "woody": "Woods",
    "earthy": "Woods",
    "patchouli": "Woods",
    "mossy": "Mossy/Oud",
    "oud": "Mossy/Oud",
    "smoky": "Mossy/Oud",
    # Oriental/Amber
    "amber": "Amber",
    "warm spicy": "Amber",
    "animalic": "Amber",
    "balsamic": "Amber",
    "soft spicy": "Spicy",
    "cinnamon": "Spicy",
    "spice": "Spicy",
    "musky": "Musk/Powdery",
    "powdery": "Musk/Powdery",
    "tobacco": "Tobacco/Leather",
    "leather": "Tobacco/Leather",
    # Gourmand
    "sweet": "Gourmand",
    "vanilla": "Gourmand",
    "honey": "Gourmand",
    "coconut": "Gourmand",
    "fruity": "Gourmand",
    "caramel": "Gourmand",
    "tropical": "Gourmand",
    "coffee": "Gourmand",
    "nutty": "Gourmand",
    "rum": "Gourmand",
    "almond": "Gourmand",
    "whiskey": "Gourmand",
    "cherry": "Gourmand",
    "beeswax": "Gourmand",
    "lactonic": "Gourmand",
    "chocolate": "Gourmand",
    "metallic": "Aquatic",
}

_SUBFAMILY_TO_GROUP: dict[str, str] = {
    "Citrus": "Fresh",
    "Green": "Fresh",
    "Aquatic": "Fresh",
    "Aromatic": "Fresh",
    "White Floral": "Floral",
    "Floral": "Floral",
    "Woods": "Woody",
    "Mossy/Oud": "Woody",
    "Amber": "Oriental",
    "Spicy": "Oriental",
    "Musk/Powdery": "Oriental",
    "Tobacco/Leather": "Oriental",
    "Gourmand": "Gourmand",
}

_FALLBACK_SUBFAMILY = "Other"
_FALLBACK_GROUP = "Other"

# One color per broad group - subfamilies belonging to the same group
# share a hue so related rows (e.g. Citrus/Green/Aquatic/Aromatic, all
# Fresh) read as visually related at a glance.
_GROUP_COLORS: dict[str, str] = {
    "Fresh": "#0ea5e9",
    "Floral": "#ec4899",
    "Woody": "#92400e",
    "Oriental": "#d97706",
    "Gourmand": "#a855f7",
    _FALLBACK_GROUP: "#64748b",
}


def subfamily_for_accord(accord_name: str) -> str:
    return _ACCORD_TO_SUBFAMILY.get(accord_name.strip().lower(), _FALLBACK_SUBFAMILY)


def group_for_subfamily(subfamily: str) -> str:
    return _SUBFAMILY_TO_GROUP.get(subfamily, _FALLBACK_GROUP)


def color_for_accord(accord_name: str) -> str:
    """The same group color used on the Insights page, looked up for one
    raw accord name - used to color a single accord chip (e.g. on a
    Collection card) consistently with the aggregate breakdown."""
    group = group_for_subfamily(subfamily_for_accord(accord_name))
    return _GROUP_COLORS.get(group, _GROUP_COLORS[_FALLBACK_GROUP])


@dataclass
class FamilyShare:
    name: str
    group: str
    color: str
    percentage: float
    top_perfumes: list[str] = field(default_factory=list)


def build_family_breakdown(perfumes: list[CollectionPerfume]) -> list[FamilyShare]:
    strength_by_subfamily: dict[str, float] = defaultdict(float)
    strength_by_subfamily_perfume: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    perfume_labels: dict[int, str] = {}

    for perfume in perfumes:
        perfume_labels[perfume.id] = f"{perfume.brand} {perfume.name}"
        for accord in perfume.accords:
            subfamily = subfamily_for_accord(accord.name)
            strength_by_subfamily[subfamily] += accord.strength
            strength_by_subfamily_perfume[subfamily][perfume.id] += accord.strength

    total = sum(strength_by_subfamily.values())
    if total <= 0:
        return []

    shares: list[FamilyShare] = []
    for subfamily, strength in sorted(strength_by_subfamily.items(), key=lambda kv: kv[1], reverse=True):
        top_contributor_ids = sorted(
            strength_by_subfamily_perfume[subfamily].items(), key=lambda kv: kv[1], reverse=True
        )[:3]
        group = group_for_subfamily(subfamily)
        shares.append(
            FamilyShare(
                name=subfamily,
                group=group,
                color=_GROUP_COLORS.get(group, _GROUP_COLORS[_FALLBACK_GROUP]),
                percentage=round(strength / total * 100, 1),
                top_perfumes=[perfume_labels[perfume_id] for perfume_id, _ in top_contributor_ids],
            )
        )
    return shares
