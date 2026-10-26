"""Sandboxed file access for agents.

Agents never touch the filesystem directly. Every write goes through ``Workspace``, which
keeps it inside the workspace root, refuses protected paths, and caps file size and count.
"""

from __future__ import annotations

import threading
from pathlib import Path, PurePosixPath

from .. import config

MAX_FILE_BYTES = int(config.VARS["SDLC_MAX_FILE_BYTES"].default)  # defaults; effective values come from config


def max_file_bytes() -> int:
    return config.get_int("SDLC_MAX_FILE_BYTES")


def max_files_per_task() -> int:
    return config.get_int("SDLC_MAX_FILES_PER_TASK")
PROTECTED = (".git", ".sdlc", ".venv", ".github/workflows")
SKIP_DIRS = {".git", ".sdlc", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules"}
TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".json", ".toml", ".sql", ".txt", ".cfg", ".ini", ".env.example"}


class GuardrailError(Exception):
    """An agent tried to do something the sandbox does not allow."""


class Workspace:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # -- path safety ---------------------------------------------------------
    def resolve(self, rel: str) -> Path:
        if not rel or rel.strip() != rel:
            raise GuardrailError(f"invalid path {rel!r}")
        p = PurePosixPath(rel.replace("\\", "/"))
        if p.is_absolute() or ".." in p.parts or (p.parts and p.parts[0].endswith(":")):
            raise GuardrailError(f"path escapes the workspace: {rel!r}")
        posix = p.as_posix()
        for prot in PROTECTED:
            if posix == prot or posix.startswith(prot + "/"):
                raise GuardrailError(f"path is protected: {rel!r}")
        full = (self.root / posix).resolve()
        if full != self.root and self.root not in full.parents:
            raise GuardrailError(f"path escapes the workspace: {rel!r}")
        return full

    # -- io -----------------------------------------------------------------
    def write(self, rel: str, content: str) -> None:
        data = content.encode("utf-8")
        limit = max_file_bytes()
        if len(data) > limit:
            raise GuardrailError(f"{rel}: {len(data)} bytes exceeds the {limit} byte limit (SDLC_MAX_FILE_BYTES)")
        full = self.resolve(rel)
        with self._lock:
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_bytes(data)

    def delete(self, rel: str) -> None:
        full = self.resolve(rel)
        with self._lock:
            if full.is_file():
                full.unlink()

    def read(self, rel: str) -> str:
        return self.resolve(rel).read_text(encoding="utf-8")

    def exists(self, rel: str) -> bool:
        try:
            return self.resolve(rel).is_file()
        except GuardrailError:
            return False

    def files(self, suffixes: set[str] | None = None) -> list[str]:
        out = []
        for p in sorted(self.root.rglob("*")):
            rel = p.relative_to(self.root)
            if any(part in SKIP_DIRS for part in rel.parts) or not p.is_file():
                continue
            if suffixes is None or p.suffix in suffixes:
                out.append(rel.as_posix())
        return out

    def snapshot(self, paths: list[str] | None = None, max_bytes: int = 120_000) -> dict[str, str]:
        """Text contents for agent context, capped so a prompt never grows without bound."""
        out, total = {}, 0
        for rel in paths if paths is not None else self.files(TEXT_SUFFIXES):
            if not self.exists(rel):
                continue
            text = self.read(rel)
            if total + len(text) > max_bytes:
                out[rel] = "<omitted: context budget reached>"
                continue
            out[rel] = text
            total += len(text)
        return out
