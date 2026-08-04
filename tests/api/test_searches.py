from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jobscraper.repositories.saved_searches import SavedSearchRepository

SEARCH_PAYLOAD = {
    "name": "Backend remote",
    "keywords": ["backend", "python"],
    "title": "Backend engineer",
    "location": "France",
    "radiusKm": 50,
    "contractTypes": ["cdi"],
    "experienceLevels": ["senior"],
    "workplaceTypes": ["remote"],
    "companies": ["Acme"],
    "excludeCompanies": ["Globex"],
    "salaryMin": 65_000,
    "sources": ["freework", "linkedin"],
    "active": True,
}


def test_create_and_list_saved_searches_on_a_clean_database(
    client: TestClient,
) -> None:
    """Fails if startup omits schema creation or request/response aliases drift."""
    created = client.post("/api/searches", json=SEARCH_PAYLOAD)

    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "Backend remote"
    assert body["radiusKm"] == 50
    assert body["contractTypes"] == ["cdi"]
    assert body["sources"] == ["freework", "linkedin"]
    assert "createdAt" in body
    assert "updatedAt" in body
    assert "radius_km" not in body

    listed = client.get("/api/searches")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [body["id"]]


def test_patch_saved_search_preserves_omitted_criteria(client: TestClient) -> None:
    """Fails if a partial edit resets fields that the request did not supply."""
    search_id = client.post("/api/searches", json=SEARCH_PAYLOAD).json()["id"]

    response = client.patch(
        f"/api/searches/{search_id}",
        json={"name": "Backend suspendu", "radiusKm": None, "active": False},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Backend suspendu"
    assert body["radiusKm"] is None
    assert body["keywords"] == ["backend", "python"]
    assert body["location"] == "France"
    assert body["sources"] == ["freework", "linkedin"]
    assert body["active"] is False


def test_search_list_can_filter_active_state(client: TestClient) -> None:
    """Fails if suspended searches cannot be separated from active searches."""
    active = client.post("/api/searches", json=SEARCH_PAYLOAD).json()
    suspended_payload = {**SEARCH_PAYLOAD, "name": "Suspendue", "active": False}
    suspended = client.post("/api/searches", json=suspended_payload).json()

    response = client.get("/api/searches", params={"active": "false"})

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [suspended["id"]]
    assert active["id"] != suspended["id"]


def test_unknown_search_patch_returns_404(client: TestClient) -> None:
    """Fails if an unknown public search ID is silently accepted."""
    response = client.patch(
        "/api/searches/00000000-0000-0000-0000-000000000000",
        json={"active": False},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "La recherche enregistrée n’existe pas."}


@pytest.mark.parametrize(
    "payload",
    [
        {**SEARCH_PAYLOAD, "name": "   "},
        {**SEARCH_PAYLOAD, "sources": []},
        {**SEARCH_PAYLOAD, "sources": ["unknown-source"]},
        {**SEARCH_PAYLOAD, "radiusKm": 0},
    ],
)
def test_invalid_search_payload_returns_422(
    client: TestClient, payload: dict[str, object]
) -> None:
    """Fails if malformed saved searches reach persistence."""
    response = client.post("/api/searches", json=payload)

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("contractTypes", ["permanent"]),
        ("experienceLevels", ["expert"]),
        ("workplaceTypes", ["anywhere"]),
    ],
)
def test_enum_like_search_criteria_are_validated_at_the_schema_boundary(
    client: TestClient, field: str, value: list[str]
) -> None:
    """Fails if domain validation escapes the route as a sanitized 500."""

    response = client.post("/api/searches", json={**SEARCH_PAYLOAD, field: value})

    assert response.status_code == 422


@pytest.mark.parametrize(
    "field",
    [
        "name",
        "keywords",
        "location",
        "contractTypes",
        "experienceLevels",
        "workplaceTypes",
        "companies",
        "excludeCompanies",
        "sources",
        "active",
    ],
)
def test_patch_rejects_null_for_non_nullable_saved_search_fields(
    client: TestClient, field: str
) -> None:
    """Fails if explicit JSON null is mistaken for an omitted patch field."""

    created = client.post("/api/searches", json=SEARCH_PAYLOAD).json()

    response = client.patch(f"/api/searches/{created['id']}", json={field: None})

    assert response.status_code == 422
    persisted = client.get("/api/searches").json()[0]
    assert persisted == created


@pytest.mark.parametrize("method", ["post", "patch"])
def test_duplicate_saved_search_sources_return_422(
    client: TestClient, method: str
) -> None:
    """Fails if duplicate sources survive with inconsistent retry/order behavior."""

    if method == "post":
        response = client.post(
            "/api/searches",
            json={**SEARCH_PAYLOAD, "sources": ["freework", "freework"]},
        )
    else:
        search_id = client.post("/api/searches", json=SEARCH_PAYLOAD).json()["id"]
        response = client.patch(
            f"/api/searches/{search_id}",
            json={"sources": ["linkedin", "linkedin"]},
        )

    assert response.status_code == 422


def test_search_persistence_failure_is_sanitized_and_next_request_works(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fails if a repository exception leaks secrets or poisons later sessions."""
    original = SavedSearchRepository.create
    calls = 0

    def fail_once(self: SavedSearchRepository, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("database-password=secret")
        return original(self, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(SavedSearchRepository, "create", fail_once)

    failed = client.post("/api/searches", json=SEARCH_PAYLOAD)
    recovered = client.post(
        "/api/searches", json={**SEARCH_PAYLOAD, "name": "Recovered"}
    )

    assert failed.status_code == 500
    assert failed.json() == {"detail": "Une erreur interne est survenue."}
    assert "secret" not in failed.text
    assert recovered.status_code == 201
