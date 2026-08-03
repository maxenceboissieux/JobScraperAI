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


@pytest.mark.parametrize(
    "company",
    [
        "Non spécifié",
        "Non précisé",
        "Non renseignée",
        "Non communiquée",
        "Entreprise confidentielle",
        "N/C",
        "SAS",
        "Société Anonyme",
        "Company",
    ],
)
def test_unknown_or_legal_only_company_never_classifies_duplicates(
    company: str,
) -> None:
    """Fails if placeholder company names collapse unrelated source listings."""

    left = Job("Développeur Python", company, "Paris")
    right = Job("Développeur Python", company, "Paris")

    expected = DuplicateDecision("none", 1.0, ("entreprise_non_explicite",))
    assert classify_duplicate(left, right) == expected
    assert classify_duplicate(right, left) == expected


def test_company_with_a_trailing_long_legal_form_remains_explicit() -> None:
    """Fails if legal-form cleanup discards a meaningful company name."""

    left = Job("Développeur Python", "Acme Société Anonyme", "Paris")
    right = Job("Développeur Python", "ACME", "Paris")

    expected = DuplicateDecision(
        "confirmed",
        1.0,
        ("entreprise_identique", "lieu_identique", "titre_confirme"),
    )
    assert classify_duplicate(left, right) == expected
    assert classify_duplicate(right, left) == expected


@pytest.mark.parametrize(
    "location",
    [
        "France",
        "Belgique",
        "Télétravail",
        "Télétravail partiel",
        "Full remote",
        "Remote Europe",
        "100% télétravail",
        "À distance",
        "Hybride 2 jours par semaine",
        "Hybride 2 jours/semaine",
        "Télétravail 2 jours/semaine",
        "National",
        "Nationale",
        "Île-de-France",
    ],
)
def test_unknown_location_cannot_confirm_an_exact_title(location: str) -> None:
    """Fails if a country-level placeholder is treated as an explicit city."""

    left = Job("Développeur Python", "Acme", location)
    right = Job("Développeur Python", "ACME", location)

    expected = DuplicateDecision("none", 1.0, ("lieu_non_explicite",))
    assert classify_duplicate(left, right) == expected
    assert classify_duplicate(right, left) == expected


def test_unknown_location_can_only_support_a_thresholded_possible_match() -> None:
    """Fails if unknown location either blocks all candidates or confirms them."""

    left = Job("Développeur Python", "Acme", "Non spécifié")
    right = Job("Développeur Python Backend", "ACME", "Paris")

    expected = DuplicateDecision(
        "possible",
        pytest.approx(0.8181818181818182),
        ("entreprise_identique", "lieu_compatible", "titre_proche"),
    )
    assert classify_duplicate(left, right) == expected
    assert classify_duplicate(right, left) == expected


@pytest.mark.parametrize(
    "remote_location",
    [
        "Full remote",
        "Télétravail partiel",
        "Hybride 2 jours par semaine",
        "Hybride 2 jours/semaine",
        "Télétravail 2 jours/semaine",
        "Remote Europe",
    ],
)
def test_embedded_remote_marker_can_only_support_a_possible_match(
    remote_location: str,
) -> None:
    """Fails if remote-only labels are mistaken for an explicit city."""

    left = Job("Développeur Python", "Acme", remote_location)
    right = Job("Développeur Python Backend", "ACME", "Paris")

    expected = DuplicateDecision(
        "possible",
        pytest.approx(0.8181818181818182),
        ("entreprise_identique", "lieu_compatible", "titre_proche"),
    )
    assert classify_duplicate(left, right) == expected
    assert classify_duplicate(right, left) == expected


def test_city_with_remote_qualifier_confirms_when_city_evidence_agrees() -> None:
    """Fails if a remote qualifier hides an otherwise identical explicit city."""

    left = Job("Développeur Python", "Acme", "Paris / télétravail")
    right = Job("Développeur Python", "ACME", "Paris")

    expected = DuplicateDecision(
        "confirmed",
        1.0,
        ("entreprise_identique", "lieu_identique", "titre_confirme"),
    )
    assert classify_duplicate(left, right) == expected
    assert classify_duplicate(right, left) == expected


