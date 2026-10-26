from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bookmarks.main import create_app


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


def test_create_and_get(client):
    created = client.post("/bookmarks", json={"url": "https://docs.python.org/3/", "title": "Python docs",
                                              "tags": ["python"]})
    assert created.status_code == 201
    got = client.get(f"/bookmarks/{created.json()['id']}")
    assert got.json()["title"] == "Python docs"


def test_invalid_url_rejected(client):
    assert client.post("/bookmarks", json={"url": "nope", "title": "x"}).status_code == 422


def test_list_first_page(client):
    client.post("/bookmarks", json={"url": "https://a.example", "title": "A"})
    body = client.get("/bookmarks").json()
    assert body["total"] == 1
    assert body["page"] == 1


def test_delete(client):
    bid = client.post("/bookmarks", json={"url": "https://a.example", "title": "A"}).json()["id"]
    assert client.delete(f"/bookmarks/{bid}").status_code == 204
    assert client.get(f"/bookmarks/{bid}").status_code == 404
