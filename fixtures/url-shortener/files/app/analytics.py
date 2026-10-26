"""Click analytics: recording clicks off the redirect path and aggregating stats."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import ClickEvent, Link, as_utc, utcnow
from app.repository import LinkRepository
from app.schemas import DailyClicks, LinkStats, ReferrerClicks

log = logging.getLogger(__name__)
TOP_REFERRERS = 5


class AnalyticsService:
    def __init__(self, session_factory: sessionmaker[Session]):
        self.session_factory = session_factory

    def record_click(self, link_id: int, referrer: str | None, user_agent: str | None) -> None:
        """Runs after the redirect response is sent. A failure here never breaks a redirect."""
        try:
            with self.session_factory() as session:
                session.add(ClickEvent(link_id=link_id, referrer=(referrer or None) and referrer[:512],
                                       user_agent=(user_agent or None) and user_agent[:512]))
                LinkRepository(session).increment_clicks(link_id)
                session.commit()
        except Exception:
            log.exception("failed to record click for link %s", link_id)

    def stats(self, session: Session, link: Link, days: int) -> LinkStats:
        since = utcnow() - timedelta(days=days)
        day = func.date(ClickEvent.occurred_at)
        daily_rows = session.execute(
            select(day, func.count()).where(ClickEvent.link_id == link.id, ClickEvent.occurred_at >= since)
            .group_by(day).order_by(day)
        ).all()
        referrer_rows = session.execute(
            select(ClickEvent.referrer, func.count().label("n"))
            .where(ClickEvent.link_id == link.id, ClickEvent.referrer.is_not(None))
            .group_by(ClickEvent.referrer).order_by(func.count().desc(), ClickEvent.referrer).limit(TOP_REFERRERS)
        ).all()
        last: datetime | None = session.scalar(
            select(func.max(ClickEvent.occurred_at)).where(ClickEvent.link_id == link.id))
        return LinkStats(
            code=link.code,
            total_clicks=link.click_count,
            last_clicked_at=as_utc(last),
            # func.date() is a DATE in PostgreSQL but a 'YYYY-MM-DD' string in SQLite; accept both.
            daily=[DailyClicks(date=date.fromisoformat(str(d)), clicks=n) for d, n in daily_rows],
            top_referrers=[ReferrerClicks(referrer=r, clicks=n) for r, n in referrer_rows],
        )
