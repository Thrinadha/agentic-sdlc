"""HTTP routes: event ingestion, user inbox and preferences."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request, status

from notify.dispatcher import Dispatcher
from notify.models import IngestResult, Notification, OrderEvent, Preferences, PreferencesUpdate
from notify.store import NotificationStore

router = APIRouter()
UserId = Annotated[str, Path(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")]


def _store(request: Request) -> NotificationStore:
    return request.app.state.store


def _dispatcher(request: Request) -> Dispatcher:
    return request.app.state.dispatcher


@router.get("/healthz", tags=["ops"])
def healthz() -> dict:
    return {"status": "ok"}


@router.post("/api/v1/events", status_code=status.HTTP_202_ACCEPTED, response_model=IngestResult, tags=["events"])
def ingest_event(event: OrderEvent, request: Request) -> IngestResult:
    result = _dispatcher(request).handle(event)
    if result.failed and not result.delivered:
        raise HTTPException(status_code=503, detail="delivery failed on every channel; retry the event")
    return result


@router.get("/api/v1/users/{user_id}/notifications", response_model=list[Notification], tags=["inbox"])
def list_notifications(user_id: UserId, request: Request, unread: bool = False) -> list[Notification]:
    return _store(request).list(user_id, unread_only=unread)


@router.post("/api/v1/users/{user_id}/notifications/{notification_id}/read", response_model=Notification,
             tags=["inbox"])
def mark_read(user_id: UserId, notification_id: int, request: Request) -> Notification:
    note = _store(request).mark_read(user_id, notification_id)
    if note is None:
        raise HTTPException(status_code=404, detail="notification not found")
    return note


@router.get("/api/v1/users/{user_id}/preferences", response_model=Preferences, tags=["preferences"])
def get_preferences(user_id: UserId, request: Request) -> Preferences:
    return _store(request).get_prefs(user_id)


@router.put("/api/v1/users/{user_id}/preferences", response_model=Preferences, tags=["preferences"])
def update_preferences(user_id: UserId, body: PreferencesUpdate, request: Request) -> Preferences:
    return _store(request).update_prefs(user_id, body.in_app)
