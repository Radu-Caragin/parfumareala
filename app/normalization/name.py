"""Perfume name normalization.

Produces a canonical, comparison-safe form of a perfume name: lowercase,
diacritic-insensitive, whitespace-collapsed. This does not attempt to strip
brand/concentration/volume/tester tokens out of a noisy store title - that
kind of extraction belongs to the matching layer, which combines this
function with the concentration/volume/tester detectors.
"""

import re

from rapidfuzz import fuzz

from app.normalization.concentration import strip_concentration_tokens
from app.normalization.tester import strip_tester_tokens
from app.normalization.text_utils import collapse_whitespace, strip_diacritics
from app.normalization.volume import strip_volume_tokens

_STRAY_PUNCTUATION_PATTERN = re.compile(r"[\"'‘’“”,]|(?<!\S)-(?!\S)")

# Audience/gender wording (e.g. "pentru femei", "unisex") is not part of
# variant identity (instructions.md section 14 - concentration/volume/
# tester only) and is common noise in a title that mixes name+everything
# else together (e.g. "Woman Eau de Parfum pentru femei" -> "Woman").
# Brasty drops the "pentru" and just appends the bare gender word instead
# (e.g. "Eau de Toilette bărbați", confirmed live) - the bare-word
# alternative catches that too. Order matters: the "pentru "-prefixed
# alternatives are tried first at each position, so "pentru bărbați"
# still gets consumed as one whole match (not leaving a dangling
# "pentru" behind) before the bare-word fallback would even apply there.
_GENDER_PATTERN = re.compile(
    r"\bpentru\s+(femei|barbati|copii)\b|\bfor\s+(women|men|kids)\b|\bunisex\b|\b(?:femei|barbati|copii)\b",
    re.IGNORECASE,
)

# Serge Lutens' former Palais-Royal-exclusive fragrances (Chergui, Ecrin de
# Fumee, Fleurs d'Oranger, L'Orpheline, Santal Majuscule, ...) were later
# relaunched for wider export under the retail line name "Collection Noir"/
# "Collection Noire" - confirmed live on Notino.ro, where every one of these
# fragrances is titled "Collection Noir(e) <name>", not the bare name alone.
# Left unstripped, that two-word prefix drags a short target name's
# token_sort_ratio score well under the ambiguous threshold (e.g. "Collection
# Noir Chergui" vs "Chergui" scores ~47), silently dropping a real, in-stock
# match.
_COLLECTION_NOIR_PATTERN = re.compile(r"\bcollection\s+noire?\b", re.IGNORECASE)

# French Avenue prefixes a subset of its catalog with its own "Aromatix"
# sub-line name (e.g. "Aromatix Sun Kissed", "Aromatix Forbidden Fruit") -
# confirmed live on two independent stores (Parfumat.ro, Notino.ro), both
# using the exact same "Aromatix <name>" wording for the same fragrance.
# Left unstripped it dragged "Sun Kissed"'s score to ~69 on both, just under
# the ambiguous threshold - stripping it is safe since the rest of the name
# still uniquely identifies each fragrance in this sub-line.
_AROMATIX_PATTERN = re.compile(r"\baromatix\b", re.IGNORECASE)

# A manufacturer "company suffix" word commonly appears directly after the
# brand in a title (e.g. "Zoologist Perfumes Tyrannosaurus Rex" for brand
# "Zoologist") without being part of the brand as the user entered it -
# consumed together with the brand so it doesn't linger as noise.
_BRAND_SUFFIX_WORDS = r"(?:perfumes?|parfums?|fragrances?|cosmetics?)"


def normalize_name(raw_name: str) -> str:
    text = strip_diacritics(raw_name).lower()
    return collapse_whitespace(text)


