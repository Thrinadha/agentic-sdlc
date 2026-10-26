"""Fan an event out to every channel the user has enabled."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from notify.channels import Channel, render
from notify.models import IngestResult, OrderEvent
from notify.store import NotificationStore

log = logging.getLogger(__name__)


class Dispatcher:
    def __init__(self, store: NotificationStore, channels: Sequence[Channel]):
        self.store = store
        self.channels = list(channels)

    def handle(self, event: OrderEvent) -> IngestResult:
        """Deliver once per event id. One failing channel never blocks the others.

        If every enabled channel fails, the event id is released so the producer's retry is
        processed (at-least-once overall, exactly-once per successful channel).
        """
        if not self.store.claim_event(event.event_id):
            return IngestResult(event_id=event.event_id, duplicate=True, delivered=[])
        prefs = self.store.get_prefs(event.user_id)
        title, body = render(event)
        delivered, failed = [], []
        for channel in self.channels:
            if not channel.enabled_for(prefs, event.type):
                continue
            try:
                channel.deliver(event, title, body)
                delivered.append(channel.name)
            except Exception:
                log.exception("channel %s failed for event %s", channel.name, event.event_id)
                failed.append(channel.name)
        if failed and not delivered:
            self.store.release_event(event.event_id)
        return IngestResult(event_id=event.event_id, duplicate=False, delivered=delivered, failed=failed)
