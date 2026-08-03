"""Tests for deterministic cross-source duplicate classification."""

from dataclasses import FrozenInstanceError, dataclass

import pytest

from jobscraper.services.deduplication import (
    DuplicateDecision,
    classify_duplicate,
    ordered_duplicate_pair_ids,
)


@dataclass(frozen=True)
class Job:
    """Minimal job-shaped input used to exercise the public classifier contract."""

    title: str
    company: str
    location: str


def test_classify_duplicate_confirms_identical_company_location_and_title() -> None:
    """Fails if equivalent source formatting cannot produce a confirmed match."""

    decision = classify_duplicate(
        Job("Développeur Python H/F", "ACME S.A.S.", "Paris (75)"),
        Job("Developpeur Python", "Acme", "Paris"),
    )

    assert decision == DuplicateDecision(
        kind="confirmed",
        score=1.0,
        reasons=("entreprise_identique", "lieu_identique", "titre_confirme"),
    )


def test_classify_duplicate_marks_close_titles_as_possible() -> None:
    """Fails if titles above the possible threshold are discarded instead of surfaced."""

    decision = classify_duplicate(
        Job("Développeur Python", "Acme", "Paris, France"),
        Job("Développeur Python Backend", "ACME", "Paris"),
    )

    assert decision.kind == "possible"
    assert decision.score == pytest.approx(0.8181818181818182)
    assert decision.reasons == (
        "entreprise_identique",
        "lieu_compatible",
        "titre_proche",
    )


def test_title_score_boundary_of_point_92_is_confirmed() -> None:
    """Fails if the inclusive confirmed threshold is moved above 0.92."""

    decision = classify_duplicate(
        Job("ingenieur plateforme data", "Acme", "Paris"),
        Job("ingenieur plateforme daxx", "Acme", "Paris"),
    )

    assert decision.score == pytest.approx(0.92)
    assert decision.kind == "confirmed"


def test_title_score_below_point_92_is_possible() -> None:
    """Fails if a near title below 0.92 is incorrectly auto-merged."""

    decision = classify_duplicate(
        Job("analyste plateforme data", "Acme", "Paris"),
        Job("analyste plateforme daxx", "Acme", "Paris"),
    )

    assert decision.score == pytest.approx(0.9166666666666666)
    assert decision.kind == "possible"


def test_title_score_boundary_of_point_78_is_possible() -> None:
    """Fails if the inclusive possible threshold is moved above 0.78."""

    decision = classify_duplicate(
        Job("a" * 50, "Acme", "Paris"),
        Job("a" * 39 + "b" * 11, "Acme", "Paris"),
    )

    assert decision.score == pytest.approx(0.78)
    assert decision.kind == "possible"


def test_title_score_below_point_78_is_not_a_possible_match() -> None:
    """Fails if titles below the possible threshold are exposed as candidates."""

    decision = classify_duplicate(
        Job("a" * 50, "Acme", "Paris"),
        Job("a" * 38 + "b" * 12, "Acme", "Paris"),
    )

    assert decision.score == pytest.approx(0.76)
    assert decision.kind == "none"
    assert decision.reasons == ("titre_insuffisant",)


def test_different_explicit_cities_force_no_match() -> None:
    """Fails if exact titles from different city vacancies are merged."""

    decision = classify_duplicate(
        Job("Développeur Python", "Acme", "Paris"),
        Job("Développeur Python", "Acme", "Lyon"),
    )

    assert decision.kind == "none"
    assert decision.reasons == ("villes_incompatibles",)


def test_incompatible_explicit_seniority_forces_no_match() -> None:
    """Fails if junior and senior vacancies are merged despite title similarity."""

    decision = classify_duplicate(
        Job("Développeur Python Senior", "Acme", "Paris"),
        Job("Développeur Python Junior", "Acme", "Paris"),
    )

    assert decision.kind == "none"
    assert decision.reasons == ("seniorite_incompatible",)


def test_classification_is_symmetric_and_decision_is_immutable() -> None:
    """Fails if source ordering changes a reciprocal duplicate decision."""

    left = Job("Développeur Python", "Acme S.A.S.", "Paris (75)")
    right = Job("Développeur Python Backend", "Acme", "Paris, France")

    decision = classify_duplicate(left, right)

    assert decision == classify_duplicate(right, left)
    with pytest.raises(FrozenInstanceError):
        decision.kind = "none"  # type: ignore[misc]


def test_ordered_duplicate_pair_ids_is_canonical_and_rejects_self_relations() -> None:
    """Fails if reciprocal persistence can create two rows for the same pair."""

    assert ordered_duplicate_pair_ids(8, 3) == (3, 8)
    with pytest.raises(ValueError, match="distinct"):
        ordered_duplicate_pair_ids(3, 3)
