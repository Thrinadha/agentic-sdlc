from __future__ import annotations

from app.cache import CachedLink, TTLCache


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def entry(n: int) -> CachedLink:
    return CachedLink(link_id=n, target_url=f"https://example.com/{n}", expires_at=None)


def test_get_returns_what_was_set():
    cache = TTLCache(10, 60)
    cache.set("a", entry(1))
    assert cache.get("a") == entry(1)
    assert cache.get("missing") is None


def test_entries_expire_after_ttl():
    clock = FakeClock()
    cache = TTLCache(10, 60, clock=clock)
    cache.set("a", entry(1))
    clock.now = 59.9
    assert cache.get("a") is not None
    clock.now = 60.0
    assert cache.get("a") is None


def test_least_recently_used_is_evicted():
    cache = TTLCache(2, 60)
    cache.set("a", entry(1))
    cache.set("b", entry(2))
    cache.get("a")  # a is now most recently used
    cache.set("c", entry(3))
    assert cache.get("b") is None
    assert cache.get("a") is not None and cache.get("c") is not None
    assert len(cache) == 2


def test_delete():
    cache = TTLCache(10, 60)
    cache.set("a", entry(1))
    cache.delete("a")
    cache.delete("never-there")
    assert cache.get("a") is None
