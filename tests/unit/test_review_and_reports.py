"""Deterministic review checks, template filling and versioning."""

import pytest

from sdlc_agent.reports import fill_template
from sdlc_agent.tools import review_checks as rc
from sdlc_agent.tools.code_index import index_module
from sdlc_agent.tools.git_tool import bump
from sdlc_agent.workflow import _ticked_size


def test_commented_out_code_needs_more_than_two_lines():
    two = "x = 1\n# y = 2\n# z = 3\n"
    three = "x = 1\n# def old():\n#     y = compute()\n#     return y\n"
    prose = "# This explains why we do it.\n# It is not code at all.\n# Really not.\n"
    assert rc.commented_out_code({"a.py": two}) == []
    assert rc.commented_out_code({"a.py": prose}) == []
    found = rc.commented_out_code({"a.py": three})
    assert len(found) == 1 and found[0].line == 2


def test_duplicated_blocks_across_files():
    block = "\n".join(f"value_{i} = compute({i}) + offset" for i in range(7))
    found = rc.duplicated_blocks({"a.py": block, "b.py": "x = 0\n" + block})
    assert len(found) == 1 and "duplicates a.py:1" in found[0].message
    assert rc.duplicated_blocks({"a.py": block}) == []


def test_leftovers_flag_todo_and_debug_prints_but_not_in_tests():
    src = "def f():\n    print('debug')  \n    # TODO: fix\n"
    checks = {f.check for f in rc.leftovers({"app/x.py": src})}
    assert checks == {"debug output", "leftover TODO"}
    assert {f.check for f in rc.leftovers({"tests/test_x.py": src})} == {"leftover TODO"}


def test_untested_modules_follow_the_import_graph():
    files = {
        "pkg/__init__.py": "",
        "pkg/main.py": "from pkg.api import router\n",
        "pkg/api.py": "from .store import Store\n",
        "pkg/store.py": "class Store: ...\n",
        "pkg/orphan.py": "def lonely(): ...\n",
        "tests/test_app.py": "from pkg.main import create_app\n",
    }
    found = rc.untested_modules({p: files[p] for p in ("pkg/api.py", "pkg/store.py", "pkg/orphan.py")}, files)
    assert [f.file for f in found] == ["pkg/orphan.py"]


def test_pr_hygiene_requires_title_format_and_one_size_box():
    ok = "## Change Size\n- [ ] **Major** - b\n- [x] **Minor** - n\n- [ ] **Patch** - f\n"
    assert rc.pr_hygiene("REQ-1 - Add thing", ok, "REQ-1") == []
    two = ok.replace("[ ] **Patch**", "[x] **Patch**")
    assert any("exactly one" in f.message for f in rc.pr_hygiene("REQ-1 - Add thing", two, "REQ-1"))
    assert any("title" in f.message for f in rc.pr_hygiene("Add thing", ok, "REQ-1"))


def test_fill_template_keeps_structure_and_ticks_by_label():
    tpl = ("## Description\n<!-- here -->\n\nTicket #: <!-- id -->\n\n"
           "## Change Size\n- [ ] **Major** - b\n- [ ] **Minor** - n\n")
    out = fill_template(tpl, {"Description": "Real text"}, {"Minor"}, {"Ticket #": "REQ-9"})
    assert "Real text" in out and "<!-- here -->" not in out
    assert "Ticket #: REQ-9" in out
    assert "- [x] **Minor** - n" in out and "- [ ] **Major** - b" in out
    assert _ticked_size(out) == "minor"


@pytest.mark.parametrize("last,size,expected", [
    (None, "minor", "0.1.0"), ("1.2.3", "patch", "1.2.4"), ("1.2.3", "minor", "1.3.0"),
    ("1.2.3", "major", "2.0.0"), ("v0.9.9", "patch", "0.9.10"),
])
def test_semver_bump(last, size, expected):
    assert bump(last, size) == expected


def test_summary_sections_are_numbered_in_order_and_timeline_shows_each_attempt():
    import re
    import time

    from sdlc_agent.orchestrator.models import (
        AcceptanceCriterion,
        Plan,
        RequirementSpec,
        RunState,
        Task,
        TaskRecord,
    )
    from sdlc_agent.reports import render_summary

    tasks = [Task(id="T1", title="code", agent="coder"), Task(id="T2", title="v", agent="validator", depends_on=["T1"])]
    state = RunState(run_id="r", requirement_id="REQ-1", requirement_path="x", scenario="s", workspace="w",
                     provider="mock", created_at=time.time(),
                     spec=RequirementSpec(title="t", kind="greenfield", intent="i", problem_statement="p",
                                          acceptance_criteria=[AcceptanceCriterion(id="AC1", text="a")]),
                     plan=Plan(rationale="r", tasks=tasks, change_size="patch", change_size_reason="x"))
    state.tasks = {"T1": TaskRecord(task=tasks[0], attempts=2, runs=[[0.0, 1.0], [3.0, 4.0]]),
                   "T2": TaskRecord(task=tasks[1], attempts=2, runs=[[1.0, 2.0], [4.0, 5.0]])}
    text = render_summary(state, [])
    numbers = [int(n) for n in re.findall(r"^## (\d+)\. ", text, re.M)]
    assert numbers == list(range(1, len(numbers) + 1))  # greenfield has no impact section: no gap
    assert "re-run with validation feedback" in text and "| T1 | coder | 2 |" in text
    assert not re.search(r"^## (Tasks|Risks)$", text, re.M)  # plan headings nested, risks not duplicated


def test_code_index_finds_routes_and_relative_imports():
    src = '"""Doc."""\nfrom .store import S\n\n@router.get("/items")\ndef items(): ...\n'
    info = index_module("pkg/api.py", src)
    assert info.routes == ["GET /items"] and ".store" in info.imports and info.doc == "Doc."
