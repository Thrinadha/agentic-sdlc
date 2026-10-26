"""Offline replay provider plus a recorder for live runs.

``MockProvider`` serves pre-written agent answers from ``fixtures/<scenario>/<key>[.attemptN].json``, so
the whole workflow runs with no API key, deterministically. Only the agents' text is replayed: the
orchestrator, gates, git, tests and checks all really run on it. ``RecordingProvider`` captures a live
run into the same format.

A fixture can keep large file contents in real files next to it:
``{"files": [{"path": "app/main.py", "content_file": "files/app/main.py"}]}``.
"""

from __future__ import annotations

import json
from pathlib import Path

from .base import LLMProvider, LLMRequest


class MissingFixture(LookupError):
    pass


class MockProvider(LLMProvider):
    name = "mock"

    def __init__(self, fixtures_root: Path):
        self.root = fixtures_root

    def _find(self, req: LLMRequest) -> Path:
        d = self.root / req.scenario
        names = []
        if req.attempt > 1:
            names.append(f"{req.key}.attempt{req.attempt}.json")
        names.append(f"{req.key}.json")
        for n in names:
            if (d / n).exists():
                return d / n
        raise MissingFixture(
            f"no fixture answer for '{req.key}' (attempt {req.attempt}) in {d}. "
            "Use a live provider (--provider anthropic|openai) for requirements without fixtures."
        )

    def complete(self, req: LLMRequest) -> str:
        path = self._find(req)
        data = json.loads(path.read_text(encoding="utf-8"))
        for container in ("files", "fixes"):
            for f in data.get(container, []) or []:
                if "content_file" in f:
                    f["content"] = (path.parent / f.pop("content_file")).read_text(encoding="utf-8")
        return json.dumps(data)


class RecordingProvider(LLMProvider):
    """Wraps a live provider and saves each answer as a fixture, for building new replay scenarios."""

    def __init__(self, inner: LLMProvider, fixtures_root: Path):
        self.inner = inner
        self.root = fixtures_root
        self.name = f"{inner.name}+record"

    def complete(self, req: LLMRequest) -> str:
        out = self.inner.complete(req)
        d = self.root / req.scenario
        d.mkdir(parents=True, exist_ok=True)
        suffix = f".attempt{req.attempt}" if req.attempt > 1 else ""
        try:
            pretty = json.dumps(json.loads(out), indent=2)
        except json.JSONDecodeError:
            pretty = out
        (d / f"{req.key}{suffix}.json").write_text(pretty, encoding="utf-8")
        return out
