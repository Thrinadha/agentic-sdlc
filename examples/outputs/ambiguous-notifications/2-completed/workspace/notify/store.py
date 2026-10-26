"""Thread-safe in-memory storage for inboxes, preferences and processed event ids.

v1 keeps state in memory (single instance). The class is the only place that holds state, so a
database-backed implementation can replace it without changing the dispatcher or the API.
"""

from __future__ import annotations

import itertools
import threading
from datetime import datetime, timezone

from notify.models import EventType, Notification, Preferences


class NotificationStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._claimed: set[str] = set()
        self._inbox: dict[str, list[Notification]] = {}
        self._prefs: dict[str, Preferences] = {}

    # -- idempotency ---------------------------------------------------------
    def claim_event(self, event_id: str) -> bool:
        """True the first time an event id is seen; False for duplicates (atomic)."""
        with self._lock:
            if event_id in self._claimed:
                return False
            self._claimed.add(event_id)
            return True

    def release_event(self, event_id: str) -> None:
        """Forget an event whose delivery failed everywhere, so the producer's retry is processed."""
        with self._lock:
            self._claimed.discard(event_id)

    # -- inbox -----------------------------------------------------------------
    def add(self, user_id: str, event_id: str, event_type: EventType, title: str, body: str) -> Notification:
        with self._lock:
            note = Notification(id=next(self._ids), user_id=user_id, event_id=event_id, event_type=event_type,
                                title=title, body=body, created_at=datetime.now(timezone.utc))
            self._inbox.setdefault(user_id, []).append(note)
            return note

    def list(self, user_id: str, unread_only: bool = False) -> list[Notification]:
        with self._lock:
            items = list(reversed(self._inbox.get(user_id, [])))
        return [n for n in items if not n.read] if unread_only else items

    def mark_read(self, user_id: str, notification_id: int) -> Notification | None:
        with self._lock:
            for i, note in enumerate(self._inbox.get(user_id, [])):
                if note.id == notification_id:
                    updated = note.model_copy(update={"read": True})
                    self._inbox[user_id][i] = updated
                    return updated
        return None

    # -- preferences -------------------------------------------------------------
    def get_prefs(self, user_id: str) -> Preferences:
        with self._lock:
            return self._prefs.get(user_id, Preferences())

    def update_prefs(self, user_id: str, in_app: dict[EventType, bool]) -> Preferences:
        with self._lock:
            current = self._prefs.get(user_id, Preferences())
            merged = Preferences(in_app={**current.in_app, **in_app})
            self._prefs[user_id] = merged
            return merged
