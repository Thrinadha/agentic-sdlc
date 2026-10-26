"""In-memory, thread-safe bookmark storage. Newest bookmarks first."""

from __future__ import annotations

import itertools
import threading
from datetime import datetime, timezone

from bookmarks.models import Bookmark, BookmarkIn


class BookmarkStore:
    def __init__(self) -> None:
        self._items: dict[int, Bookmark] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def add(self, data: BookmarkIn) -> Bookmark:
        with self._lock:
            bookmark = Bookmark(id=next(self._ids), url=str(data.url), title=data.title, tags=data.tags,
                                created_at=datetime.now(timezone.utc))
            self._items[bookmark.id] = bookmark
            return bookmark

    def get(self, bookmark_id: int) -> Bookmark | None:
        return self._items.get(bookmark_id)

    def delete(self, bookmark_id: int) -> bool:
        with self._lock:
            return self._items.pop(bookmark_id, None) is not None

    def list(self, page: int, size: int) -> tuple[list[Bookmark], int]:
        """One page of bookmarks (page is 1-based) and the total count."""
        with self._lock:
            ordered = sorted(self._items.values(), key=lambda b: b.id, reverse=True)
        start = (page - 1) * size
        end = start + size - 1
        return ordered[start:end], len(ordered)
