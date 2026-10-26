"""Shared fixtures: an app on a temporary SQLite database and an HTTP client."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.config import Settings
from app.main import create_app
from app.models import Link
from tests.helpers import BASE_URL


@pytest.fixture
def app(tmp_path):
    return create_app(Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}", base_url=BASE_URL))


@pytest.fixture
def client(app):
    with TestClient(app, follow_redirects=False) as c:
        yield c


@pytest.fixture
def create(client):
    """POST a link and return the JSON body; fails the test on a non-201."""

    def _create(url: str = "https://example.com/some/long/path", **extra) -> dict:
        resp = client.post("/api/v1/links", json={"url": url, **extra})
        assert resp.status_code == 201, resp.text
        return resp.json()

    return _create


@pytest.fixture
def expire(app):
    """Move a link's expiry into the past directly in the database (no sleeping in tests)."""

    def _expire(code: str) -> None:
        with app.state.session_factory() as s:
            past = datetime.now(timezone.utc) - timedelta(seconds=1)
            s.execute(update(Link).where(Link.code == code).values(expires_at=past))
            s.commit()

    return _expire
