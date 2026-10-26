"""Application factory. Run with: uvicorn bookmarks.main:create_app --factory"""

from __future__ import annotations

from fastapi import FastAPI

from bookmarks.api import router
from bookmarks.store import BookmarkStore


def create_app() -> FastAPI:
    app = FastAPI(title="Bookmarks API", version="1.2.0")
    app.state.store = BookmarkStore()
    app.include_router(router)
    return app
