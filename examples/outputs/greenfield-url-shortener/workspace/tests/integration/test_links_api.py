"""Link management API, written against api/openapi.yaml."""

from __future__ import annotations

from tests.helpers import BASE_URL, future


def test_create_link_returns_201_with_short_url(create):
    body = create("https://example.com/a?b=c")
    assert body["target_url"] == "https://example.com/a?b=c"
    assert len(body["code"]) == 7
    assert body["short_url"] == f"{BASE_URL}/{body['code']}"
    assert body["click_count"] == 0


def test_codes_are_unique(create):
    codes = {create(f"https://example.com/{i}")["code"] for i in range(50)}
    assert len(codes) == 50


def test_custom_alias_is_used(create):
    assert create(custom_alias="spring-sale")["code"] == "spring-sale"


def test_duplicate_alias_returns_409(client, create):
    create(custom_alias="taken")
    resp = client.post("/api/v1/links", json={"url": "https://example.org", "custom_alias": "taken"})
    assert resp.status_code == 409
    assert "already in use" in resp.json()["detail"]


def test_reserved_alias_returns_422(client):
    resp = client.post("/api/v1/links", json={"url": "https://example.org", "custom_alias": "api"})
    assert resp.status_code == 422


def test_invalid_urls_are_rejected(client):
    for bad in ["ftp://example.com/file", "javascript:alert(1)", "not a url", "https://", "/relative"]:
        assert client.post("/api/v1/links", json={"url": bad}).status_code == 422, bad


def test_url_longer_than_limit_is_rejected(client):
    resp = client.post("/api/v1/links", json={"url": "https://example.com/" + "a" * 2100})
    assert resp.status_code == 422


def test_cannot_shorten_own_short_links(client):
    resp = client.post("/api/v1/links", json={"url": f"{BASE_URL}/abc1234"})
    assert resp.status_code == 422


def test_expiry_in_the_past_is_rejected(client):
    resp = client.post("/api/v1/links", json={"url": "https://example.com", "expires_at": "2000-01-01T00:00:00Z"})
    assert resp.status_code == 422


def test_get_link_metadata(client, create):
    code = create(expires_at=future())["code"]
    resp = client.get(f"/api/v1/links/{code}")
    assert resp.status_code == 200
    assert resp.json()["expires_at"] is not None


def test_unknown_link_returns_404(client):
    assert client.get("/api/v1/links/nope404").status_code == 404


def test_delete_link_then_404(client, create):
    code = create()["code"]
    assert client.delete(f"/api/v1/links/{code}").status_code == 204
    assert client.get(f"/api/v1/links/{code}").status_code == 404
    assert client.get(f"/{code}").status_code == 404


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}
