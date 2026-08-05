"""Generate the bundled French metropolitan commune reference snapshot."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any
from urllib.request import urlopen

EPCI_GROUPS = (
    ("grand_paris", "Métropole du Grand Paris", "Paris", "200054781", 130),
    (
        "aix_marseille_provence",
        "Métropole d'Aix-Marseille-Provence",
        "Marseille",
        "200054807",
        92,
    ),
    ("lille", "Métropole Européenne de Lille", "Lille", "200093201", 95),
    ("bordeaux", "Bordeaux Métropole", "Bordeaux", "243300316", 28),
    ("toulouse", "Toulouse Métropole", "Toulouse", "243100518", 37),
    ("nantes", "Nantes Métropole", "Nantes", "244400404", 24),
    ("nice_cote_d_azur", "Métropole Nice Côte d'Azur", "Nice", "200030195", 51),
    (
        "montpellier",
        "Montpellier Méditerranée Métropole",
        "Montpellier",
        "243400017",
        31,
    ),
    ("strasbourg", "Eurométropole de Strasbourg", "Strasbourg", "246700488", 33),
)

LYON_GROUP = (
    "lyon",
    "Métropole de Lyon",
    "Lyon",
    "200046977",
    58,
)

ALIASES = {
    "grand_paris": ["Paris", "Grand Paris", "Métropole du Grand Paris"],
    "aix_marseille_provence": [
        "Marseille",
        "Aix-Marseille",
        "Aix-Marseille-Provence",
        "Métropole d'Aix-Marseille-Provence",
    ],
    "lyon": ["Lyon", "Grand Lyon", "Métropole de Lyon"],
    "lille": ["Lille", "Métropole Européenne de Lille"],
    "bordeaux": ["Bordeaux", "Bordeaux Métropole"],
    "toulouse": ["Toulouse", "Toulouse Métropole"],
    "nantes": ["Nantes", "Nantes Métropole"],
    "nice_cote_d_azur": ["Nice", "Nice Côte d'Azur", "Métropole Nice Côte d'Azur"],
    "montpellier": ["Montpellier", "Montpellier Méditerranée Métropole"],
    "strasbourg": ["Strasbourg", "Eurométropole de Strasbourg"],
}

LYON_OFFICIAL_NAMES = (
    "Albigny-sur-Saône",
    "Bron",
    "Cailloux-sur-Fontaines",
    "Caluire-et-Cuire",
    "Champagne-au-Mont-d'Or",
    "Charbonnières-les-Bains",
    "Charly",
    "Chassieu",
    "Collonges-au-Mont-d'Or",
    "Corbas",
    "Couzon-au-Mont-d'Or",
    "Craponne",
    "Curis-au-Mont-d'Or",
    "Dardilly",
    "Décines-Charpieu",
    "Écully",
    "Feyzin",
    "Fleurieu-sur-Saône",
    "Fontaines-Saint-Martin",
    "Fontaines-sur-Saône",
    "Francheville",
    "Genay",
    "Givors",
    "Grigny-sur-Rhône",
    "Irigny",
    "Jonage",
    "La Mulatière",
    "La Tour-de-Salvagny",
    "Limonest",
    "Lissieu",
    "Lyon",
    "Marcy-l'Étoile",
    "Meyzieu",
    "Mions",
    "Montanay",
    "Neuville-sur-Saône",
    "Oullins-Pierre-Bénite",
    "Poleymieux-au-Mont-d'Or",
    "Quincieux",
    "Rillieux-la-Pape",
    "Rochetaillée-sur-Saône",
    "Saint-Cyr-au-Mont-d'Or",
    "Saint-Didier-au-Mont-d'Or",
    "Saint-Fons",
    "Saint-Genis-Laval",
    "Saint-Genis-les-Ollières",
    "Saint-Germain-au-Mont-d'Or",
    "Saint-Priest",
    "Saint-Romain-au-Mont-d'Or",
    "Sainte-Foy-lès-Lyon",
    "Sathonay-Camp",
    "Sathonay-Village",
    "Solaize",
    "Tassin-la-Demi-Lune",
    "Vaulx-en-Velin",
    "Vénissieux",
    "Vernaison",
    "Villeurbanne",
)

GEO_API_URL = "https://geo.api.gouv.fr/epcis/{code}/communes?fields=nom,code"
LYON_SOURCE_URL = "https://www.grandlyon.com/metropole/les-58-communes-de-la-metropole"
_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")


def _normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(
        character for character in normalized if not unicodedata.combining(character)
    ).casefold()
    return " ".join(_NON_ALPHANUMERIC.sub(" ", ascii_value).split())


def _fetch_communes(epci_code: str) -> list[dict[str, str]]:
    source_url = GEO_API_URL.format(code=epci_code)
    with urlopen(source_url, timeout=30) as response:
        raw_rows = json.load(response)
    if not isinstance(raw_rows, list):
        raise ValueError(f"Unexpected Geo API response for EPCI {epci_code}")
    try:
        communes = [
            {"insee_code": str(row["code"]), "name": str(row["nom"])}
            for row in raw_rows
        ]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"Invalid commune data for EPCI {epci_code}") from exc
    return sorted(
        communes, key=lambda commune: (commune["insee_code"], commune["name"])
    )


def _build_group(group: tuple[str, str, str, str, int]) -> dict[str, Any]:
    key, official_name, city_center, epci_code, expected_count = group
    communes = _fetch_communes(epci_code)
    names = {_normalize_name(commune["name"]) for commune in communes}
    if len(communes) != expected_count:
        raise ValueError(
            f"EPCI {epci_code} has {len(communes)} communes, expected {expected_count}"
        )
    if _normalize_name(city_center) not in names:
        raise ValueError(f"EPCI {epci_code} does not contain {city_center}")
    source_url = GEO_API_URL.format(code=epci_code)
    if key == "lyon":
        official_names = {_normalize_name(name) for name in LYON_OFFICIAL_NAMES}
        if names != official_names:
            raise ValueError(
                "Lyon commune list differs from the official Grand Lyon list"
            )
        source_url = LYON_SOURCE_URL
    return {
        "key": key,
        "official_name": official_name,
        "city_center": city_center,
        "activation_aliases": ALIASES[key],
        "epci_code": epci_code,
        "source_url": source_url,
        "machine_readable_source_url": GEO_API_URL.format(code=epci_code),
        "communes": communes,
    }


def generate_snapshot(output: Path) -> None:
    groups = [_build_group(group) for group in (*EPCI_GROUPS, LYON_GROUP)]
    payload = {"reference_date": "2026-01-01", "groups": groups}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("src/jobscraper/data/french_metropolises.json"),
        help="path for the generated JSON snapshot",
    )
    args = parser.parse_args()
    generate_snapshot(args.output)


if __name__ == "__main__":
    main()
