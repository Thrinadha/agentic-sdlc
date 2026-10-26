"""Brownfield codebase index built with ``ast``: modules, imports, HTTP routes, models, functions.

The CodebaseAnalyst agent reasons over this index (and the files it points to) instead of
guessing from file names.
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field

from .workspace import Workspace

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


@dataclass
class ModuleInfo:
    path: str
    doc: str = ""
    imports: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    routes: list[str] = field(default_factory=list)
    is_test: bool = False
    lines: int = 0


def _route(dec: ast.expr) -> str | None:
    # @router.get("/path") / @app.post("/path", ...)
    if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr in HTTP_METHODS
            and dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str)):
        return f"{dec.func.attr.upper()} {dec.args[0].value}"
    return None


def index_module(path: str, source: str) -> ModuleInfo:
    info = ModuleInfo(path=path, lines=source.count("\n") + 1,
                      is_test="/tests/" in f"/{path}" or path.split("/")[-1].startswith("test_"))
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        info.doc = f"<syntax error: {e}>"
        return info
    info.doc = (ast.get_docstring(tree) or "").split("\n")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            info.imports.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            mod = "." * node.level + (node.module or "")
            info.imports.append(mod)
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            info.classes.append(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            info.functions.append(node.name)
            info.routes.extend(r for r in (_route(d) for d in node.decorator_list) if r)
    info.imports = sorted(set(info.imports))
    return info


def build_index(ws: Workspace) -> dict:
    modules = [index_module(rel, ws.read(rel)) for rel in ws.files({".py"})]
    local_pkgs = {m.path.split("/")[0] for m in modules}
    graph = {
        m.path: sorted({i for i in m.imports if i.startswith(".") or i.split(".")[0] in local_pkgs})
        for m in modules
    }
    return {
        "modules": [asdict(m) for m in modules],
        "routes": sorted({r for m in modules for r in m.routes}),
        "internal_imports": graph,
        "other_files": [f for f in ws.files() if not f.endswith(".py")],
    }


def render_index(index: dict) -> str:
    lines = ["Routes:", *(f"  {r}" for r in index["routes"]), "", "Modules:"]
    for m in index["modules"]:
        tag = " (test)" if m["is_test"] else ""
        lines.append(f"  {m['path']}{tag} - {m['lines']} lines - {m['doc']}")
        if m["classes"]:
            lines.append(f"      classes: {', '.join(m['classes'])}")
        if m["functions"]:
            lines.append(f"      functions: {', '.join(m['functions'])}")
        deps = index["internal_imports"].get(m["path"])
        if deps:
            lines.append(f"      imports: {', '.join(deps)}")
    lines += ["", "Other files:", *(f"  {f}" for f in index["other_files"])]
    return "\n".join(lines)
