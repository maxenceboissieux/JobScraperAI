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
_LocationEvidenceKind = Literal[
    "place", "non_city", "remote_descriptor", "unknown", "conflict"
]
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


@dataclass(frozen=True, slots=True)
class _LocationEvidence:
    """One conservative interpretation of a raw location label."""

    kind: _LocationEvidenceKind
    key: str = ""


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

    left_location = _location_evidence(left.location)
    right_location = _location_evidence(right.location)
    left_location_is_explicit = _is_explicit_location(left_location)
    right_location_is_explicit = _is_explicit_location(right_location)
    if left_location.kind == "conflict" or right_location.kind == "conflict":
        return DuplicateDecision("none", score, ("lieux_incompatibles",))
    if (
        left_location_is_explicit
        and right_location_is_explicit
        and left_location.key != right_location.key
    ):
        return DuplicateDecision("none", score, ("villes_incompatibles",))
    if not _locations_compatible(left_location, right_location):
        return DuplicateDecision("none", score, ("lieux_incompatibles",))

    if (
        left_location_is_explicit
        and right_location_is_explicit
        and left_location.key == right_location.key
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
    if left_location.key != right_location.key:
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


def _locations_compatible(left: _LocationEvidence, right: _LocationEvidence) -> bool:
    """Allow only exact place agreement or one genuinely unknown location.

    Region labels are not city evidence.  They may support a possible match
    only when the normalized regional label is identical; different regions,
    and an explicit city paired with a region, fail closed because this service
    intentionally has no geographical containment database.
    """

    if left == right:
        return True
    return left.kind == "unknown" or right.kind == "unknown"


def _is_explicit_company(company: str) -> bool:
    return bool(company) and _NON_EXPLICIT_COMPANY.fullmatch(company) is None


def _is_explicit_location(location: _LocationEvidence) -> bool:
    return location.kind == "place"


def _is_unknown_location(location: str) -> bool:
    return not location or _UNKNOWN_LOCATION.fullmatch(location) is not None


def _location_evidence(raw_location: str) -> _LocationEvidence:
    """Parse raw clauses into place, non-city, unknown, or conflict evidence."""

    trailing_france_place = _trailing_france_place_evidence(raw_location)
    if trailing_france_place is not None:
        return trailing_france_place

    clause_source = _REMOTE_CADENCE_SLASH.sub(r"\1 par \2", raw_location)
    clauses = [
        clause.strip()
        for clause in _LOCATION_CLAUSE_SEPARATOR.split(clause_source)
        if clause.strip()
    ]
    if not clauses:
        return _LocationEvidence("unknown")

    has_remote_context = any(
        _has_remote_qualifier(normalize_location(clause).split()) for clause in clauses
    )
    parsed_clauses = [
        (clause, evidence)
        for clause in clauses
        if (
            evidence := _location_clause_evidence(
                clause, has_remote_context=has_remote_context
            )
        )
        is not None
    ]
    parsed = [evidence for _, evidence in parsed_clauses]
    if any(evidence.kind == "conflict" for evidence in parsed):
        return _LocationEvidence("conflict")

    remote_bearing_places = [
        evidence
        for clause, evidence in parsed_clauses
        if evidence.kind == "place"
        and _has_remote_qualifier(normalize_location(clause).split())
    ]
    remote_clause_count = sum(
        _has_remote_qualifier(normalize_location(clause).split()) for clause in clauses
    )
    if remote_clause_count > 1 and remote_bearing_places:
        return _LocationEvidence("unknown")

    places = {evidence for evidence in parsed if evidence.kind == "place"}
    non_city_scopes = {evidence for evidence in parsed if evidence.kind == "non_city"}
    has_unknown = any(evidence.kind == "unknown" for evidence in parsed)
    concrete = places | non_city_scopes
    if places and non_city_scopes:
        return _LocationEvidence("conflict")
    if len(places) > 1:
        return _LocationEvidence("unknown")
    if len(non_city_scopes) > 1 or (concrete and has_unknown):
        return _LocationEvidence("conflict")
    if concrete:
        return next(iter(concrete))
    return _LocationEvidence("unknown")


def _location_clause_evidence(
    raw_clause: str, *, has_remote_context: bool
) -> _LocationEvidence | None:
    key = normalize_location(raw_clause)
    if not key or _DEPARTMENT_CLAUSE.fullmatch(key) is not None:
        return None
    if _is_unknown_location(key):
        return _LocationEvidence("unknown")

    prepositional_evidence = _standalone_preposition_evidence(key)
    if prepositional_evidence is not None:
        return prepositional_evidence

    tokens = key.split()
    if _has_remote_qualifier(tokens):
        return _remote_clause_evidence(raw_clause)
    if has_remote_context and (
        _REMOTE_RESIDUAL_TOKENS.intersection(tokens) or key in _REMOTE_SCOPE_KEYS
    ):
        return _LocationEvidence("remote_descriptor")
    return _evidence_for_key(key)


def _trailing_france_place_evidence(
    raw_location: str,
) -> _LocationEvidence | None:
    """Preserve the normalizer's exact, safely-delimited France qualifier."""

    match = _SAFE_TRAILING_FRANCE_QUALIFIER.fullmatch(raw_location)
    if match is None:
        return None
    raw_place = match.group("place")
    place_clauses = [
        clause.strip()
        for clause in _LOCATION_CLAUSE_SEPARATOR.split(raw_place)
        if clause.strip()
    ]
    if len(place_clauses) != 1:
        return None
    evidence = _bounded_location_evidence(normalize_location(raw_location))
    return evidence if evidence.kind == "place" else None


def _standalone_preposition_evidence(key: str) -> _LocationEvidence | None:
    """Interpret only explicit ``à`` place and ``en`` scope clause grammar."""

    preposition, separator, remainder = key.partition(" ")
    if not separator:
        return None
    if preposition == "a":
        return _bounded_location_evidence(remainder)
    if preposition == "en":
        evidence = _evidence_for_key(remainder)
        if evidence.kind == "non_city":
            return evidence
        return _LocationEvidence("unknown")
    return None


def _remote_clause_evidence(raw_clause: str) -> _LocationEvidence:
    preposition_match = _REMOTE_PREFIX_PREPOSITION.fullmatch(raw_clause.strip())
    if preposition_match is not None:
        preposition = normalize_location(preposition_match.group("preposition"))
        candidate = normalize_location(preposition_match.group("place"))
        if _is_remote_descriptor_key(candidate):
            return _LocationEvidence("remote_descriptor")
        evidence = _bounded_location_evidence(candidate)
        if preposition == "en" and evidence.kind != "non_city":
            return _LocationEvidence("remote_descriptor")
        return evidence

    prefix_match = _REMOTE_MODE_PREFIX.fullmatch(raw_clause.strip())
    if prefix_match is not None:
        tail = normalize_location(prefix_match.group("tail") or "")
        if not tail or _is_remote_descriptor_key(tail):
            return _LocationEvidence("remote_descriptor")
        direct_scope = _evidence_for_key(tail)
        if direct_scope.kind == "non_city":
            return direct_scope
        return _LocationEvidence("remote_descriptor")

    suffix_match = _REMOTE_SUFFIX.fullmatch(raw_clause.strip())
    if suffix_match is not None:
        return _bounded_location_evidence(
            normalize_location(suffix_match.group("place"))
        )
    return _LocationEvidence("unknown")


def _bounded_location_evidence(key: str) -> _LocationEvidence:
    if (
        not key
        or _is_unknown_location(key)
        or _has_remote_qualifier(key.split())
        or _REMOTE_RESIDUAL_TOKENS.intersection(key.split())
        or key in _REMOTE_SCOPE_KEYS
    ):
        return _LocationEvidence("remote_descriptor")
    return _evidence_for_key(key)


def _evidence_for_key(key: str) -> _LocationEvidence:
    if _is_unknown_location(key):
        return _LocationEvidence("unknown")
    if key in _COUNTRY_LOCATION_KEYS or key in _REGION_LOCATION_KEYS:
        return _LocationEvidence("non_city", key)
    return _LocationEvidence("place", key)


def _is_remote_descriptor_key(key: str) -> bool:
    tokens = key.split()
    return bool(tokens) and all(
        token.isdigit() or token in _REMOTE_DESCRIPTOR_TOKENS for token in tokens
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
        "accord",
        "accords",
        "alternatif",
        "alternative",
        "complet",
        "complete",
        "convenir",
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
        "la",
        "monde",
        "occasionnel",
        "occasionnelle",
        "ponctuel",
        "ponctuelle",
        "pourcent",
        "par",
        "partiel",
        "partielle",
        "possible",
        "regulier",
        "reguliere",
        "remote",
        "semaine",
        "selon",
        "teletravail",
        "total",
        "totale",
        "worldwide",
    }
)
_REMOTE_RESIDUAL_TOKENS = _REMOTE_DESCRIPTOR_TOKENS - {"a", "en"}
_REMOTE_SCOPE_KEYS = frozenset({"europe", "international", "monde", "worldwide"})
_LOCATION_CLAUSE_SEPARATOR = re.compile(r"\s*(?:[,/|;()]|\s[-–—]\s)\s*")
_SAFE_TRAILING_FRANCE_QUALIFIER = re.compile(
    r"^\s*(?P<place>.+?)(?:\s*,\s*france|\s*\(\s*france\s*\)|"
    r"\s+[-–—]\s+france)\s*$",
    re.IGNORECASE,
)
_REMOTE_CADENCE_SLASH = re.compile(r"\b(jours?)\s*/\s*(semaine)\b", re.IGNORECASE)
_DEPARTMENT_CLAUSE = re.compile(r"(?:0?[1-9]|[1-9][0-9]|2[ab]|97[1-6])")
_REMOTE_MODE_PATTERN = r"(?:remote|t[eé]l[eé]travail|hybrid|hybride|[aà]\s+distance)"
_REMOTE_PERCENTAGE_PATTERN = r"(?:100(?:\s*(?:%|pourcent))?|\d{1,2}\s*(?:%|pourcent))"
_REMOTE_LEADING_MODIFIER_PATTERN = rf"(?:en|full|{_REMOTE_PERCENTAGE_PATTERN})"
_REMOTE_TRAILING_MODIFIER_PATTERN = (
    r"(?:partiel|partielle|possible|flexible|complet|complete|total|totale|"
    r"occasionnel|occasionnelle|ponctuel|ponctuelle|regulier|reguliere|"
    r"selon\s+accords?|[aà]\s+convenir|"
    r"europe|international|monde|worldwide|"
    rf"{_REMOTE_PERCENTAGE_PATTERN}|\d+\s+jours?(?:\s+par\s+semaine)?)"
)
_REMOTE_QUALIFIER_PATTERN = (
    rf"(?:{_REMOTE_LEADING_MODIFIER_PATTERN}\s+)*"
    rf"{_REMOTE_MODE_PATTERN}"
    rf"(?:\s+{_REMOTE_TRAILING_MODIFIER_PATTERN})*"
)
_REMOTE_PREFIX_PREPOSITION = re.compile(
    rf"^(?:{_REMOTE_QUALIFIER_PATTERN})\s+"
    rf"(?P<preposition>[aà]|en)\s+(?P<place>.+)$",
    re.IGNORECASE,
)
_REMOTE_MODE_PREFIX = re.compile(
    rf"^(?:{_REMOTE_LEADING_MODIFIER_PATTERN}\s+)*"
    rf"{_REMOTE_MODE_PATTERN}(?:\s+(?P<tail>.+))?$",
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
