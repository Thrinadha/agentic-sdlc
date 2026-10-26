"""Regression tests for REQ-202: paging must return every bookmark exactly once."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bookmarks.main import create_app


@pytest.fixture
def client_with_45():
    with TestClient(create_app()) as c:
        for i in range(45):
            c.post("/bookmarks", json={"url": f"https://site{i}.example", "title": f"B{i}"})
        yield c


def test_pages_add_up_to_total(client_with_45):
    seen = []
    for page in (1, 2, 3):
        body = client_with_45.get("/bookmarks", params={"page": page}).json()
        assert body["total"] == 45
        seen += [b["id"] for b in body["items"]]
    assert sorted(seen) == list(range(1, 46))
    assert len(seen) == len(set(seen))


def test_full_page_has_exactly_size_items(client_with_45):
    assert len(client_with_45.get("/bookmarks", params={"page": 1, "size": 20}).json()["items"]) == 20
    assert len(client_with_45.get("/bookmarks", params={"page": 3, "size": 20}).json()["items"]) == 5


def test_newest_first_across_pages(client_with_45):
    first = client_with_45.get("/bookmarks", params={"page": 1, "size": 10}).json()["items"]
    second = client_with_45.get("/bookmarks", params={"page": 2, "size": 10}).json()["items"]
    assert first[0]["id"] == 45 and first[-1]["id"] == 36
    assert second[0]["id"] == 35


def test_page_past_the_end_is_empty(client_with_45):
    body = client_with_45.get("/bookmarks", params={"page": 99}).json()
    assert body["items"] == [] and body["total"] == 45


@pytest.mark.parametrize("params", [{"page": 0}, {"size": 0}, {"size": 101}])
def test_out_of_range_paging_is_rejected(client_with_45, params):
    assert client_with_45.get("/bookmarks", params=params).status_code == 422
