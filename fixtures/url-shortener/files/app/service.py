"""Business rules for creating, resolving and deleting short links."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from urllib.parse import urlsplit

from sqlalchemy.exc import IntegrityError

from app.cache import Cache, CachedLink
from app.config import Settings
from app.models import Link, as_utc, utcnow
from app.repository import LinkRepository
from app.schemas import LinkCreate
from app.shortcode import is_valid_alias, random_code

MAX_CODE_ATTEMPTS = 5


class LinkError(Exception):
    """Base class for domain errors; the API layer maps each one to a status code."""


class LinkNotFound(LinkError):
    pass


class LinkExpired(LinkError):
    pass


class AliasTaken(LinkError):
    pass


class InvalidLink(LinkError):
    pass


class LinkService:
    def __init__(self, repo: LinkRepository, settings: Settings, cache: Cache,
                 code_factory: Callable[[], str] | None = None, clock: Callable = utcnow):
        self.repo = repo
        self.settings = settings
        self.cache = cache
        self.code_factory = code_factory or partial(random_code, settings.code_length)
        self.clock = clock

    def create(self, data: LinkCreate) -> Link:
        if urlsplit(data.url).netloc.lower() == urlsplit(self.settings.base_url).netloc.lower():
            raise InvalidLink("cannot shorten a link to this service")
        if data.expires_at is not None and data.expires_at <= self.clock():
            raise InvalidLink("expires_at must be in the future")
        if data.custom_alias is not None and not is_valid_alias(data.custom_alias):
            raise InvalidLink("custom_alias must be 3-32 characters of A-Z a-z 0-9 _ - and not reserved")

        attempts = 1 if data.custom_alias else MAX_CODE_ATTEMPTS
        for _ in range(attempts):
            code = data.custom_alias or self.code_factory()
            try:
                return self.repo.add(Link(code=code, target_url=data.url, expires_at=data.expires_at))
            except IntegrityError:
                self.repo.rollback()
        if data.custom_alias:
            raise AliasTaken(f"alias '{data.custom_alias}' is already in use")
        raise RuntimeError(f"could not allocate a unique code in {MAX_CODE_ATTEMPTS} attempts")

    def get(self, code: str) -> Link:
        link = self.repo.get_by_code(code)
        if link is None or not link.is_active:
            raise LinkNotFound(code)
        return link

    def resolve(self, code: str) -> CachedLink:
        """Target for a redirect: cache first, then the database."""
        cached = self.cache.get(code)
        if cached is None:
            link = self.get(code)
            cached = CachedLink(link_id=link.id, target_url=link.target_url, expires_at=as_utc(link.expires_at))
            self.cache.set(code, cached)
        if cached.expires_at is not None and cached.expires_at <= self.clock():
            raise LinkExpired(code)
        return cached

    def delete(self, code: str) -> None:
        self.repo.deactivate(self.get(code))
        self.cache.delete(code)

    def short_url(self, link: Link) -> str:
        return f"{self.settings.base_url}/{link.code}"
