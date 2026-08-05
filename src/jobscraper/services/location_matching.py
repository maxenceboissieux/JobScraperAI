"""Validated access to the bundled French metropolitan reference data."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from importlib import resources
from types import MappingProxyType
from typing import Any

from jobscraper.services.normalization import normalize_location

_INSEE_CODE = re.compile(r"^(?:[0-9]{5}|2[AB][0-9]{3})$")


class LocationReferenceError(RuntimeError):
    """Raised when bundled metropolitan reference data is invalid."""


@dataclass(frozen=True)
class Metropole:
    key: str
    official_name: str
    city_center: str
    activation_aliases: frozenset[str]
    communes: frozenset[str]


@dataclass(frozen=True)
class _MetropoleSchema:
    commune_count: int
    epci_code: str
    source_url: str

    @property
    def machine_readable_source_url(self) -> str:
        return (
            f"https://geo.api.gouv.fr/epcis/{self.epci_code}/communes"
            "?fields=nom,code"
        )


_EXPECTED_SCHEMA = MappingProxyType(
    {
        "grand_paris": _MetropoleSchema(
            130,
            "200054781",
            "https://geo.api.gouv.fr/epcis/200054781/communes?fields=nom,code",
        ),
        "aix_marseille_provence": _MetropoleSchema(
            92,
            "200054807",
            "https://geo.api.gouv.fr/epcis/200054807/communes?fields=nom,code",
        ),
        "lyon": _MetropoleSchema(
            58,
            "200046977",
            "https://www.grandlyon.com/metropole/les-58-communes-de-la-metropole",
        ),
        "lille": _MetropoleSchema(
            95,
            "200093201",
            "https://geo.api.gouv.fr/epcis/200093201/communes?fields=nom,code",
        ),
        "bordeaux": _MetropoleSchema(
            28,
            "243300316",
            "https://geo.api.gouv.fr/epcis/243300316/communes?fields=nom,code",
        ),
        "toulouse": _MetropoleSchema(
            37,
            "243100518",
            "https://geo.api.gouv.fr/epcis/243100518/communes?fields=nom,code",
        ),
        "nantes": _MetropoleSchema(
            24,
            "244400404",
            "https://geo.api.gouv.fr/epcis/244400404/communes?fields=nom,code",
        ),
        "nice_cote_d_azur": _MetropoleSchema(
            51,
            "200030195",
            "https://geo.api.gouv.fr/epcis/200030195/communes?fields=nom,code",
        ),
        "montpellier": _MetropoleSchema(
            31,
            "243400017",
            "https://geo.api.gouv.fr/epcis/243400017/communes?fields=nom,code",
        ),
        "strasbourg": _MetropoleSchema(
            33,
            "246700488",
            "https://geo.api.gouv.fr/epcis/246700488/communes?fields=nom,code",
        ),
    }
)


def _required_string(raw: dict[str, Any], field: str, context: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise LocationReferenceError(f"{context} field {field} must be a string")
    return value


def _read_payload() -> dict[str, Any]:
    resource = resources.files("jobscraper.data").joinpath("french_metropolises.json")
    try:
        value = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LocationReferenceError(
            "Bundled French metropole reference data is unreadable"
        ) from exc
    if not isinstance(value, dict):
        raise LocationReferenceError("Metropole reference root must be an object")
    return value


def _load_metropolises() -> tuple[Metropole, ...]:
    payload = _read_payload()
    if payload.get("reference_date") != "2026-01-01":
        raise LocationReferenceError("Metropole reference date must be 2026-01-01")
    raw_groups = payload.get("groups")
    if not isinstance(raw_groups, list) or len(raw_groups) != 10:
        raise LocationReferenceError("Metropole reference must contain 10 groups")

    result: list[Metropole] = []
    aliases_seen: set[str] = set()
    group_keys_seen: set[str] = set()
    for raw in raw_groups:
        if not isinstance(raw, dict):
            raise LocationReferenceError("Each metropole group must be an object")
        key = _required_string(raw, "key", "Metropole group")
        if key in group_keys_seen:
            raise LocationReferenceError(f"Metropole group key {key} is duplicated")
        expected = _EXPECTED_SCHEMA.get(key)
        if expected is None:
            raise LocationReferenceError(f"Metropole group key {key} is unexpected")
        group_keys_seen.add(key)

        official_name = _required_string(raw, "official_name", f"Metropole {key}")
        raw_city_center = _required_string(raw, "city_center", f"Metropole {key}")
        epci_code = _required_string(raw, "epci_code", f"Metropole {key}")
        source_url = _required_string(raw, "source_url", f"Metropole {key}")
        machine_source_url = _required_string(
            raw, "machine_readable_source_url", f"Metropole {key}"
        )
        if epci_code != expected.epci_code:
            raise LocationReferenceError(f"Metropole {key} has an invalid EPCI code")
        if (
            source_url != expected.source_url
            or machine_source_url != expected.machine_readable_source_url
        ):
            raise LocationReferenceError(f"Metropole {key} has invalid source metadata")

        raw_aliases = raw.get("activation_aliases")
        if not isinstance(raw_aliases, list) or not raw_aliases:
            raise LocationReferenceError(f"Metropole {key} aliases must be a list")
        normalized_aliases: list[str] = []
        for alias in raw_aliases:
            if not isinstance(alias, str):
                raise LocationReferenceError(f"Metropole {key} alias must be a string")
            normalized_alias = normalize_location(alias)
            if not normalized_alias:
                raise LocationReferenceError(f"Metropole {key} has an invalid alias")
            normalized_aliases.append(normalized_alias)
        aliases = frozenset(normalized_aliases)
        if len(aliases) != len(normalized_aliases):
            raise LocationReferenceError(f"Metropole {key} has duplicate aliases")

        commune_rows = raw.get("communes")
        if (
            not isinstance(commune_rows, list)
            or len(commune_rows) != expected.commune_count
        ):
            raise LocationReferenceError(
                f"Metropole {key} must contain {expected.commune_count} communes"
            )
        city_center = normalize_location(raw_city_center)
        codes: set[str] = set()
        communes: set[str] = set()
        for row in commune_rows:
            if not isinstance(row, dict):
                raise LocationReferenceError(f"Metropole {key} has an invalid commune")
            code = row.get("insee_code")
            raw_name = row.get("name")
            if not isinstance(code, str) or not isinstance(raw_name, str):
                raise LocationReferenceError(f"Metropole {key} has an invalid commune")
            normalized_code = code.upper()
            name = normalize_location(raw_name)
            if not _INSEE_CODE.fullmatch(normalized_code) or not name:
                raise LocationReferenceError(f"Metropole {key} has an invalid commune")
            if normalized_code in codes or name in communes:
                raise LocationReferenceError(f"Metropole {key} has duplicate communes")
            codes.add(normalized_code)
            communes.add(name)
        if not aliases or city_center not in aliases or city_center not in communes:
            raise LocationReferenceError(f"Metropole {key} is missing its city center")
        duplicate_aliases = aliases_seen.intersection(aliases)
        if duplicate_aliases:
            raise LocationReferenceError("Metropole activation alias is duplicated")
        aliases_seen.update(aliases)
        result.append(
            Metropole(
                key=key,
                official_name=official_name,
                city_center=city_center,
                activation_aliases=aliases,
                communes=frozenset(communes),
            )
        )
    if group_keys_seen != set(_EXPECTED_SCHEMA):
        raise LocationReferenceError("Metropole reference group keys are incomplete")
    return tuple(result)


_METROPOLES = _load_metropolises()

_BY_ALIAS = MappingProxyType(
    {
        alias: metropole
        for metropole in _METROPOLES
        for alias in metropole.activation_aliases
    }
)
_TRAILING_FRANCE_QUALIFIER = re.compile(
    r"(?:\s*,\s*france|\s+[-–—]\s+france|\s*\(\s*france\s*\))\s*$"
)
_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")
_KNOWN_CITY_NUMBER = re.compile(
    r"^(paris|lyon|marseille)\s+([0-9]{1,2})(er|e|eme)?"
    r"(?:\s+(arrondissement))?"
    r"(?:\s+(0?[1-9]|[1-9][0-9]|2[ab]|97[1-6]))?$"
)
_ARRONDISSEMENT_MAX = {"paris": 20, "lyon": 9, "marseille": 16}
_CITY_DEPARTMENT = {"paris": 75, "lyon": 69, "marseille": 13}


def _location_key(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(
        character for character in ascii_value if not unicodedata.combining(character)
    ).casefold()
    without_country = _TRAILING_FRANCE_QUALIFIER.sub("", ascii_value)
    preserved = " ".join(_NON_ALPHANUMERIC.sub(" ", without_country).split())
    match = _KNOWN_CITY_NUMBER.fullmatch(preserved)
    if match is None:
        return normalize_location(value)
    city, raw_number, ordinal, arrondissement, department = match.groups()
    number = int(raw_number)
    if (
        ordinal is None
        and arrondissement is None
        and department is None
        and number == _CITY_DEPARTMENT[city]
    ):
        return city
    return f"{city} {number}"


def _municipality_key(normalized: str) -> str:
    match = _KNOWN_CITY_NUMBER.fullmatch(normalized)
    if match is None:
        return normalized
    city, raw_number, _, _, _ = match.groups()
    number = int(raw_number)
    return city if 1 <= number <= _ARRONDISSEMENT_MAX[city] else normalized


def location_matches(candidate: str, requested: str) -> bool:
    """Match one job location against one municipal or metropolitan request."""

    requested_key = _location_key(requested)
    candidate_key = _location_key(candidate)
    metropole = _BY_ALIAS.get(requested_key)
    if metropole is None:
        return candidate_key == requested_key
    return _municipality_key(candidate_key) in metropole.communes
