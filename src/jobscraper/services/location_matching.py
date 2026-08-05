"""Validated access to the bundled French metropolitan reference data."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources
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
    for raw in raw_groups:
        if not isinstance(raw, dict):
            raise LocationReferenceError("Each metropole group must be an object")
        try:
            key = str(raw["key"])
            official_name = str(raw["official_name"])
            source_url = str(raw["source_url"])
            city_center = normalize_location(str(raw["city_center"]))
            aliases = frozenset(
                normalize_location(str(alias)) for alias in raw["activation_aliases"]
            )
            commune_rows = raw["communes"]
        except (KeyError, TypeError) as exc:
            raise LocationReferenceError("Metropole group fields are invalid") from exc
        if not key or not official_name or not source_url.startswith("https://"):
            raise LocationReferenceError("Metropole metadata is invalid")
        if not isinstance(commune_rows, list) or not commune_rows:
            raise LocationReferenceError(f"Metropole {key} has no communes")
        codes: set[str] = set()
        communes: set[str] = set()
        for row in commune_rows:
            if not isinstance(row, dict):
                raise LocationReferenceError(f"Metropole {key} has an invalid commune")
            code = str(row.get("insee_code", ""))
            name = normalize_location(str(row.get("name", "")))
            if not _INSEE_CODE.fullmatch(code.upper()) or not name:
                raise LocationReferenceError(f"Metropole {key} has an invalid commune")
            if code in codes or name in communes:
                raise LocationReferenceError(f"Metropole {key} has duplicate communes")
            codes.add(code)
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
    return tuple(result)


_METROPOLES = _load_metropolises()
