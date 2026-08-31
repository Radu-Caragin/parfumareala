"""Brand normalization.

Produces a canonical, comparison-safe form of a brand name: lowercase,
diacritic-insensitive, whitespace-collapsed. Used both for the monitored
Perfume.normalized_brand and, later, for validating scraped candidates
against it in the matching layer.
"""

from app.normalization.text_utils import collapse_whitespace, strip_diacritics


def normalize_brand(raw_brand: str) -> str:
    text = strip_diacritics(raw_brand).lower()
    return collapse_whitespace(text)


# Bidirectional aliases confirmed live: a store's own brand directory can
# list a brand under a different (also-correct) name than the one this
# app - or the user - calls it. Confirmed live on two separate stores so
# far, both for the same brand: Parfumat's directory only has "Christian
# Dior" (no "Dior" entry at all), and so did Brasty's, until that scraper
# stopped using a directory lookup entirely (see its module docstring).
# A directory-based scraper (Fragranza/EsenteDeLux/Parfumat/Vivantis)
# that finds nothing under the exact requested name should also try
# these before giving up - see brand_lookup_candidates(). Only add an
# entry here once it's actually been observed live; guessing plausible-
# looking aliases (YSL/Yves Saint Laurent, CK/Calvin Klein, ...) without
# confirming a real store uses them risks silently pulling in the wrong
# brand's products instead of just finding nothing.
_ALIAS_GROUPS: list[tuple[str, ...]] = [
    ("dior", "christian dior"),
    # Notino's own brand-directory slug for this house is
    # "initio-parfums-prives", not "initio" - confirmed live, its perfume
    # sitemap has zero product URLs under the bare "initio" prefix but 18
    # under "initio-parfums-prives".
    ("initio", "initio parfums prives"),
    # Confirmed live on two independent stores: Vivantis's own brand
    # directory lists this house as "Jean P. Gaultier" (no "Jean Paul
    # Gaultier" entry at all), and Brasty's product search results spell
    # it the same abbreviated way ("Jean P. Gaultier Le Male Elixir...") -
    # "paul" written out in full never appears on either site.
    ("jean paul gaultier", "jean p. gaultier"),
]
_ALIASES: dict[str, tuple[str, ...]] = {}
for _group in _ALIAS_GROUPS:
    for _name in _group:
        _ALIASES[_name] = tuple(n for n in _group if n != _name)


def brand_lookup_candidates(raw_brand: str) -> list[str]:
    """Every normalized form worth trying when looking a brand up in a
    store's own brand directory - the requested brand's own normalized
    name first, then any confirmed alternate name a store might use
    instead (see _ALIAS_GROUPS above). Also used by
    matching_service.validate_candidate's own brand-match gate - a
    candidate's brand is accepted if it's any of these, not just an exact
    match against the monitored perfume's own normalized_brand (confirmed
    necessary live: fixing only a scraper's own discovery-stage alias
    handling and not this downstream gate left the Dior/Christian Dior
    case rejected end-to-end even after the scraper itself found it)."""
    normalized = normalize_brand(raw_brand)
    return [normalized, *_ALIASES.get(normalized, ())]
