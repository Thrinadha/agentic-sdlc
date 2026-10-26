"""Tests for REQ-202: filter the bookmark list by tag."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bookmarks.main import create_app

DATA = [
    ("https://docs.python.org", "Python docs", ["Python", "docs"]),
    ("https://fastapi.tiangolo.com", "FastAPI", ["python", "web"]),
    ("https://go.dev", "Go", ["go"]),
    ("https://example.com", "No tags", []),
]


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        for url, title, tags in DATA:
            c.post("/bookmarks", json={"url": url, "title": title, "tags": tags})
        yield c


def titles(body: dict) -> list[str]:
    return [b["title"] for b in body["items"]]


def test_filter_by_tag_ignores_case(client):
    body = client.get("/bookmarks", params={"tag": "PYTHON"}).json()
    assert titles(body) == ["FastAPI", "Python docs"]
    assert body["total"] == 2


def test_unknown_tag_returns_empty_page(client):
    body = client.get("/bookmarks", params={"tag": "rust"}).json()
    assert body == {"items": [], "total": 0, "page": 1, "size": 20}


def test_paging_applies_to_filtered_list(client):
    body = client.get("/bookmarks", params={"tag": "python", "size": 1, "page": 2}).json()
    assert titles(body) == ["Python docs"]
    assert body["total"] == 2


def test_tag_is_an_exact_match_not_a_substring(client):
    assert client.get("/bookmarks", params={"tag": "pyth"}).json()["total"] == 0


def test_without_tag_lists_everything(client):
    assert client.get("/bookmarks").json()["total"] == 4


def test_empty_tag_is_rejected(client):
    assert client.get("/bookmarks", params={"tag": ""}).status_code == 422
