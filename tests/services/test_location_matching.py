from __future__ import annotations

import json
from importlib import resources

import pytest

from jobscraper.services import location_matching

EXPECTED_COUNTS = {
    "grand_paris": 130,
    "aix_marseille_provence": 92,
    "lyon": 58,
    "lille": 95,
    "bordeaux": 28,
    "toulouse": 37,
    "nantes": 24,
    "nice_cote_d_azur": 51,
    "montpellier": 31,
    "strasbourg": 33,
}

EXPECTED_CENTERS = {
    "grand_paris": "Paris",
    "aix_marseille_provence": "Marseille",
    "lyon": "Lyon",
    "lille": "Lille",
    "bordeaux": "Bordeaux",
    "toulouse": "Toulouse",
    "nantes": "Nantes",
    "nice_cote_d_azur": "Nice",
    "montpellier": "Montpellier",
    "strasbourg": "Strasbourg",
}


def test_bundled_metropole_snapshot_has_expected_groups_and_counts() -> None:
    groups = {group.key: group for group in location_matching._METROPOLES}

    assert {
        key: len(group.communes) for key, group in groups.items()
    } == EXPECTED_COUNTS
    assert {key: group.city_center for key, group in groups.items()} == {
        key: location_matching.normalize_location(value)
        for key, value in EXPECTED_CENTERS.items()
    }
    assert all(group.city_center in group.communes for group in groups.values())


def test_reference_validation_rejects_duplicate_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource = resources.files("jobscraper.data").joinpath("french_metropolises.json")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    duplicate = payload["groups"][0]["activation_aliases"][0]
    payload["groups"][1]["activation_aliases"].append(duplicate)
    monkeypatch.setattr(location_matching, "_read_payload", lambda: payload)

    with pytest.raises(location_matching.LocationReferenceError, match="alias"):
        location_matching._load_metropolises()


def test_snapshot_is_valid_json_package_data() -> None:
    resource = resources.files("jobscraper.data").joinpath("french_metropolises.json")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    assert payload["reference_date"] == "2026-01-01"
