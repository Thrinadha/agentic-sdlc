"""Task dependency graph: validation, topological levels and the ready set."""

from __future__ import annotations

from collections.abc import Iterable

from .models import Task


class PlanError(ValueError):
    """The planner produced a graph the engine refuses to run."""


class TaskGraph:
    def __init__(self, tasks: Iterable[Task]):
        self.tasks: dict[str, Task] = {}
        for t in tasks:
            if t.id in self.tasks:
                raise PlanError(f"duplicate task id {t.id!r}")
            self.tasks[t.id] = t
        self._validate()

    def _validate(self) -> None:
        if not self.tasks:
            raise PlanError("plan has no tasks")
        for t in self.tasks.values():
            for dep in t.depends_on:
                if dep not in self.tasks:
                    raise PlanError(f"task {t.id!r} depends on unknown task {dep!r}")
                if dep == t.id:
                    raise PlanError(f"task {t.id!r} depends on itself")
        self.levels()  # raises on cycles

    def levels(self) -> list[list[str]]:
        """Kahn's algorithm grouped by depth. Tasks in one level can run in parallel."""
        indegree = {tid: len(t.depends_on) for tid, t in self.tasks.items()}
        level = sorted(tid for tid, d in indegree.items() if d == 0)
        out: list[list[str]] = []
        seen = 0
        while level:
            out.append(level)
            seen += len(level)
            nxt = []
            for tid in level:
                for child in self.dependents(tid):
                    indegree[child] -= 1
                    if indegree[child] == 0:
                        nxt.append(child)
            level = sorted(nxt)
        if seen != len(self.tasks):
            cyclic = sorted(tid for tid, d in indegree.items() if d > 0)
            raise PlanError(f"dependency cycle among tasks: {', '.join(cyclic)}")
        return out

    def dependents(self, tid: str) -> list[str]:
        return sorted(t.id for t in self.tasks.values() if tid in t.depends_on)

    def ancestors(self, tid: str) -> set[str]:
        seen: set[str] = set()
        stack = list(self.tasks[tid].depends_on)
        while stack:
            cur = stack.pop()
            if cur not in seen:
                seen.add(cur)
                stack.extend(self.tasks[cur].depends_on)
        return seen

    def ready(self, done: set[str], running: set[str], blocked: set[str]) -> list[str]:
        """Tasks whose dependencies are all done and that are not running, done or blocked."""
        return sorted(
            tid
            for tid, t in self.tasks.items()
            if tid not in done
            and tid not in running
            and tid not in blocked
            and all(d in done for d in t.depends_on)
        )

    def to_mermaid(self) -> str:
        lines = ["graph TD"]
        for t in self.tasks.values():
            label = t.title.replace('"', "'")
            lines.append(f'  {t.id}["{t.id}: {label}<br/><i>{t.agent}</i>"]')
        for t in self.tasks.values():
            for d in t.depends_on:
                lines.append(f"  {d} --> {t.id}")
        return "\n".join(lines)