def extract_core_name(raw_title: str, *, brand: str | None = None) -> str:
    """Best-effort perfume name extraction from a raw title that mixes the
    name together with brand/concentration/volume/tester (used by stores
    that don't expose the name as its own structured field - e.g. Parfimo,
    where "Xerjoff Erba Gold Apa de parfum 50 ml" needs to become
    "erba gold" before fuzzy-matching against a monitored perfume).

    Stores with a clean structured name field (e.g. Fragranza) should use
    it directly instead - this is inherently approximate, since it relies
    on the same keyword lists as concentration/volume/tester detection and
    can leave stray words behind (a store-specific line/edition marker,
    for instance) that those detectors don't recognize. A dangling "-"
    left over from a "Brand - Name" separator (once the brand word itself
    is stripped) is cleaned up the same way as stray quote marks - as are
    stray commas left over from a "Brand, Name, Gender, Volume"-style
    title (confirmed live: Parfumat's "Paris Corner, Mawj Moscow Mule,
    Unisex, 100 ml" left ", mawj moscow mule, ," behind once the other
    fields were stripped, which - left unfixed - would have compared as
    unequal to a clean "mawj moscow mule" and fallen back to a weaker
    fuzzy-match score for no real reason).
    """
    text = strip_diacritics(raw_title).lower()
    if brand:
        brand_normalized = strip_diacritics(brand).lower()
        text = re.sub(
            rf"\b{re.escape(brand_normalized)}\b(\s+{_BRAND_SUFFIX_WORDS}\b)?", " ", text, count=1
        )
    text = strip_concentration_tokens(text)
    text = strip_volume_tokens(text)
    text = strip_tester_tokens(text)
    text = _GENDER_PATTERN.sub(" ", text)
    text = _COLLECTION_NOIR_PATTERN.sub(" ", text)
    text = _AROMATIX_PATTERN.sub(" ", text)
    text = _STRAY_PUNCTUATION_PATTERN.sub(" ", text)
    return collapse_whitespace(text)


def word_sets_overlap_fully(candidate_name: str, target_name: str) -> bool:
    """True if the monitored perfume's entire set of words is present, in
    any order, inside the candidate's. Both arguments must already be
    normalized (see normalize_name).

    Deliberately one-directional (target's words ⊆ candidate's, never the
    reverse): a store wraps the real name in EXTRA decoration - a
    collection/edition code, a product-line prefix - it doesn't truncate
    it. Confirmed live, Xerjoff's "Naxos" is officially "XJ 1861 Naxos" on
    some stores; token_sort_ratio alone scores that only 56 (well under
    any reasonable threshold) because it scores the *whole* string and
    "xj 1861" dominates a 13-character candidate, even though "naxos" is
    entirely and unambiguously present. Checking the reverse direction too
    would instead catch the opposite, genuinely risky shape: a candidate
    whose name is a strict PREFIX of the target's is usually a different,
    simpler flanker, not the same perfume with decoration added (e.g. a
    plain "Sauvage" candidate must never be treated as a possible match
    for a monitored "Sauvage Elixir" just because "sauvage" is one of its
    words - confirmed live, that's a separate fragrance entirely).

    Used both by matching_service.validate_candidate (routes such a case
    to AMBIGUOUS - the /match-review queue - rather than a silent,
    permanent REJECTED) and by every store scraper's own discovery-stage
    pre-filter (see names_plausibly_match below) - fixing only one of
    those two gates still drops the candidate at the other, same lesson
    as the Dior/Christian Dior brand-alias bug earlier in this project's
    history.
    """
    target_tokens = set(target_name.split())
    candidate_tokens = set(candidate_name.split())
    return bool(target_tokens) and target_tokens <= candidate_tokens


def names_plausibly_match(candidate_name: str, target_name: str, ambiguous_threshold: int) -> bool:
    """Cheap "is this worth fetching in full" check shared by every store
    scraper's own discovery-stage pre-filter. Both arguments must already
    be normalized (see normalize_name). Deliberately permissive - the
    authoritative decision happens later, in
    matching_service.validate_candidate, once the exact variant is known.
    """
    if candidate_name == target_name:
        return True
    if fuzz.token_sort_ratio(candidate_name, target_name) >= ambiguous_threshold:
        return True
    return word_sets_overlap_fully(candidate_name, target_name)
