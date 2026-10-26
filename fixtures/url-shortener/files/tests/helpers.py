"""Small helpers shared by the test modules."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

BASE_URL = "http://sho.rt"


def future(hours: int = 1) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
