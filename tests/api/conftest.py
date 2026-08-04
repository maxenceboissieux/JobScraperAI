from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from jobscraper.api.app import create_app


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'api.db'}"


@pytest.fixture
def app(database_url: str) -> FastAPI:
    return create_app(database_url)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def session(app: FastAPI, client: TestClient) -> Iterator[Session]:
    del client  # The dependency keeps the application lifespan active.
    with app.state.session_factory() as database_session:
        yield database_session
