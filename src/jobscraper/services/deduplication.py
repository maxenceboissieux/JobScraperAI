"""Deterministic duplicate classification for canonical job-shaped objects."""

import re
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
    """Classify two job records without I/O, persistence, or source preference.

    A duplicate requires an explicit company.  Confirmed matches additionally
    require the same explicit location.  Unknown locations can only leave room
    for a thresholded possible match: they are never confirmation evidence.
    """

    left_company = normalize_company(left.company)
    right_company = normalize_company(right.company)
    score = title_similarity(left.title, right.title)
    if not _is_explicit_company(left_company) or not _is_explicit_company(
        right_company
    ):
        return DuplicateDecision("none", score, ("entreprise_non_explicite",))
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

    left_location = _location_evidence_key(left.location)
    right_location = _location_evidence_key(right.location)
    left_location_is_explicit = _is_explicit_location(left_location)
    right_location_is_explicit = _is_explicit_location(right_location)
    if (
        left_location_is_explicit
        and right_location_is_explicit
        and left_location != right_location
    ):
        return DuplicateDecision("none", score, ("villes_incompatibles",))
    if not _locations_compatible(left_location, right_location):
        return DuplicateDecision("none", score, ("lieux_incompatibles",))

    if (
        left_location_is_explicit
        and right_location_is_explicit
        and left_location == right_location
        and score >= CONFIRMED_TITLE_SCORE
    ):
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

    if not (left_location_is_explicit and right_location_is_explicit):
        return DuplicateDecision("none", score, ("lieu_non_explicite",))
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
    """Allow only exact place agreement or one genuinely unknown location.

    Region labels are not city evidence.  They may support a possible match
    only when the normalized regional label is identical; different regions,
    and an explicit city paired with a region, fail closed because this service
    intentionally has no geographical containment database.
    """

    if left == right:
        return True
    return _is_unknown_location(left) or _is_unknown_location(right)


def _is_explicit_company(company: str) -> bool:
    return bool(company) and _NON_EXPLICIT_COMPANY.fullmatch(company) is None


def _is_explicit_location(location: str) -> bool:
    return (
        bool(location)
        and not _is_unknown_location(location)
        and location not in _COUNTRY_LOCATION_KEYS
        and location not in _REGION_LOCATION_KEYS
    )


def _is_unknown_location(location: str) -> bool:
    return not location or _UNKNOWN_LOCATION.fullmatch(location) is not None


def _location_evidence_key(raw_location: str) -> str:
    """Extract conservative place evidence without rewriting place tokens.

    Remote clauses are discarded only across explicit separators.  An
    undelimited qualifier is removed only at a bounded edge; an ambiguous
    mixed label remains unknown rather than becoming an invented city key.
    """

    if _is_remote_descriptor(raw_location):
        return ""

    clause_source = _REMOTE_CADENCE_SLASH.sub(r"\1 par \2", raw_location)
    clauses = [
        clause.strip()
        for clause in _LOCATION_CLAUSE_SEPARATOR.split(clause_source)
        if clause.strip()
    ]
    remote_clauses = [clause for clause in clauses if _is_remote_descriptor(clause)]
    if remote_clauses:
        return _place_key_from_clauses(
            [clause for clause in clauses if not _is_remote_descriptor(clause)]
        )

    location = normalize_location(raw_location)
    tokens = location.split()
    if not _has_remote_qualifier(tokens):
        return location
    match = _REMOTE_PREFIX.fullmatch(raw_location.strip()) or _REMOTE_SUFFIX.fullmatch(
        raw_location.strip()
    )
    if match is None:
        return ""
    place = normalize_location(match.group("place"))
    if not _is_safe_bounded_place(place):
        return ""
    return place


