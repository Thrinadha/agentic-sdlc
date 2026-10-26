"""HTTP API tests, written against api/openapi.yaml."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from notify.main import create_app


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


def send(client, event_id: str, kind: str = "order_shipped", user: str = "alice"):
    return client.post("/api/v1/events", json={"event_id": event_id, "type": kind, "user_id": user,
                                               "order_id": "o-1", "occurred_at": "2026-10-01T10:00:00Z"})


def test_event_lands_in_inbox(client):
    resp = send(client, "e1")
    assert resp.status_code == 202 and resp.json()["delivered"] == ["in_app"]
    inbox = client.get("/api/v1/users/alice/notifications").json()
    assert [n["title"] for n in inbox] == ["Your order has shipped"]


def test_duplicate_event_is_ignored(client):
    send(client, "e1")
    assert send(client, "e1").json()["duplicate"] is True
    assert len(client.get("/api/v1/users/alice/notifications").json()) == 1


def test_inbox_is_newest_first_and_per_user(client):
    send(client, "e1", "order_shipped")
    send(client, "e2", "order_delivered")
    send(client, "e3", "order_shipped", user="bob")
    inbox = client.get("/api/v1/users/alice/notifications").json()
    assert [n["event_type"] for n in inbox] == ["order_delivered", "order_shipped"]
    assert len(client.get("/api/v1/users/bob/notifications").json()) == 1


def test_mark_read_and_unread_filter(client):
    send(client, "e1")
    send(client, "e2", "order_delivered")
    first = client.get("/api/v1/users/alice/notifications").json()[0]
    resp = client.post(f"/api/v1/users/alice/notifications/{first['id']}/read")
    assert resp.status_code == 200 and resp.json()["read"] is True
    unread = client.get("/api/v1/users/alice/notifications", params={"unread": True}).json()
    assert [n["id"] for n in unread] == [first["id"] - 1]


def test_mark_read_unknown_or_other_users_notification_is_404(client):
    send(client, "e1", user="bob")
    bob_note = client.get("/api/v1/users/bob/notifications").json()[0]
    assert client.post(f"/api/v1/users/alice/notifications/{bob_note['id']}/read").status_code == 404
    assert client.post("/api/v1/users/alice/notifications/999/read").status_code == 404


def test_preferences_default_on_and_can_be_changed(client):
    prefs = client.get("/api/v1/users/alice/preferences").json()
    assert all(prefs["in_app"].values())
    updated = client.put("/api/v1/users/alice/preferences", json={"in_app": {"order_shipped": False}}).json()
    assert updated["in_app"]["order_shipped"] is False and updated["in_app"]["order_delivered"] is True
    assert send(client, "e9", "order_shipped").json()["delivered"] == []
    assert send(client, "e10", "order_delivered").json()["delivered"] == ["in_app"]


@pytest.mark.parametrize("bad", [
    {"event_id": "e1", "type": "price_changed", "user_id": "a", "order_id": "o", "occurred_at": "2026-10-01T10:00:00Z"},
    {"event_id": "", "type": "order_shipped", "user_id": "a", "order_id": "o", "occurred_at": "2026-10-01T10:00:00Z"},
    {"event_id": "e1", "type": "order_shipped", "user_id": "a", "order_id": "o"},
])
def test_invalid_events_are_rejected(client, bad):
    assert client.post("/api/v1/events", json=bad).status_code == 422


def test_unknown_preference_key_is_rejected(client):
    assert client.put("/api/v1/users/alice/preferences", json={"in_app": {"spam": True}}).status_code == 422
