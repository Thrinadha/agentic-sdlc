"""Request and response models (the HTTP boundary). Mirrors api/openapi.yaml."""

from __future__ import annotations

from datetime import date, datetime
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_URL_LENGTH = 2048
ALLOWED_SCHEMES = ("http", "https")


class LinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(..., max_length=MAX_URL_LENGTH, examples=["https://example.com/a/long/path?q=1"])
    custom_alias: str | None = Field(None, examples=["spring-sale"])
    expires_at: datetime | None = Field(None, description="ISO 8601 with timezone; must be in the future")

    @field_validator("url")
    @classmethod
    def _valid_url(cls, value: str) -> str:
        value = value.strip()
        parts = urlsplit(value)
        if parts.scheme.lower() not in ALLOWED_SCHEMES:
            raise ValueError("url must start with http:// or https://")
        if not parts.netloc or any(c.isspace() for c in value):
            raise ValueError("url must be absolute and contain no whitespace")
        return value

    @field_validator("expires_at")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("expires_at must include a timezone offset")
        return value


class LinkOut(BaseModel):
    code: str
    short_url: str
    target_url: str
    created_at: datetime
    expires_at: datetime | None
    click_count: int


class DailyClicks(BaseModel):
    date: date
    clicks: int


class ReferrerClicks(BaseModel):
    referrer: str
    clicks: int


class LinkStats(BaseModel):
    code: str
    total_clicks: int
    last_clicked_at: datetime | None
    daily: list[DailyClicks]
    top_referrers: list[ReferrerClicks]
