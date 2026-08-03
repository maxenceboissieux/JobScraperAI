"""Behavioral tests for duplicate-comparison normalization keys."""

import pytest

from jobscraper.services.normalization import (
    normalize_company,
    normalize_location,
    normalize_text,
    normalize_title,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Développeur Python H/F", "developpeur python"),
        ("  ACME S.A.S. ", "acme"),
        ("Paris (75)", "paris"),
    ],
)
def test_normalize_text_removes_source_formatting_noise(
    value: str, expected: str
) -> None:
    """Fails if accents, common suffixes, or presentation markers split matches."""

    assert normalize_text(value) == expected


def test_normalize_title_removes_gender_markers_without_dropping_words() -> None:
    """Fails if title punctuation leaves gender markers in the comparison key."""

    assert normalize_title("Ingénieur·e plateforme (H - F)") == "ingenieur e plateforme"


def test_normalize_company_removes_only_trailing_legal_suffixes() -> None:
    """Fails if legal-form cleanup erases a meaningful company-name token."""

    assert normalize_company("SAS Institute S.A.S.") == "sas institute"
    assert normalize_company("Acme SAS") == "acme"
    assert normalize_company("Acme Société Anonyme") == "acme"
    assert normalize_company("Société Anonyme") == ""


def test_normalize_location_removes_department_suffix_without_merging_cities() -> None:
    """Fails if departmental cleanup makes distinct city labels indistinguishable."""

    assert normalize_location("Boulogne-Billancourt - 92") == "boulogne billancourt"
    assert normalize_location("Paris 75") == "paris"
    assert normalize_location("Saint-Denis") != normalize_location(
        "Saint-Denis-sur-Loire"
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Paris, France", "paris"),
        ("Paris (France)", "paris"),
        ("France", "france"),
        ("Île-de-France", "ile de france"),
        ("Hauts-de-France", "hauts de france"),
    ],
)
def test_normalize_location_preserves_hyphenated_regions_and_strips_qualifiers(
    value: str, expected: str
) -> None:
    """Fails if country cleanup erases region names or leaves delimiters behind."""

    assert normalize_location(value) == expected
