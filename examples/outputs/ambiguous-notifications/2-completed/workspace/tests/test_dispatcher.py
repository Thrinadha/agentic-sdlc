"""Dispatcher rules: idempotency, preferences and channel failure isolation."""

from __future__ import annotations

from datetime import datetime, timezone

from notify.channels import InAppChannel
from notify.dispatcher import Dispatcher
from notify.models import EventType, OrderEvent
from notify.store import NotificationStore


def event(event_id: str = "e1", kind: EventType = EventType.ORDER_SHIPPED, user: str = "u1") -> OrderEvent:
    return OrderEvent(event_id=event_id, type=kind, user_id=user, order_id="o-42",
                      occurred_at=datetime.now(timezone.utc))


class BrokenChannel:
    name = "broken"

    def enabled_for(self, prefs, event_type) -> bool:
        return True

    def deliver(self, event, title, body) -> None:
        raise ConnectionError("provider down")


def test_event_is_delivered_once():
    store = NotificationStore()
    d = Dispatcher(store, [InAppChannel(store)])
    assert d.handle(event()).delivered == ["in_app"]
    again = d.handle(event())
    assert again.duplicate and again.delivered == []
    assert len(store.list("u1")) == 1


def test_disabled_event_type_is_not_delivered():
    store = NotificationStore()
    store.update_prefs("u1", {EventType.ORDER_SHIPPED: False})
    result = Dispatcher(store, [InAppChannel(store)]).handle(event())
    assert result.delivered == [] and store.list("u1") == []


def test_one_failing_channel_does_not_block_others():
    store = NotificationStore()
    result = Dispatcher(store, [BrokenChannel(), InAppChannel(store)]).handle(event())
    assert result.delivered == ["in_app"] and result.failed == ["broken"]
    assert len(store.list("u1")) == 1


def test_total_failure_releases_event_for_retry():
    store = NotificationStore()
    d = Dispatcher(store, [BrokenChannel()])
    assert d.handle(event()).failed == ["broken"]
    assert d.handle(event()).duplicate is False  # retry is processed, not dropped


def test_message_text_mentions_the_order():
    store = NotificationStore()
    Dispatcher(store, [InAppChannel(store)]).handle(event(kind=EventType.ORDER_DELIVERED))
    note = store.list("u1")[0]
    assert note.title == "Your order was delivered" and "o-42" in note.body
