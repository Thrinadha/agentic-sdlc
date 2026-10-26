"""Redirects and click analytics, written against api/openapi.yaml."""

from __future__ import annotations

from datetime import datetime, timezone

from tests.helpers import future


def test_redirect_is_307_to_target(client, create):
    link = create("https://example.com/landing")
    resp = client.get(f"/{link['code']}")
    assert resp.status_code == 307
    assert resp.headers["location"] == "https://example.com/landing"
    assert "no-store" in resp.headers["cache-control"]


def test_unknown_code_redirect_returns_404(client):
    assert client.get("/zzzzzzz").status_code == 404


def test_expired_link_returns_410(client, create, expire):
    code = create(expires_at=future())["code"]
    expire(code)
    assert client.get(f"/{code}").status_code == 410


def test_clicks_are_counted(client, create):
    code = create()["code"]
    for _ in range(3):
        client.get(f"/{code}")
    assert client.get(f"/api/v1/links/{code}").json()["click_count"] == 3


def test_stats_daily_and_referrers(client, create):
    code = create()["code"]
    client.get(f"/{code}", headers={"referer": "https://news.example"})
    client.get(f"/{code}", headers={"referer": "https://news.example"})
    client.get(f"/{code}", headers={"referer": "https://blog.example"})
    client.get(f"/{code}")

    stats = client.get(f"/api/v1/links/{code}/stats").json()
    assert stats["total_clicks"] == 4
    today = datetime.now(timezone.utc).date().isoformat()
    assert stats["daily"] == [{"date": today, "clicks": 4}]
    assert stats["top_referrers"][0] == {"referrer": "https://news.example", "clicks": 2}
    assert stats["last_clicked_at"] is not None


def test_stats_for_link_without_clicks(client, create):
    code = create()["code"]
    stats = client.get(f"/api/v1/links/{code}/stats").json()
    assert stats == {"code": code, "total_clicks": 0, "last_clicked_at": None, "daily": [], "top_referrers": []}
