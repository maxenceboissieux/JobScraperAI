"""Utilitaires de géocodage pour convertir les noms de villes en coordonnées."""

from typing import Dict, Optional, Tuple

import requests
from loguru import logger

# Cache des coordonnées pour éviter les appels répétés
_geocode_cache: Dict[str, Optional[Tuple[float, float]]] = {}

# Coordonnées pré-définies des grandes villes françaises
FRENCH_CITIES: Dict[str, Tuple[float, float]] = {
    "paris": (48.8566, 2.3522),
    "marseille": (43.2965, 5.3698),
    "lyon": (45.7640, 4.8357),
    "toulouse": (43.6047, 1.4442),
    "nice": (43.7102, 7.2620),
    "nantes": (47.2184, -1.5536),
    "strasbourg": (48.5734, 7.7521),
    "montpellier": (43.6108, 3.8767),
    "bordeaux": (44.8378, -0.5792),
    "lille": (50.6292, 3.0573),
    "rennes": (48.1173, -1.6778),
    "reims": (49.2583, 4.0317),
    "le havre": (49.4944, 0.1079),
    "saint-étienne": (45.4397, 4.3872),
    "toulon": (43.1242, 5.9280),
    "grenoble": (45.1885, 5.7245),
    "dijon": (47.3220, 5.0415),
    "angers": (47.4784, -0.5632),
    "nîmes": (43.8367, 4.3601),
    "villeurbanne": (45.7676, 4.8810),
    "clermont-ferrand": (45.7772, 3.0870),
    "le mans": (48.0061, 0.1996),
    "aix-en-provence": (43.5297, 5.4474),
    "brest": (48.3904, -4.4861),
    "tours": (47.3941, 0.6848),
    "amiens": (49.8941, 2.2958),
    "limoges": (45.8336, 1.2611),
    "annecy": (45.8992, 6.1294),
    "perpignan": (42.6986, 2.8956),
    "boulogne-billancourt": (48.8352, 2.2410),
    "metz": (49.1193, 6.1757),
    "besançon": (47.2378, 6.0241),
    "orléans": (47.9029, 1.9039),
    "rouen": (49.4432, 1.0999),
    "mulhouse": (47.7508, 7.3359),
    "caen": (49.1829, -0.3707),
    "nancy": (48.6921, 6.1844),
    "saint-denis": (48.9362, 2.3574),
    "argenteuil": (48.9472, 2.2467),
    "montreuil": (48.8638, 2.4483),
    "roubaix": (50.6942, 3.1746),
    "tourcoing": (50.7262, 3.1612),
    "avignon": (43.9493, 4.8055),
    "dunkerque": (51.0343, 2.3768),
    "poitiers": (46.5802, 0.3404),
    "courbevoie": (48.8966, 2.2522),
    "versailles": (48.8014, 2.1301),
    "colombes": (48.9226, 2.2526),
    "aulnay-sous-bois": (48.9326, 2.4922),
    "rueil-malmaison": (48.8769, 2.1894),
    "pau": (43.2951, -0.3708),
    "vitry-sur-seine": (48.7875, 2.3928),
    "calais": (50.9513, 1.8587),
    "la rochelle": (46.1603, -1.1511),
    "cannes": (43.5528, 7.0174),
    "antibes": (43.5808, 7.1239),
    "saint-maur-des-fossés": (48.7997, 2.4892),
    "levallois-perret": (48.8933, 2.2875),
    "issy-les-moulineaux": (48.8239, 2.2700),
    "neuilly-sur-seine": (48.8848, 2.2687),
    "cergy": (49.0364, 2.0634),
    "la défense": (48.8918, 2.2383),
}


def geocode(location: str) -> Optional[Tuple[float, float]]:
    """
    Convertit un nom de ville en coordonnées GPS.

    Args:
        location: Nom de la ville ou lieu

    Returns:
        Tuple (latitude, longitude) ou None si non trouvé
    """
    if not location:
        return None

    location_lower = location.lower().strip()

    # Vérifier le cache
    if location_lower in _geocode_cache:
        return _geocode_cache[location_lower]

    # Vérifier les villes pré-définies
    for city_name, coords in FRENCH_CITIES.items():
        if city_name in location_lower or location_lower in city_name:
            _geocode_cache[location_lower] = coords
            logger.debug(f"Géocodage (cache local): {location} -> {coords}")
            return coords

    # Utiliser Nominatim pour les autres villes
    coords = _nominatim_geocode(location)
    _geocode_cache[location_lower] = coords
    return coords


def _nominatim_geocode(location: str) -> Optional[Tuple[float, float]]:
    """
    Utilise l'API Nominatim (OpenStreetMap) pour géocoder.

    Args:
        location: Nom du lieu

    Returns:
        Tuple (latitude, longitude) ou None
    """
    try:
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            "q": f"{location}, France",
            "format": "json",
            "limit": 1,
            "countrycodes": "fr",
        }
        headers = {
            "User-Agent": "JobScraper/1.0 (job search aggregator)",
        }

        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data:
            lat = float(data[0]["lat"])
            lon = float(data[0]["lon"])
            logger.debug(f"Géocodage (Nominatim): {location} -> ({lat}, {lon})")
            return (lat, lon)

        logger.warning(f"Lieu non trouvé: {location}")
        return None

    except Exception as e:
        logger.warning(f"Erreur géocodage {location}: {e}")
        return None
