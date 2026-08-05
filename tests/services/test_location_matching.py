from __future__ import annotations

import json
from importlib import resources
from typing import Any

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

EXPECTED_ALIASES = {
    "grand_paris": frozenset({"paris", "grand paris", "metropole du grand paris"}),
    "aix_marseille_provence": frozenset(
        {
            "marseille",
            "aix marseille",
            "aix marseille provence",
            "metropole d aix marseille provence",
        }
    ),
    "lyon": frozenset({"lyon", "grand lyon", "metropole de lyon"}),
    "lille": frozenset({"lille", "metropole europeenne de lille"}),
    "bordeaux": frozenset({"bordeaux", "bordeaux metropole"}),
    "toulouse": frozenset({"toulouse", "toulouse metropole"}),
    "nantes": frozenset({"nantes", "nantes metropole"}),
    "nice_cote_d_azur": frozenset(
        {"nice", "nice cote d azur", "metropole nice cote d azur"}
    ),
    "montpellier": frozenset({"montpellier", "montpellier mediterranee metropole"}),
    "strasbourg": frozenset({"strasbourg", "eurometropole de strasbourg"}),
}

EXPECTED_METADATA = {
    "grand_paris": (
        "200054781",
        "https://geo.api.gouv.fr/epcis/200054781/communes?fields=nom,code",
    ),
    "aix_marseille_provence": (
        "200054807",
        "https://geo.api.gouv.fr/epcis/200054807/communes?fields=nom,code",
    ),
    "lyon": (
        "200046977",
        "https://www.grandlyon.com/metropole/les-58-communes-de-la-metropole",
    ),
    "lille": (
        "200093201",
        "https://geo.api.gouv.fr/epcis/200093201/communes?fields=nom,code",
    ),
    "bordeaux": (
        "243300316",
        "https://geo.api.gouv.fr/epcis/243300316/communes?fields=nom,code",
    ),
    "toulouse": (
        "243100518",
        "https://geo.api.gouv.fr/epcis/243100518/communes?fields=nom,code",
    ),
    "nantes": (
        "244400404",
        "https://geo.api.gouv.fr/epcis/244400404/communes?fields=nom,code",
    ),
    "nice_cote_d_azur": (
        "200030195",
        "https://geo.api.gouv.fr/epcis/200030195/communes?fields=nom,code",
    ),
    "montpellier": (
        "243400017",
        "https://geo.api.gouv.fr/epcis/243400017/communes?fields=nom,code",
    ),
    "strasbourg": (
        "246700488",
        "https://geo.api.gouv.fr/epcis/246700488/communes?fields=nom,code",
    ),
}


def _snapshot_payload() -> dict[str, Any]:
    resource = resources.files("jobscraper.data").joinpath("french_metropolises.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def _rejects_payload(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> None:
    monkeypatch.setattr(location_matching, "_read_payload", lambda: payload)
    with pytest.raises(location_matching.LocationReferenceError):
        location_matching._load_metropolises()


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
    assert {
        key: group.activation_aliases for key, group in groups.items()
    } == EXPECTED_ALIASES


def test_bundled_snapshot_has_exact_published_metadata() -> None:
    payload = _snapshot_payload()
    groups = {group["key"]: group for group in payload["groups"]}

    assert {
        key: (group["epci_code"], group["source_url"]) for key, group in groups.items()
    } == EXPECTED_METADATA
    assert {
        key: group["machine_readable_source_url"] for key, group in groups.items()
    } == {
        key: f"https://geo.api.gouv.fr/epcis/{epci_code}/communes?fields=nom,code"
        for key, (epci_code, _) in EXPECTED_METADATA.items()
    }


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


def test_reference_validation_rejects_duplicate_group_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _snapshot_payload()
    groups = payload["groups"]
    groups[1]["key"] = groups[0]["key"]

    _rejects_payload(monkeypatch, payload)


def test_reference_validation_rejects_unknown_group_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _snapshot_payload()
    payload["groups"][0]["key"] = "unexpected_metropole"

    _rejects_payload(monkeypatch, payload)


def test_reference_validation_rejects_truncated_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _snapshot_payload()
    payload["groups"][0]["communes"].pop()

    _rejects_payload(monkeypatch, payload)


@pytest.mark.parametrize(
    "field",
    ["epci_code", "source_url", "machine_readable_source_url"],
)
def test_reference_validation_requires_source_metadata(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    payload = _snapshot_payload()
    del payload["groups"][0][field]

    _rejects_payload(monkeypatch, payload)


@pytest.mark.parametrize(
    ("group_index", "field", "wrong_value"),
    [
        (0, "epci_code", "000000000"),
        (0, "source_url", "https://example.com/not-the-official-source"),
        (
            0,
            "machine_readable_source_url",
            "https://example.com/not-the-geo-api-source",
        ),
        (
            9,
            "source_url",
            "https://geo.api.gouv.fr/epcis/200046977/communes?fields=nom,code",
        ),
    ],
)
def test_reference_validation_rejects_wrong_source_metadata(
    monkeypatch: pytest.MonkeyPatch,
    group_index: int,
    field: str,
    wrong_value: str,
) -> None:
    payload = _snapshot_payload()
    payload["groups"][group_index][field] = wrong_value

    _rejects_payload(monkeypatch, payload)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("key", True),
        ("official_name", 123),
        ("city_center", True),
        ("activation_aliases", ("Paris", "Grand Paris")),
        ("epci_code", 200054781),
        ("source_url", True),
        ("machine_readable_source_url", True),
    ],
)
def test_reference_validation_rejects_coercible_group_field_types(
    monkeypatch: pytest.MonkeyPatch, field: str, invalid_value: object
) -> None:
    payload = _snapshot_payload()
    payload["groups"][0][field] = invalid_value

    _rejects_payload(monkeypatch, payload)


