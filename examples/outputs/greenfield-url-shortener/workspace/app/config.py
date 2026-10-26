"""Runtime configuration, read once from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./shortener.db"
    base_url: str = "http://localhost:8000"
    code_length: int = 7
    cache_size: int = 10_000
    cache_ttl_seconds: int = 300
    max_url_length: int = 2048
    stats_days: int = 30

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            database_url=os.getenv("DATABASE_URL", cls.database_url),
            base_url=os.getenv("BASE_URL", cls.base_url).rstrip("/"),
            code_length=int(os.getenv("SHORT_CODE_LENGTH", str(cls.code_length))),
            cache_size=int(os.getenv("CACHE_SIZE", str(cls.cache_size))),
            cache_ttl_seconds=int(os.getenv("CACHE_TTL_SECONDS", str(cls.cache_ttl_seconds))),
            stats_days=int(os.getenv("STATS_DAYS", str(cls.stats_days))),
        )