def _place_key_from_clauses(clauses: list[str]) -> str:
    place_keys: list[str] = []
    country_keys: set[str] = set()
    for clause in clauses:
        key = normalize_location(clause)
        if not key or _DEPARTMENT_CLAUSE.fullmatch(key) is not None:
            continue
        if key in _COUNTRY_LOCATION_KEYS:
            country_keys.add(key)
            continue
        if not _is_safe_structural_place(key):
            return ""
        place_keys.append(key)
    if len(place_keys) > 1 or len(country_keys) > 1:
        return ""
    if place_keys:
        return place_keys[0]
    return next(iter(country_keys), "")


def _is_remote_descriptor(value: str) -> bool:
    tokens = normalize_location(value).split()
    return _has_remote_qualifier(tokens) and all(
        token.isdigit() or token in _REMOTE_DESCRIPTOR_TOKENS for token in tokens
    )


def _is_safe_bounded_place(place: str) -> bool:
    return bool(place) and not (
        _has_remote_qualifier(place.split())
        or _REMOTE_RESIDUAL_TOKENS.intersection(place.split())
        or _is_unknown_location(place)
        or place in _REMOTE_SCOPE_KEYS
    )


def _is_safe_structural_place(place: str) -> bool:
    tokens = place.split()
    return bool(place) and not (
        _has_remote_qualifier(tokens)
        or _REMOTE_RESIDUAL_TOKENS.intersection(tokens)
        or _is_unknown_location(place)
    )


def _has_remote_qualifier(tokens: list[str]) -> bool:
    return bool(_REMOTE_MARKER_TOKENS.intersection(tokens)) or any(
        first == "a" and second == "distance"
        for first, second in zip(tokens, tokens[1:])
    )


def _seniority(job: JobLike) -> str | None:
    """Return the highest explicit seniority level from data and title tokens.

    Marker order cannot alter the result: a compound ``Senior Lead`` title is
    lead, and ``Sr``/``Jr`` are treated as senior/junior respectively.  A
    structured source level participates in the same maximum, rather than
    overriding a stronger explicit title marker.
    """

    levels: set[str] = set()
    declared_level = getattr(job, "experience_level", None)
    if declared_level is not None:
        level_value = str(getattr(declared_level, "value", declared_level)).casefold()
        if level_value in _SENIORITY_LEVELS:
            levels.add(level_value)

    for marker in normalize_title(job.title).split():
        level = _TITLE_SENIORITY_MARKERS.get(marker)
        if level is not None:
            levels.add(level)
    return max(levels, key=_SENIORITY_RANK.__getitem__) if levels else None


