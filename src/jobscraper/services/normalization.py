"""Stable comparison keys for titles, companies, and French locations."""

import re
import unicodedata

_GENDER_MARKER = re.compile(r"(?<![a-z0-9])[hf]\s*(?:/|-)\s*[hf](?![a-z0-9])")
_PARENTHESIZED_DEPARTMENT = re.compile(
    r"\s*\(\s*(?:0?[1-9]|[1-9][0-9]|2[ab]|97[1-6])\s*\)\s*$"
)
_SEPARATED_DEPARTMENT = re.compile(
    r"\s*(?:,|-)\s*(?:0?[1-9]|[1-9][0-9]|2[ab]|97[1-6])\s*$"
)
_DEPARTMENT_TOKEN = re.compile(r"^(?:0?[1-9]|[1-9][0-9]|2[ab]|97[1-6])$")
_EXACT_FRANCE = re.compile(r"^\s*france\s*$")
_TRAILING_FRANCE_QUALIFIER = re.compile(
    r"(?:\s*,\s*france|\s+-\s+france|\s*\(\s*france\s*\))\s*$"
)
_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")
_LEGAL_SUFFIXES = (
    ("entreprise", "unipersonnelle", "a", "responsabilite", "limitee"),
    ("societe", "par", "actions", "simplifiee"),
    ("societe", "a", "responsabilite", "limitee"),
    ("societe", "en", "commandite", "simple"),
    ("societe", "civile", "immobiliere"),
    ("societe", "en", "nom", "collectif"),
    ("societe", "anonyme"),
    ("s", "a", "r", "l", "u"),
    ("s", "a", "s", "u"),
    ("e", "u", "r", "l"),
    ("s", "a", "r", "l"),
    ("s", "a", "s"),
    ("s", "c", "a"),
    ("s", "c", "i"),
    ("l", "l", "c"),
    ("l", "t", "d"),
    ("i", "n", "c"),
    ("s", "n", "c"),
    ("gmbh",),
    ("sarl",),
    ("sasu",),
    ("sas",),
    ("eurl",),
    ("llc",),
    ("ltd",),
    ("inc",),
    ("snc",),
    ("sci",),
    ("sca",),
    ("s", "a"),
    ("sa",),
    ("b", "v"),
    ("g", "m", "b", "h"),
)


def normalize_text(value: str) -> str:
    """Return an accent-free, punctuation-insensitive comparison key.

    The cleanup deliberately removes only legal forms at the end of a value, so
    a name such as ``SAS Institute`` retains its meaningful first token.
    """

    ascii_value = _ascii_casefold(value)
    without_markers = _GENDER_MARKER.sub(" ", ascii_value)
    without_department = _PARENTHESIZED_DEPARTMENT.sub("", without_markers)
    without_department = _SEPARATED_DEPARTMENT.sub("", without_department)
    tokens = _NON_ALPHANUMERIC.sub(" ", without_department).split()
    return " ".join(_without_legal_suffix(tokens))


def normalize_title(value: str) -> str:
    """Normalize a job title while removing conventional H/F markers."""

    return normalize_text(value)


def normalize_company(value: str) -> str:
    """Normalize a company name while ignoring trailing legal forms."""

    return normalize_text(value)


def normalize_location(value: str) -> str:
    """Normalize a location without collapsing distinct city names.

    France is removed only when it is a separately-delimited city qualifier.
    Hyphenated region names such as ``Île-de-France`` keep their country token.
    """

    ascii_value = _ascii_casefold(value).strip()
    if _EXACT_FRANCE.fullmatch(ascii_value):
        return "france"
    without_country_qualifier = _TRAILING_FRANCE_QUALIFIER.sub("", ascii_value)
    tokens = normalize_text(without_country_qualifier).split()
    while tokens and _DEPARTMENT_TOKEN.fullmatch(tokens[-1]) is not None:
        tokens.pop()
    return " ".join(tokens)


def _ascii_casefold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(
        character for character in normalized if not unicodedata.combining(character)
    ).casefold()


def _without_legal_suffix(tokens: list[str]) -> list[str]:
    remaining = tokens
    while remaining:
        suffix = next(
            (
                candidate
                for candidate in _LEGAL_SUFFIXES
                if len(remaining) >= len(candidate)
                and tuple(remaining[-len(candidate) :]) == candidate
            ),
            None,
        )
        if suffix is None:
            break
        remaining = remaining[: -len(suffix)]
    return remaining
