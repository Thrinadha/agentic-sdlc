"""Short code generation and custom alias rules."""

from __future__ import annotations

import re
import secrets
import string

ALPHABET = string.digits + string.ascii_letters  # base62: URL-safe, case-sensitive
ALIAS_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,32}$")
RESERVED = frozenset({"api", "healthz", "docs", "redoc", "openapi.json", "static", "admin"})


def random_code(length: int = 7) -> str:
    """A random base62 code. 62^7 ≈ 3.5e12 codes, so collisions are rare and retried by the caller."""
    if length < 4:
        raise ValueError("code length must be at least 4")
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def is_valid_alias(alias: str) -> bool:
    return bool(ALIAS_PATTERN.match(alias)) and alias.lower() not in RESERVED
