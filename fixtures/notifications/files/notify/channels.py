"""Delivery channels. v1 ships the in-app inbox; email/push implement the same protocol later."""

from __future__ import annotations

from typing import Protocol

from notify.models import EventType, OrderEvent, Preferences
from notify.store import NotificationStore

MESSAGES: dict[EventType, tuple[str, str]] = {
    EventType.ORDER_SHIPPED: ("Your order has shipped", "Order {order_id} is on its way."),
    EventType.ORDER_DELIVERED: ("Your order was delivered", "Order {order_id} has been delivered."),
    EventType.ORDER_CANCELLED: ("Your order was cancelled", "Order {order_id} has been cancelled."),
}


def render(event: OrderEvent) -> tuple[str, str]:
    title, body = MESSAGES[event.type]
    return title, body.format(order_id=event.order_id)


class Channel(Protocol):
    name: str

    def enabled_for(self, prefs: Preferences, event_type: EventType) -> bool: ...

    def deliver(self, event: OrderEvent, title: str, body: str) -> None: ...


class InAppChannel:
    name = "in_app"

    def __init__(self, store: NotificationStore):
        self.store = store

    def enabled_for(self, prefs: Preferences, event_type: EventType) -> bool:
        return prefs.in_app.get(event_type, True)

    def deliver(self, event: OrderEvent, title: str, body: str) -> None:
        self.store.add(event.user_id, event.event_id, event.type, title, body)