def test_city_with_remote_qualifier_vetoes_a_different_explicit_city() -> None:
    """Fails if a remote qualifier lets Paris and Lyon form a possible match."""

    left = Job("Développeur Python", "Acme", "Paris / télétravail")
    right = Job("Développeur Python Backend", "ACME", "Lyon")

    expected = DuplicateDecision(
        "none", pytest.approx(0.8181818181818182), ("villes_incompatibles",)
    )
    assert classify_duplicate(left, right) == expected
    assert classify_duplicate(right, left) == expected


@pytest.mark.parametrize(
    "qualified_location",
    [
        "Paris / télétravail",
        "Paris | Full remote",
        "Paris ; hybride 2 jours par semaine",
        "Paris (télétravail partiel)",
        "Paris - remote",
        "Paris – à distance",
        "Paris télétravail",
        "Remote Paris",
        "Paris hybride 2 jours par semaine",
        "Hybride 2 jours par semaine Paris",
        "Paris 100% télétravail",
        "100% télétravail Paris",
        "Paris 80% télétravail",
        "80% télétravail Paris",
        "Télétravail possible Paris",
        "Paris télétravail flexible",
        "Remote Europe Paris",
        "Paris remote Europe",
    ],
)
def test_structural_and_bounded_remote_qualifiers_retain_paris_evidence(
    qualified_location: str,
) -> None:
    """Fails if a safely bounded remote clause hides or pollutes Paris."""

    qualified = Job("Développeur Python", "Acme", qualified_location)
    paris = Job("Développeur Python", "ACME", "Paris")
    lyon = Job("Développeur Python Backend", "ACME", "Lyon")

    confirmed = DuplicateDecision(
        "confirmed",
        1.0,
        ("entreprise_identique", "lieu_identique", "titre_confirme"),
    )
    vetoed = DuplicateDecision(
        "none", pytest.approx(0.8181818181818182), ("villes_incompatibles",)
    )
    assert classify_duplicate(qualified, paris) == confirmed
    assert classify_duplicate(paris, qualified) == confirmed
    assert classify_duplicate(qualified, lyon) == vetoed
    assert classify_duplicate(lyon, qualified) == vetoed


def test_internal_place_hyphens_survive_remote_clause_parsing() -> None:
    """Fails if descriptor cleanup removes words inside a hyphenated city name."""

    qualified = Job("Développeur Python", "Acme", "Châlons-en-Champagne / télétravail")
    same_city = Job("Développeur Python", "ACME", "Châlons-en-Champagne")
    other_city = Job("Développeur Python Backend", "ACME", "Châlons-sur-Marne")

    confirmed = DuplicateDecision(
        "confirmed",
        1.0,
        ("entreprise_identique", "lieu_identique", "titre_confirme"),
    )
    vetoed = DuplicateDecision(
        "none", pytest.approx(0.8181818181818182), ("villes_incompatibles",)
    )
    assert classify_duplicate(qualified, same_city) == confirmed
    assert classify_duplicate(same_city, qualified) == confirmed
    assert classify_duplicate(qualified, other_city) == vetoed
    assert classify_duplicate(other_city, qualified) == vetoed


@pytest.mark.parametrize(
    "location",
    [
        "Paris / Lyon / télétravail",
        "Paris remote Europe / télétravail",
        "Paris flexible / remote",
        "Remote / Europe",
        "Télétravail / partiel",
        "Remote-sur-Mer",
    ],
)
def test_ambiguous_remote_labels_fail_closed_without_inventing_a_city(
    location: str,
) -> None:
    """Fails if an uncertain mixed label becomes explicit place evidence."""

    left = Job("Développeur Python", "Acme", location)
    right = Job("Développeur Python", "ACME", location)

    expected = DuplicateDecision("none", 1.0, ("lieu_non_explicite",))
    assert classify_duplicate(left, right) == expected
    assert classify_duplicate(right, left) == expected


