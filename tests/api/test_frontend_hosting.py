from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jobscraper.api.app import create_app


@pytest.fixture
def built_frontend(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text(
        '<!doctype html><html lang="fr"><div id="root"></div></html>',
        encoding="utf-8",
    )
    (assets / "app.js").write_text("window.JOBSCRAPER = true;", encoding="utf-8")
    return dist


@pytest.fixture
def client_with_built_frontend(
    database_url: str, built_frontend: Path
) -> Iterator[TestClient]:
    with TestClient(
        create_app(database_url, frontend_dist=built_frontend),
        raise_server_exceptions=False,
    ) as client:
        yield client


def test_frontend_index_is_served(client_with_built_frontend: TestClient) -> None:
    response = client_with_built_frontend.get("/")

    assert response.status_code == 200
    assert '<div id="root"></div>' in response.text


def test_frontend_index_is_served_for_deep_client_route(
    client_with_built_frontend: TestClient,
) -> None:
    response = client_with_built_frontend.get("/offres/42")

    assert response.status_code == 200
    assert '<div id="root"></div>' in response.text


def test_frontend_asset_is_served(client_with_built_frontend: TestClient) -> None:
    response = client_with_built_frontend.get("/assets/app.js")

    assert response.status_code == 200
    assert response.text == "window.JOBSCRAPER = true;"


def test_missing_build_keeps_api_available_and_returns_development_hint(
    database_url: str, tmp_path: Path
) -> None:
    with TestClient(
        create_app(database_url, frontend_dist=tmp_path / "missing-dist"),
        raise_server_exceptions=False,
    ) as client:
        api_response = client.get("/api/jobs")
        frontend_response = client.get("/")

    assert api_response.status_code == 200
    assert frontend_response.status_code == 503
    assert "pnpm install" in frontend_response.text
    assert "pnpm build" in frontend_response.text


def test_unknown_api_route_stays_json_404(
    client_with_built_frontend: TestClient,
) -> None:
    response = client_with_built_frontend.get("/api/inconnue")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert '<div id="root"></div>' not in response.text


def test_mutating_client_route_is_refused(
    client_with_built_frontend: TestClient,
) -> None:
    response = client_with_built_frontend.post("/offres/42")

    assert response.status_code == 405
    assert response.headers["content-type"].startswith("application/json")
    assert '<div id="root"></div>' not in response.text


@pytest.mark.parametrize(
    "path",
    [
        "/assets/introuvable.js",
        "/assets/%2e%2e/index.html",
    ],
)
def test_missing_or_traversing_asset_never_uses_spa_fallback(
    client_with_built_frontend: TestClient, path: str
) -> None:
    response = client_with_built_frontend.get(path)

    assert response.status_code == 404
    assert '<div id="root"></div>' not in response.text


def test_missing_assets_directory_never_uses_spa_fallback(
    database_url: str, tmp_path: Path
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text('<div id="root"></div>', encoding="utf-8")

    with TestClient(
        create_app(database_url, frontend_dist=dist),
        raise_server_exceptions=False,
    ) as client:
        response = client.get("/assets/introuvable.js")

    assert response.status_code == 404
    assert '<div id="root"></div>' not in response.text


def test_head_client_route_uses_index_without_a_body(
    client_with_built_frontend: TestClient,
) -> None:
    response = client_with_built_frontend.head("/offres/42")

    assert response.status_code == 200
    assert response.content == b""
