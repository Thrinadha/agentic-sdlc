"""LinkService rules, tested without HTTP."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.cache import TTLCache
from app.config import Settings
from app.db import Base, make_engine, make_session_factory
from app.repository import LinkRepository
from app.schemas import LinkCreate
from app.service import AliasTaken, InvalidLink, LinkExpired, LinkNotFound, LinkService

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def session(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'unit.db'}")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        yield s


def make_service(session, codes=None, now=NOW) -> LinkService:
    factory = iter(codes).__next__ if codes else None
    return LinkService(LinkRepository(session), Settings(base_url="http://sho.rt"), TTLCache(100, 60),
                       code_factory=factory, clock=lambda: now)


def test_collision_is_retried_with_a_new_code(session):
    svc = make_service(session, codes=["dup1234", "dup1234", "new5678"])
    assert svc.create(LinkCreate(url="https://a.example")).code == "dup1234"
    assert svc.create(LinkCreate(url="https://b.example")).code == "new5678"


def test_gives_up_after_max_attempts(session):
    svc = make_service(session, codes=["same000"] * 10)
    svc.create(LinkCreate(url="https://a.example"))
    with pytest.raises(RuntimeError, match="unique code"):
        svc.create(LinkCreate(url="https://b.example"))


def test_alias_conflict(session):
    svc = make_service(session)
    svc.create(LinkCreate(url="https://a.example", custom_alias="promo"))
    with pytest.raises(AliasTaken):
        svc.create(LinkCreate(url="https://b.example", custom_alias="promo"))


def test_expiry_must_be_in_future(session):
    with pytest.raises(InvalidLink):
        make_service(session).create(LinkCreate(url="https://a.example", expires_at=NOW))


def test_resolve_uses_cache_and_honours_expiry(session):
    svc = make_service(session)
    link = svc.create(LinkCreate(url="https://a.example", expires_at=NOW + timedelta(minutes=5)))
    assert svc.resolve(link.code).target_url == "https://a.example"
    assert svc.cache.get(link.code) is not None
    later = make_service(session, now=NOW + timedelta(minutes=6))
    later.cache = svc.cache
    with pytest.raises(LinkExpired):
        later.resolve(link.code)


def test_delete_invalidates_cache(session):
    svc = make_service(session)
    link = svc.create(LinkCreate(url="https://a.example"))
    svc.resolve(link.code)
    svc.delete(link.code)
    with pytest.raises(LinkNotFound):
        svc.resolve(link.code)