_NON_EXPLICIT_COMPANY = re.compile(
    r"^(?:"
    r"n\s*[ac]|"
    r"(?:non|pas)\s+(?:communique(?:e)?|precis(?:e|ee)?|"
    r"renseigne(?:e)?|specifie(?:e)?)|"
    r"(?:entreprise|societe)?\s*confidentiel(?:le)?|"
    r"(?:entreprise|societe)?\s*(?:generique|generic)|"
    r"(?:company|entreprise|societe|employer|employeur)|"
    r"inconnu(?:e)?|unknown|not\s+specified"
    r")$"
)
_UNKNOWN_LOCATION = re.compile(
    r"^(?:"
    r"n\s*[ac]|"
    r"(?:non|pas)\s+(?:communique(?:e)?|precis(?:e|ee)?|"
    r"renseigne(?:e)?|specifie(?:e)?)|"
    r"(?:france\s+)?entiere|national(?:e)?|"
    r"inconnu(?:e)?|unknown|not\s+specified"
    r")$"
)
_REMOTE_MARKER_TOKENS = frozenset({"hybrid", "hybride", "remote", "teletravail"})
_REMOTE_DESCRIPTOR_TOKENS = frozenset(
    {
        "100",
        "a",
        "complet",
        "complete",
        "distance",
        "en",
        "europe",
        "flexible",
        "full",
        "hybrid",
        "hybride",
        "international",
        "jour",
        "jours",
        "monde",
        "pourcent",
        "par",
        "partiel",
        "partielle",
        "possible",
        "remote",
        "semaine",
        "teletravail",
        "total",
        "totale",
        "worldwide",
    }
)
_REMOTE_RESIDUAL_TOKENS = _REMOTE_DESCRIPTOR_TOKENS - {"a", "en"}
_REMOTE_SCOPE_KEYS = frozenset({"europe", "international", "monde", "worldwide"})
_LOCATION_CLAUSE_SEPARATOR = re.compile(r"\s*(?:[/|;()]|\s[-–—]\s)\s*")
_REMOTE_CADENCE_SLASH = re.compile(r"\b(jours?)\s*/\s*(semaine)\b", re.IGNORECASE)
_DEPARTMENT_CLAUSE = re.compile(r"(?:0?[1-9]|[1-9][0-9]|2[ab]|97[1-6])")
_REMOTE_MODE_PATTERN = r"(?:remote|t[eé]l[eé]travail|hybrid|hybride|[aà]\s+distance)"
_REMOTE_PERCENTAGE_PATTERN = r"(?:100(?:\s*(?:%|pourcent))?|\d{1,2}\s*(?:%|pourcent))"
_REMOTE_LEADING_MODIFIER_PATTERN = rf"(?:en|full|{_REMOTE_PERCENTAGE_PATTERN})"
_REMOTE_TRAILING_MODIFIER_PATTERN = (
    r"(?:partiel|partielle|possible|flexible|complet|complete|total|totale|"
    r"europe|international|monde|worldwide|"
    rf"{_REMOTE_PERCENTAGE_PATTERN}|\d+\s+jours?(?:\s+par\s+semaine)?)"
)
_REMOTE_QUALIFIER_PATTERN = (
    rf"(?:{_REMOTE_LEADING_MODIFIER_PATTERN}\s+)*"
    rf"{_REMOTE_MODE_PATTERN}"
    rf"(?:\s+{_REMOTE_TRAILING_MODIFIER_PATTERN})*"
)
_REMOTE_PREFIX = re.compile(
    rf"^(?:{_REMOTE_QUALIFIER_PATTERN})\s+(?P<place>.+)$",
    re.IGNORECASE,
)
_REMOTE_SUFFIX = re.compile(
    rf"^(?P<place>.+?)\s+(?:{_REMOTE_QUALIFIER_PATTERN})$",
    re.IGNORECASE,
)
_COUNTRY_LOCATION_KEYS = frozenset(
    {
        "allemagne",
        "autriche",
        "belgique",
        "danemark",
        "espagne",
        "france",
        "irlande",
        "italie",
        "luxembourg",
        "pays bas",
        "portugal",
        "royaume uni",
        "suisse",
    }
)
_REGION_LOCATION_KEYS = frozenset(
    {
        "auvergne rhone alpes",
        "bourgogne franche comte",
        "bretagne",
        "centre val de loire",
        "corse",
        "grand est",
        "hauts de france",
        "ile de france",
        "normandie",
        "nouvelle aquitaine",
        "occitanie",
        "pays de la loire",
        "provence alpes cote d azur",
    }
)


_SENIORITY_LEVELS = frozenset(
    {"internship", "junior", "mid", "senior", "lead", "director"}
)
_SENIORITY_RANK = {
    "internship": 0,
    "junior": 1,
    "mid": 2,
    "senior": 3,
    "lead": 4,
    "director": 5,
}
_TITLE_SENIORITY_MARKERS = {
    "alternance": "internship",
    "alternant": "internship",
    "apprenti": "internship",
    "intern": "internship",
    "stage": "internship",
    "stagiaire": "internship",
    "debutant": "junior",
    "jr": "junior",
    "junior": "junior",
    "confirme": "mid",
    "intermediaire": "mid",
    "expert": "senior",
    "senior": "senior",
    "sr": "senior",
    "lead": "lead",
    "principal": "lead",
    "staff": "lead",
    "directeur": "director",
    "director": "director",
}
