"""Deterministic review checks run alongside the Reviewer agent.

These catch what does not need judgment: commented-out code, duplicated blocks, leftover
TODO/debug output, new modules without tests, and PR hygiene. The agent covers the rest
(story coverage, reuse, patterns, missed scenarios).
"""

from __future__ import annotations

import ast
import re
import textwrap
from collections import defaultdict

from ..orchestrator.models import Finding
from .code_index import index_module

_COMMENT = re.compile(r"^\s*#\s?(.*)$")
_CODEY = re.compile(r"^(def |class |import |from |return\b|if |for |while |print\(|\w+\s*=|\w+\(.*\)$)")
DUP_WINDOW = 6


def commented_out_code(files: dict[str, str]) -> list[Finding]:
    """Flag more than 2 consecutive comment lines that parse as code."""
    out = []
    for path, text in files.items():
        if not path.endswith(".py"):
            continue
        run: list[tuple[int, str]] = []
        for i, line in enumerate([*text.splitlines(), ""], start=1):
            m = _COMMENT.match(line)
            if m and _CODEY.match(m.group(1).strip()):
                run.append((i, m.group(1)))
                continue
            if len(run) > 2:
                try:
                    ast.parse(textwrap.dedent("\n".join(s for _, s in run)))
                    out.append(Finding(severity="medium", check="commented-out code", file=path, line=run[0][0],
                                       message=f"{len(run)} lines of commented-out code",
                                       suggestion="delete it; git history keeps the old version", source="static"))
                except SyntaxError:
                    pass
            run = []
    return out


def _normalize(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip())


def duplicated_blocks(files: dict[str, str]) -> list[Finding]:
    """Same 6 consecutive non-trivial lines appearing in two places."""
    seen: dict[tuple[str, ...], list[tuple[str, int]]] = defaultdict(list)
    for path, text in files.items():
        if not path.endswith(".py"):
            continue
        lines = [(i, _normalize(s)) for i, s in enumerate(text.splitlines(), start=1)]
        lines = [(i, s) for i, s in lines
                 if s and not s.startswith(("#", "import ", "from ", '"""', "@")) and s not in (")", "]", "}")]
        for k in range(len(lines) - DUP_WINDOW + 1):
            window = tuple(s for _, s in lines[k:k + DUP_WINDOW])
            seen[window].append((path, lines[k][0]))
    out, reported = [], set()
    for locs in seen.values():
        uniq = sorted(set(locs))
        if len(uniq) < 2:
            continue
        (p1, l1), (p2, l2) = uniq[0], uniq[1]
        if abs(l1 - l2) < DUP_WINDOW and p1 == p2:
            continue
        key = (p1, p2)
        if key in reported:
            continue
        reported.add(key)
        out.append(Finding(severity="medium", check="duplicated code", file=p2, line=l2,
                           message=f"block duplicates {p1}:{l1}",
                           suggestion="extract a shared helper and call it from both places", source="static"))
    return out


def leftovers(files: dict[str, str]) -> list[Finding]:
    out = []
    for path, text in files.items():
        if not path.endswith(".py"):
            continue
        is_test = "tests/" in path or path.split("/")[-1].startswith("test_")
        for i, line in enumerate(text.splitlines(), start=1):
            if re.search(r"#\s*(TODO|FIXME|XXX)\b", line):
                out.append(Finding(severity="low", check="leftover TODO", file=path, line=i,
                                   message=line.strip()[:100], suggestion="resolve it or track it as a ticket",
                                   source="static"))
            if not is_test and re.match(r"\s*(print\(|breakpoint\(|import pdb)", line):
                out.append(Finding(severity="low", check="debug output", file=path, line=i,
                                   message=line.strip()[:100], suggestion="use logging or remove", source="static"))
    return out


def _is_test(path: str) -> bool:
    return path.startswith("tests/") or "/tests/" in path or path.split("/")[-1].startswith(("test_", "conftest"))


def _module_name(path: str) -> str:
    return path[:-3].replace("/", ".").removesuffix(".__init__")


def _resolve(importer: str, name: str) -> str:
    """Absolute dotted name for an import written in module ``importer`` (handles relative imports)."""
    level = len(name) - len(name.lstrip("."))
    if not level:
        return name
    base = importer.split(".")[:-level]
    rest = name.lstrip(".")
    return ".".join([*base, rest] if rest else base)


def untested_modules(changed: dict[str, str], all_files: dict[str, str]) -> list[Finding]:
    """Changed modules that no test reaches through the import graph (tests -> app -> ... -> module)."""
    modules = {_module_name(p): p for p in all_files if p.endswith(".py")}
    graph: dict[str, set[str]] = {}
    for mod, path in modules.items():
        deps = set()
        for imp in index_module(path, all_files[path]).imports:
            target = _resolve(mod, imp)
            while target and target not in modules:  # `from pkg.mod import name` -> pkg.mod
                target = target.rpartition(".")[0]
            if target:
                deps.add(target)
        graph[mod] = deps
    reached: set[str] = set()
    stack = [m for m, p in modules.items() if _is_test(p)]
    while stack:
        cur = stack.pop()
        if cur not in reached:
            reached.add(cur)
            stack.extend(graph.get(cur, ()))
    out = []
    for path in changed:
        if not path.endswith(".py") or _is_test(path) or path.endswith("__init__.py"):
            continue
        if _module_name(path) not in reached:
            out.append(Finding(severity="low", check="test coverage", file=path,
                               message=f"no test reaches module '{_module_name(path)}' through its imports",
                               suggestion="add a test that exercises it", source="static"))
    return out


def pr_hygiene(title: str, body: str, requirement_id: str) -> list[Finding]:
    out = []
    if not re.match(rf"^{re.escape(requirement_id)} - \S", title):
        out.append(Finding(severity="medium", check="PR hygiene", source="static",
                           message=f"title should be '{requirement_id} - <description>'"))
    size_section = body.split("## Change Size", 1)[-1].split("\n## ", 1)[0] if "## Change Size" in body else ""
    ticked = re.findall(r"- \[x\] \*\*(Major|Minor|Patch)\*\*", size_section, re.I)
    if len(ticked) != 1:
        out.append(Finding(severity="high", check="PR hygiene",
                           message=f"exactly one Change Size box must be ticked (found {len(ticked)})",
                           suggestion="tick Major, Minor or Patch", source="static"))
    return out
