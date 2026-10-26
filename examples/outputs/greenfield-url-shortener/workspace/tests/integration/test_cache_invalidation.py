"""Regression tests from review: cached redirects must honour deletes and expiry."""

from __future__ import annotations


def test_deleted_link_stops_redirecting_even_when_cached(client, create):
    code = create()["code"]
    assert client.get(f"/{code}").status_code == 307  # now in the redirect cache
    assert client.delete(f"/api/v1/links/{code}").status_code == 204
    assert client.get(f"/{code}").status_code == 404


def test_deleting_twice_returns_404(client, create):
    code = create()["code"]
    assert client.delete(f"/api/v1/links/{code}").status_code == 204
    assert client.delete(f"/api/v1/links/{code}").status_code == 404
