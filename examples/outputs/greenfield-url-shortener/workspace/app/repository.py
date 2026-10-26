"""Persistence for links. The only module that issues queries against the links table."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Link


class LinkRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, link: Link) -> Link:
        """Insert and commit. Raises ``IntegrityError`` if the code is already taken."""
        self.session.add(link)
        self.session.commit()
        return link

    def rollback(self) -> None:
        self.session.rollback()

    def get_by_code(self, code: str) -> Link | None:
        return self.session.scalar(select(Link).where(Link.code == code))

    def deactivate(self, link: Link) -> None:
        link.is_active = False
        self.session.commit()

    def increment_clicks(self, link_id: int) -> None:
        """Atomic in the database, so concurrent redirects never lose a count."""
        self.session.execute(update(Link).where(Link.id == link_id).values(click_count=Link.click_count + 1))