@pytest.mark.parametrize(
    "location",
    [
        "Remotely",
        "Hybrideville",
        "Télétravailleur-sur-Loire",
    ],
)
def test_near_remote_words_remain_explicit_place_labels(location: str) -> None:
    """Fails if substring matching turns a near-marker place into remote-only."""

    left = Job("Développeur Python", "Acme", location)
    same = Job("Développeur Python", "ACME", location)
    different = Job("Développeur Python Backend", "ACME", "Paris")

    assert classify_duplicate(left, same) == DuplicateDecision(
        "confirmed",
        1.0,
        ("entreprise_identique", "lieu_identique", "titre_confirme"),
    )
    vetoed = DuplicateDecision(
        "none", pytest.approx(0.8181818181818182), ("villes_incompatibles",)
    )
    assert classify_duplicate(left, different) == vetoed
    assert classify_duplicate(different, left) == vetoed


def test_remote_qualified_countries_preserve_country_incompatibility() -> None:
    """Fails if removing remote clauses erases incompatible country evidence."""

    france = Job("Développeur Python", "Acme", "France / remote")
    belgium = Job("Développeur Python Backend", "ACME", "Belgique / remote")

    expected = DuplicateDecision(
        "none", pytest.approx(0.8181818181818182), ("lieux_incompatibles",)
    )
    assert classify_duplicate(france, belgium) == expected
    assert classify_duplicate(belgium, france) == expected


def test_remote_qualified_country_remains_non_explicit() -> None:
    """Fails if a country plus a remote clause becomes confirmation evidence."""

    left = Job("Développeur Python", "Acme", "France / remote")
    right = Job("Développeur Python", "ACME", "France")

    expected = DuplicateDecision("none", 1.0, ("lieu_non_explicite",))
    assert classify_duplicate(left, right) == expected
    assert classify_duplicate(right, left) == expected


def test_different_country_labels_are_not_location_compatible() -> None:
    """Fails if two country-level labels can form a cross-country candidate."""

    left = Job("Développeur Python", "Acme", "France")
    right = Job("Développeur Python Backend", "ACME", "Belgique")

    expected = DuplicateDecision(
        "none", pytest.approx(0.8181818181818182), ("lieux_incompatibles",)
    )
    assert classify_duplicate(left, right) == expected
    assert classify_duplicate(right, left) == expected


def test_saint_denis_variants_are_different_explicit_places_in_both_orders() -> None:
    """Fails if token-subset location matching merges distinct named places."""

    left = Job("Développeur Python", "Acme", "Saint-Denis")
    right = Job("Développeur Python", "ACME", "Saint-Denis-sur-Loire")

    expected = DuplicateDecision("none", 1.0, ("villes_incompatibles",))
    assert classify_duplicate(left, right) == expected
    assert classify_duplicate(right, left) == expected


def test_sr_and_jr_seniority_abbreviations_veto_matching_in_both_orders() -> None:
    """Fails if common seniority abbreviations leave incompatible jobs mergeable."""

    left = Job("Data Engineer Sr", "Acme", "Paris")
    right = Job("Data Engineer Jr", "ACME", "Paris")

    expected = DuplicateDecision(
        "none", pytest.approx(0.9375), ("seniorite_incompatible",)
    )
    assert classify_duplicate(left, right) == expected
    assert classify_duplicate(right, left) == expected


def test_compound_seniority_uses_the_highest_effective_level_in_both_orders() -> None:
    """Fails if a compound title depends on marker order instead of effective level."""

    left = Job("Data Engineer Senior Lead", "Acme", "Paris")
    right = Job("Data Engineer Senior", "ACME", "Paris")

    expected = DuplicateDecision(
        "none", pytest.approx(0.8888888888888888), ("seniorite_incompatible",)
    )
    assert classify_duplicate(left, right) == expected
    assert classify_duplicate(right, left) == expected


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
