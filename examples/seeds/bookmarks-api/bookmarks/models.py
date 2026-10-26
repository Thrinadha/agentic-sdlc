"""Request and response models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl


class BookmarkIn(BaseModel):
    url: HttpUrl
    title: str = Field(..., min_length=1, max_length=200)
    tags: list[str] = Field(default_factory=list, max_length=20)


class Bookmark(BaseModel):
    id: int
    url: str
    title: str
    tags: list[str]
    created_at: datetime


class Page(BaseModel):
    items: list[Bookmark]
    total: int
    page: int
    size: int
