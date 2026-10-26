"""Application factory. Run with: uvicorn notify.main:create_app --factory"""

from __future__ import annotations

from fastapi import FastAPI

from notify.api import router
from notify.channels import InAppChannel
from notify.dispatcher import Dispatcher
from notify.store import NotificationStore


def create_app() -> FastAPI:
    app = FastAPI(title="Notification Service", version="1.0.0")
    store = NotificationStore()
    app.state.store = store
    app.state.dispatcher = Dispatcher(store, [InAppChannel(store)])
    app.include_router(router)
    return app
