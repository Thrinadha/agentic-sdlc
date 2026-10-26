"""Read-through cache for redirect lookups.

``TTLCache`` is an in-process LRU with per-entry expiry. A shared cache (e.g. Redis) can implement the
same ``Cache`` protocol for multi-instance deployments without touching the service layer.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class CachedLink:
    link_id: int
    target_url: str
    expires_at: datetime | None


class Cache(Protocol):
    def get(self, key: str) -> CachedLink | None: ...

    def set(self, key: str, value: CachedLink) -> None: ...

    def delete(self, key: str) -> None: ...


class TTLCache:
    def __init__(self, max_size: int, ttl_seconds: float, clock: Callable[[], float] = time.monotonic):
        if max_size <= 0:
            raise ValueError("max_size must be positive")
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._clock = clock
        self._items: OrderedDict[str, tuple[float, CachedLink]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> CachedLink | None:
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                return None
            expires, value = entry
            if expires <= self._clock():
                del self._items[key]
                return None
            self._items.move_to_end(key)
            return value

    def set(self, key: str, value: CachedLink) -> None:
        with self._lock:
            self._items[key] = (self._clock() + self._ttl, value)
            self._items.move_to_end(key)
            while len(self._items) > self._max_size:
                self._items.popitem(last=False)

    def delete(self, key: str) -> None:
        with self._lock:
            self._items.pop(key, None)

    def __len__(self) -> int:
        return len(self._items)
