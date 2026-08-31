"""Product matching: determines whether a scraped candidate refers to the
same monitored perfume, and which exact variant it belongs to.

Brand is matched exactly on its normalized form - never fuzzy, since a
brand mismatch means a genuinely different product - except for a small,
confirmed-live set of alternate names one same brand is known to go by
across stores (see app.normalization.brand.brand_lookup_candidates, e.g.
"Dior" / "Christian Dior" - a store's own product data can carry either
one). That's a fixed lookup table, never a fuzzy comparison, and every
entry in it was only added after being observed live - it doesn't get
looser just because two brand names happen to look similar. Concentration,
volume and tester are also exact (they define variant identity - see
instructions.md section 26). Fuzzy matching is only ever applied to the
perfume name, to tolerate minor spelling/spacing differences between
stores, and it can never override a brand mismatch or missing variant data.

The perfume name has its own equivalent of the brand alias table:
Perfume.name_aliases (see models.py's PerfumeNameAlias). A store can call a
perfume by a genuinely different-looking but equally correct name (e.g.
Xerjoff's "Naxos" is officially "XJ 1861 Naxos") - that scores too low for
the fuzzy check below to trust automatically, and unlike a brand, this
can't be a small fixed table someone curates in advance, because it isn't
one closed list shared by everyone - any given perfume, any given store,
might turn out to have one. So each occurrence is instead surfaced once as
an AmbiguousMatch for a human to confirm (see match_review_service); a
confirmed one becomes a PerfumeNameAlias, and only entries added that way
ever count as a match here - same "never guessed, only confirmed" rule the
brand table follows.

That confirmation flow only helps if the candidate actually reaches
AMBIGUOUS in the first place, though - and "Naxos" vs "XJ 1861 Naxos"
scores only 56 on token_sort_ratio (it scores the *whole* string, and
"xj 1861" dominates a 13-character candidate), well under
ambiguous_threshold, so it would otherwise be a hard REJECTED and never
even get the chance to be reviewed. A second, narrower check catches this
specific shape - one name's entire set of words present, in any order,
inside the other's (see the word-set containment check below) - and also
routes it to AMBIGUOUS. This never feeds into EXACT/HIGH_CONFIDENCE, only
into "worth a human's one-time look", so it can afford to be more
permissive than the strict score without weakening what gets auto-saved
as a real offer.

When matching is uncertain, the result is AMBIGUOUS rather than a false
positive (instructions.md section 28).
"""

import enum
from dataclasses import dataclass

from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.database.models import Perfume, PerfumeVariant
from app.database.repositories import variants as variants_repo
from app.normalization.brand import brand_lookup_candidates
from app.normalization.exclusions import check_exclusion
from app.normalization.name import normalize_name, word_sets_overlap_fully


class MatchConfidence(str, enum.Enum):
    EXACT = "exact"
    HIGH_CONFIDENCE = "high_confidence"
    AMBIGUOUS = "ambiguous"
    REJECTED = "rejected"


@dataclass(frozen=True)
class MatchCandidate:
    """Fields already extracted from a scraped product, ready for
    validation against a monitored Perfume.

    brand/name should come from the store's structured data when available,
    falling back to title parsing otherwise. raw_title is kept for the
    defensive exclusion check and for logging.
    """

    raw_title: str
    brand: str
    name: str
    concentration: str | None
    volume_ml: int | None
    tester: bool


@dataclass(frozen=True)
class MatchResult:
    confidence: MatchConfidence
    reason: str | None = None
    # Set only alongside a "name_fuzzy_score=..." reason - the raw
    # token_sort_ratio value, structured instead of needing to be parsed
    # back out of the reason string. Used by scraping_service to record an
    # AMBIGUOUS result's score on its review-queue entry (see
    # AmbiguousMatch.match_score).
    name_score: int | None = None

    @property
    def is_usable(self) -> bool:
        """Only EXACT/HIGH_CONFIDENCE results should be persisted as offers."""
        return self.confidence in (MatchConfidence.EXACT, MatchConfidence.HIGH_CONFIDENCE)


def validate_candidate(
    perfume: Perfume,
    candidate: MatchCandidate,
    *,
    high_confidence_threshold: int | None = None,
    ambiguous_threshold: int | None = None,
) -> MatchResult:
    settings = get_settings()
    if high_confidence_threshold is None:
        high_confidence_threshold = settings.MATCH_NAME_HIGH_CONFIDENCE_THRESHOLD
    if ambiguous_threshold is None:
        ambiguous_threshold = settings.MATCH_NAME_AMBIGUOUS_THRESHOLD

    exclusion_reason = check_exclusion(candidate.raw_title)
    if exclusion_reason is not None:
        return MatchResult(MatchConfidence.REJECTED, reason=f"excluded:{exclusion_reason}")

    if perfume.normalized_brand not in brand_lookup_candidates(candidate.brand):
        return MatchResult(MatchConfidence.REJECTED, reason="brand_mismatch")

    if candidate.concentration is None or candidate.volume_ml is None:
        return MatchResult(MatchConfidence.AMBIGUOUS, reason="missing_variant_fields")

    candidate_normalized_name = normalize_name(candidate.name)

    if candidate_normalized_name == perfume.normalized_name:
        return MatchResult(MatchConfidence.EXACT)

    known_aliases = {alias.normalized_alias for alias in perfume.name_aliases}
    if candidate_normalized_name in known_aliases:
        return MatchResult(MatchConfidence.EXACT, reason="confirmed_name_alias")

    name_score = fuzz.token_sort_ratio(candidate_normalized_name, perfume.normalized_name)
    rounded_score = round(name_score)

    if name_score >= high_confidence_threshold:
        return MatchResult(
            MatchConfidence.HIGH_CONFIDENCE, reason=f"name_fuzzy_score={rounded_score}", name_score=rounded_score
        )

    if name_score >= ambiguous_threshold:
        return MatchResult(
            MatchConfidence.AMBIGUOUS, reason=f"name_fuzzy_score={rounded_score}", name_score=rounded_score
        )

    # A name wrapped in extra decoration words scores badly on the whole-
    # string comparison above even when it's a clean, complete match
    # otherwise (see word_sets_overlap_fully's own docstring for the
    # confirmed-live "Naxos"/"XJ 1861 Naxos" case). This ONLY ever decides
    # whether to surface the candidate for a human to confirm (never auto-
    # accepted, same as any other AMBIGUOUS result) - a coincidental one-
    # word overlap between two genuinely different same-brand perfumes
    # costs nothing worse than one extra "No, different" click, unlike
    # loosening the strict score above ever would.
    if word_sets_overlap_fully(candidate_normalized_name, perfume.normalized_name):
        return MatchResult(
            MatchConfidence.AMBIGUOUS, reason=f"name_containment_score={rounded_score}", name_score=rounded_score
        )

    return MatchResult(MatchConfidence.REJECTED, reason="name_mismatch")


def resolve_variant(db: Session, perfume: Perfume, candidate: MatchCandidate) -> PerfumeVariant | None:
    """Get-or-create the exact PerfumeVariant a candidate belongs to.

    Caller is responsible for only calling this once validate_candidate()
    has returned a usable (EXACT/HIGH_CONFIDENCE) result. Returns None if
    the variant fields aren't known.
    """
    if candidate.concentration is None or candidate.volume_ml is None:
        return None

    return variants_repo.get_or_create(
        db,
        perfume_id=perfume.id,
        concentration=candidate.concentration,
        volume_ml=candidate.volume_ml,
        tester=candidate.tester,
    )
