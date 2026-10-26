"""Requirement files: Markdown with a small YAML front-matter header."""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class Requirement:
    id: str
    title: str
    scenario: str
    body: str
    path: Path
    seed: str = ""
    seed_version: str = ""

    @property
    def slug(self) -> str:
        return re.sub(r"[^a-z0-9]+", "-", self.title.lower()).strip("-")[:40]

    @property
    def branch(self) -> str:
        return f"{self.id}-{self.slug}"


def load_requirement(path: Path) -> Requirement:
    text = path.read_text(encoding="utf-8")
    meta: dict = {}
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
    if m:
        meta = yaml.safe_load(m.group(1)) or {}
        text = m.group(2)
    # Stable across processes (built-in hash() of a str is randomized per interpreter).
    rid = str(meta.get("id") or f"REQ-{zlib.crc32(path.name.encode()) % 1000:03d}")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*-\d+", rid):
        raise ValueError(f"requirement id {rid!r} must look like REQ-101")
    title = str(meta.get("title") or path.stem.replace("-", " "))
    return Requirement(
        id=rid,
        title=title,
        scenario=str(meta.get("scenario") or path.stem),
        body=text.strip(),
        path=path.resolve(),
        seed=str(meta.get("seed") or ""),
        seed_version=str(meta.get("seed_version") or ""),
    )
