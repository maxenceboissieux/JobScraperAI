"""Deterministic duplicate classification for canonical job-shaped objects."""

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal, Protocol

from jobscraper.services.normalization import (
    normalize_company,
    normalize_location,
    normalize_title,
)

DuplicateKind = Literal["confirmed", "possible", "none"]
CONFIRMED_TITLE_SCORE = 0.92
POSSIBLE_TITLE_SCORE = 0.78


class JobLike(Protocol):
    """The smallest input shape needed for pure duplicate classification."""

    title: str
    company: str
    location: str


@dataclass(frozen=True, slots=True)
class DuplicateDecision:
    """An immutable, explainable duplicate-classification result."""

    kind: DuplicateKind
    score: float
    reasons: tuple[str, ...]


def classify_duplicate(left: JobLike, right: JobLike) -> DuplicateDecision:
    """Classify two job records without I/O, persistence, or source preference."""

    left_company = normalize_company(left.company)
    right_company = normalize_company(right.company)
    score = title_similarity(left.title, right.title)
    if left_company != right_company:
        return DuplicateDecision("none", score, ("entreprise_differente",))

    left_seniority = _seniority(left)
    right_seniority = _seniority(right)
    if (
        left_seniority is not None
        and right_seniority is not None
        and left_seniority != right_seniority
    ):
        return DuplicateDecision("none", score, ("seniorite_incompatible",))

    left_location = normalize_location(left.location)
    right_location = normalize_location(right.location)
    if not _locations_compatible(left_location, right_location):
        return DuplicateDecision("none", score, ("villes_incompatibles",))

    if left_location == right_location and score >= CONFIRMED_TITLE_SCORE:
        return DuplicateDecision(
            "confirmed",
            score,
            ("entreprise_identique", "lieu_identique", "titre_confirme"),
        )

    if POSSIBLE_TITLE_SCORE <= score < CONFIRMED_TITLE_SCORE:
        return DuplicateDecision(
            "possible",
            score,
            ("entreprise_identique", "lieu_compatible", "titre_proche"),
        )

    if left_location != right_location:
        return DuplicateDecision("none", score, ("lieu_compatible_non_identique",))
    return DuplicateDecision("none", score, ("titre_insuffisant",))


def title_similarity(left_title: str, right_title: str) -> float:
    """Return a symmetric SequenceMatcher title score after normalization."""

    first_title, second_title = sorted(
        (normalize_title(left_title), normalize_title(right_title))
    )
    return SequenceMatcher(None, first_title, second_title).ratio()


def ordered_duplicate_pair_ids(left_id: int, right_id: int) -> tuple[int, int]:
    """Return the canonical persistence order for two distinct internal IDs."""

    if left_id == right_id:
        raise ValueError("Duplicate relation IDs must be distinct")
    return (left_id, right_id) if left_id < right_id else (right_id, left_id)


def _locations_compatible(left: str, right: str) -> bool:
    if left == right or not left or not right:
        return True
    left_specific = _specific_location_tokens(left)
    right_specific = _specific_location_tokens(right)
    if not left_specific or not right_specific:
        return True
    return left_specific.issubset(right_specific) or right_specific.issubset(
        left_specific
    )


def _specific_location_tokens(location: str) -> frozenset[str]:
    broad_tokens = frozenset(
        {
            "de",
            "france",
            "ile",
            "metropolitaine",
            "national",
            "region",
            "remote",
            "teletravail",
            "hybride",
            "hybrid",
        }
    )
    return frozenset(token for token in location.split() if token not in broad_tokens)


def _seniority(job: JobLike) -> str | None:
    declared_level = getattr(job, "experience_level", None)
    if declared_level is not None:
        level_value = str(getattr(declared_level, "value", declared_level)).casefold()
        if level_value in _SENIORITY_LEVELS:
            return level_value

    title = normalize_title(job.title)
    for marker, level in _TITLE_SENIORITY_MARKERS:
        if marker in title.split():
            return level
    return None


_SENIORITY_LEVELS = frozenset(
    {"internship", "junior", "mid", "senior", "lead", "director"}
)
_TITLE_SENIORITY_MARKERS = (
    ("stagiaire", "internship"),
    ("stage", "internship"),
    ("alternance", "internship"),
    ("apprenti", "internship"),
    ("junior", "junior"),
    ("debutant", "junior"),
    ("confirme", "mid"),
    ("senior", "senior"),
    ("expert", "senior"),
    ("lead", "lead"),
    ("principal", "lead"),
    ("staff", "lead"),
    ("directeur", "director"),
    ("director", "director"),
)
