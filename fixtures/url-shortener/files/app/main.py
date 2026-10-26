"""Application factory. Run with: uvicorn app.main:create_app --factory"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from app.analytics import AnalyticsService
from app.api import register_error_handlers, router
from app.cache import TTLCache
from app.config import Settings
from app.db import Base, make_engine, make_session_factory


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    logging.basicConfig(level=logging.INFO)
    engine = make_engine(settings.database_url)
    # Local/dev convenience. Production applies db/schema.sql (or migrations) before deploying.
    Base.metadata.create_all(engine)

    app = FastAPI(title="URL Shortener", version="1.0.0",
                  description="Short links with redirects and click analytics.")
    app.state.settings = settings
    app.state.session_factory = make_session_factory(engine)
    app.state.cache = TTLCache(settings.cache_size, settings.cache_ttl_seconds)
    app.state.analytics = AnalyticsService(app.state.session_factory)
    register_error_handlers(app)
    app.include_router(router)  # the catch-all /{code} route is registered last inside the router
    return app
