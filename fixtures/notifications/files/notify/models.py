"""Domain and API models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class EventType(str, Enum):
    ORDER_SHIPPED = "order_shipped"
    ORDER_DELIVERED = "order_delivered"
    ORDER_CANCELLED = "order_cancelled"


Id = Annotated[str, StringConstraints(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")]


class OrderEvent(BaseModel):
    """An event published by the order system. ``event_id`` makes ingestion idempotent."""

    model_config = ConfigDict(extra="forbid")

    event_id: Id
    type: EventType
    user_id: Id
    order_id: Id
    occurred_at: datetime


class Notification(BaseModel):
    id: int
    user_id: str
    event_id: str
    event_type: EventType
    title: str
    body: str
    created_at: datetime
    read: bool = False


def _all_on() -> dict[EventType, bool]:
    return {t: True for t in EventType}


class Preferences(BaseModel):
    """Per channel, per event type opt-in. Everything is on by default."""

    in_app: dict[EventType, bool] = Field(default_factory=_all_on)


class PreferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    in_app: dict[EventType, bool]


class IngestResult(BaseModel):
    event_id: str
    duplicate: bool
    delivered: list[str]
    failed: list[str] = []
