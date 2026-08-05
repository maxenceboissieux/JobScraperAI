from __future__ import annotations

import json
from importlib import resources

import pytest

from jobscraper.services import location_matching
from jobscraper.services.location_matching import location_matches

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


def test_reference_validation_rejects_non_object_commune_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource = resources.files("jobscraper.data").joinpath("french_metropolises.json")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    payload["groups"][0]["communes"][0] = None
    monkeypatch.setattr(location_matching, "_read_payload", lambda: payload)

    with pytest.raises(
        location_matching.LocationReferenceError, match="invalid commune"
    ):
        location_matching._load_metropolises()


def test_snapshot_is_valid_json_package_data() -> None:
    resource = resources.files("jobscraper.data").joinpath("french_metropolises.json")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    assert payload["reference_date"] == "2026-01-01"


def test_alias_index_is_immutable() -> None:
    with pytest.raises(TypeError):
        location_matching._BY_ALIAS["test"] = location_matching._METROPOLES[0]


@pytest.mark.parametrize(
    ("requested", "candidate"),
    [
        ("Paris", "Boulogne-Billancourt - 92"),
        ("Métropole du Grand Paris", "Saint-Denis, France"),
        ("Marseille", "Aix-en-Provence - 13"),
        ("Aix-Marseille", "Aubagne"),
        ("Lyon", "Villeurbanne - 69"),
        ("Grand Lyon", "Bron"),
        ("Lille", "Roubaix"),
        ("Métropole Européenne de Lille", "Tourcoing"),
        ("Bordeaux", "Mérignac"),
        ("Toulouse", "Blagnac"),
        ("Nantes", "Saint-Herblain"),
        ("Nice", "Cagnes-sur-Mer"),
        ("Montpellier", "Lattes"),
        ("Strasbourg", "Schiltigheim"),
    ],
)
def test_city_centers_and_aliases_expand_to_official_metropole(
    requested: str, candidate: str
) -> None:
    assert location_matches(candidate, requested)


@pytest.mark.parametrize(
    ("requested", "candidate"),
    [
        ("Paris", "Melun"),
        ("Marseille", "Avignon"),
        ("Lyon", "Villefranche-sur-Saône"),
        ("Villeurbanne", "Bron"),
        ("Roubaix", "Lille"),
        ("Unknownville", "Paris"),
    ],
)
def test_metropole_matching_does_not_broaden_unrecognized_or_member_tags(
    requested: str, candidate: str
) -> None:
    assert not location_matches(candidate, requested)


@pytest.mark.parametrize(
    ("requested", "candidate"),
    [
        ("lyon", "Lyon 7e - 69"),
        ("Métropole de Lyon", "Lyon 7ème arrondissement, France"),
        ("Paris", "Paris 20e arrondissement - 75"),
        ("Marseille", "Marseille 16ème (13)"),
        ("MÉTROPOLE NICE CÔTE D'AZUR", "Nice - 06"),
        ("Villeurbanne", "VILLEURBANNE, France"),
    ],
)
def test_location_matching_handles_arrondissements_and_normalization(
    requested: str, candidate: str
) -> None:
    assert location_matches(candidate, requested)


@pytest.mark.parametrize(
    ("requested", "candidate"),
    [("Lyon", "Lyon 10e"), ("Marseille", "Marseille 17e"), ("Paris", "Paris 21e")],
)
def test_out_of_range_arrondissements_are_not_collapsed(
    requested: str, candidate: str
) -> None:
    assert not location_matches(candidate, requested)