def test_reference_validation_rejects_boolean_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _snapshot_payload()
    payload["groups"][0]["activation_aliases"][1] = True

    _rejects_payload(monkeypatch, payload)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [("insee_code", 92002), ("name", True)],
)
def test_reference_validation_rejects_coercible_commune_field_types(
    monkeypatch: pytest.MonkeyPatch, field: str, invalid_value: object
) -> None:
    payload = _snapshot_payload()
    payload["groups"][0]["communes"][1][field] = invalid_value

    _rejects_payload(monkeypatch, payload)


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
        ("Grand Paris", "Boulogne-Billancourt"),
        ("Métropole du Grand Paris", "Saint-Denis, France"),
        ("Marseille", "Aix-en-Provence - 13"),
        ("Aix-Marseille", "Aubagne"),
        ("Aix-Marseille-Provence", "Aubagne"),
        ("Métropole d'Aix-Marseille-Provence", "Aubagne"),
        ("Lyon", "Villeurbanne - 69"),
        ("Grand Lyon", "Bron"),
        ("Métropole de Lyon", "Bron"),
        ("Lille", "Roubaix"),
        ("Métropole Européenne de Lille", "Tourcoing"),
        ("Bordeaux", "Mérignac"),
        ("Bordeaux Métropole", "Mérignac"),
        ("Toulouse", "Blagnac"),
        ("Toulouse Métropole", "Blagnac"),
        ("Nantes", "Saint-Herblain"),
        ("Nantes Métropole", "Saint-Herblain"),
        ("Nice", "Cagnes-sur-Mer"),
        ("Nice Côte d'Azur", "Cagnes-sur-Mer"),
        ("Métropole Nice Côte d'Azur", "Cagnes-sur-Mer"),
        ("Montpellier", "Lattes"),
        ("Montpellier Méditerranée Métropole", "Lattes"),
        ("Strasbourg", "Schiltigheim"),
        ("Eurométropole de Strasbourg", "Schiltigheim"),
    ],
)
def test_every_declared_alias_expands_to_its_official_metropole(
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
    [
        ("Lyon 7e", "Bron"),
        ("Marseille 2e", "Aubagne"),
        ("Lyon 7e", "Lyon 8e"),
        ("Lyon 7e", "Lyon"),
    ],
)
def test_direct_arrondissement_requests_do_not_expand(
    requested: str, candidate: str
) -> None:
    assert not location_matches(candidate, requested)


@pytest.mark.parametrize(
    ("requested", "candidate"),
    [
        ("Lyon 7e", "Lyon 7ème arrondissement - 69"),
        ("Marseille 2", "Marseille 2e arrondissement (13)"),
        ("Paris 10", "Paris 10e, France"),
    ],
)
def test_direct_arrondissement_requests_match_only_the_same_arrondissement(
    requested: str, candidate: str
) -> None:
    assert location_matches(candidate, requested)


@pytest.mark.parametrize(
    ("center", "arrondissement"),
    [("Lyon", "Lyon 7"), ("Marseille", "Marseille 12"), ("Paris", "Paris 20")],
)
def test_unsuffixed_candidate_arrondissements_collapse_for_center_requests(
    center: str, arrondissement: str
) -> None:
    assert location_matches(arrondissement, center)


@pytest.mark.parametrize(
    ("center", "department_form", "member"),
    [
        ("Paris", "Paris 75", "Boulogne-Billancourt"),
        ("Lyon", "Lyon 69", "Bron"),
        ("Marseille", "Marseille 13", "Aubagne"),
    ],
)
def test_unsuffixed_city_department_forms_remain_center_locations(
    center: str, department_form: str, member: str
) -> None:
    assert location_matches(department_form, center)
    assert location_matches(member, department_form)


@pytest.mark.parametrize(
    ("center", "out_of_range"),
    [
        ("Lyon", "Lyon 10e"),
        ("Marseille", "Marseille 17e"),
        ("Paris", "Paris 21e"),
    ],
)
def test_ordinal_out_of_range_arrondissements_remain_excluded(
    center: str, out_of_range: str
) -> None:
    assert not location_matches(out_of_range, center)


@pytest.mark.parametrize("separator", ["–", "—", "/", ";"])
def test_punctuation_separated_departments_preserve_known_city_numbers(
    separator: str,
) -> None:
    out_of_range = f"Lyon 10 {separator} 69"

    assert not location_matches(out_of_range, "Lyon")
    assert not location_matches("Lyon", out_of_range)
    assert location_matches(out_of_range, "Lyon 10")
    assert location_matches(f"Lyon 7e {separator} 69", "Lyon 7e")


@pytest.mark.parametrize(
    ("center", "out_of_range"),
    [
        ("Lyon", "Lyon 10"),
        ("Marseille", "Marseille 17"),
        ("Paris", "Paris 21"),
        ("Lyon", "Lyon 99"),
    ],
)
def test_unsuffixed_out_of_range_forms_never_broaden_in_either_direction(
    center: str, out_of_range: str
) -> None:
    assert not location_matches(out_of_range, center)
    assert not location_matches(center, out_of_range)
    assert location_matches(out_of_range, out_of_range)
