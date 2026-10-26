"""HTTP layer: routes, dependencies and error mapping. No business logic here."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.analytics import AnalyticsService
from app.models import Link
from app.repository import LinkRepository
from app.schemas import LinkCreate, LinkOut, LinkStats
from app.service import AliasTaken, InvalidLink, LinkError, LinkExpired, LinkNotFound, LinkService

router = APIRouter()

ERROR_STATUS = {
    LinkNotFound: status.HTTP_404_NOT_FOUND,
    LinkExpired: status.HTTP_410_GONE,
    AliasTaken: status.HTTP_409_CONFLICT,
    InvalidLink: 422,  # same status FastAPI uses for request validation errors
}
ERROR_DETAIL = {LinkNotFound: "link not found", LinkExpired: "link has expired"}


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def get_service(request: Request, session: Annotated[Session, Depends(get_session)]) -> LinkService:
    state = request.app.state
    return LinkService(LinkRepository(session), state.settings, state.cache)


def get_analytics(request: Request) -> AnalyticsService:
    return request.app.state.analytics


Service = Annotated[LinkService, Depends(get_service)]


def _out(service: LinkService, link: Link) -> LinkOut:
    return LinkOut(code=link.code, short_url=service.short_url(link), target_url=link.target_url,
                   created_at=link.created_at, expires_at=link.expires_at, click_count=link.click_count)


@router.get("/healthz", tags=["ops"])
def healthz() -> dict:
    return {"status": "ok"}


@router.post("/api/v1/links", status_code=status.HTTP_201_CREATED, response_model=LinkOut, tags=["links"])
def create_link(body: LinkCreate, service: Service) -> LinkOut:
    return _out(service, service.create(body))


@router.get("/api/v1/links/{code}", response_model=LinkOut, tags=["links"])
def get_link(code: str, service: Service) -> LinkOut:
    return _out(service, service.get(code))


@router.delete("/api/v1/links/{code}", status_code=status.HTTP_204_NO_CONTENT, tags=["links"])
def delete_link(code: str, service: Service) -> Response:
    service.delete(code)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/v1/links/{code}/stats", response_model=LinkStats, tags=["analytics"])
def link_stats(code: str, request: Request, service: Service,
               session: Annotated[Session, Depends(get_session)],
               analytics: Annotated[AnalyticsService, Depends(get_analytics)]) -> LinkStats:
    link = service.get(code)
    return analytics.stats(session, link, request.app.state.settings.stats_days)


@router.get("/{code}", status_code=status.HTTP_307_TEMPORARY_REDIRECT, tags=["redirect"],
            response_class=RedirectResponse)
def redirect(code: str, request: Request, background: BackgroundTasks, service: Service,
             analytics: Annotated[AnalyticsService, Depends(get_analytics)]) -> RedirectResponse:
    target = service.resolve(code)
    background.add_task(analytics.record_click, target.link_id, request.headers.get("referer"),
                        request.headers.get("user-agent"))
    # 307 + no-store: browsers must come back to us on every click, or analytics would undercount.
    return RedirectResponse(target.target_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                            headers={"Cache-Control": "private, no-store"})


def register_error_handlers(app: FastAPI) -> None:
    async def handle(_: Request, exc: LinkError) -> JSONResponse:
        kind = type(exc)
        return JSONResponse(status_code=ERROR_STATUS.get(kind, 400),
                            content={"detail": ERROR_DETAIL.get(kind, str(exc))})

    app.add_exception_handler(LinkError, handle)
