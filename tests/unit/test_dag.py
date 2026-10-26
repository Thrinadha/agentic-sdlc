import pytest

from sdlc_agent.orchestrator.dag import PlanError, TaskGraph
from sdlc_agent.orchestrator.models import Task


def t(tid, *deps, agent="coder"):
    return Task(id=tid, title=tid, agent=agent, depends_on=list(deps))


def test_levels_group_independent_tasks():
    g = TaskGraph([t("A"), t("B", "A"), t("C", "A"), t("D", "B", "C")])
    assert g.levels() == [["A"], ["B", "C"], ["D"]]


def test_cycle_is_rejected():
    with pytest.raises(PlanError, match="cycle"):
        TaskGraph([t("A", "C"), t("B", "A"), t("C", "B")])


def test_unknown_dependency_is_rejected():
    with pytest.raises(PlanError, match="unknown task"):
        TaskGraph([t("A", "Z")])


def test_self_dependency_and_duplicates_are_rejected():
    with pytest.raises(PlanError):
        TaskGraph([t("A", "A")])
    with pytest.raises(PlanError, match="duplicate"):
        TaskGraph([t("A"), t("A")])


def test_ready_set_respects_done_running_and_blocked():
    g = TaskGraph([t("A"), t("B"), t("C", "A", "B")])
    assert g.ready(set(), set(), set()) == ["A", "B"]
    assert g.ready({"A"}, {"B"}, set()) == []
    assert g.ready({"A", "B"}, set(), set()) == ["C"]
    assert g.ready({"A", "B"}, set(), {"C"}) == []


def test_ancestors_are_transitive():
    g = TaskGraph([t("A"), t("B", "A"), t("C", "B")])
    assert g.ancestors("C") == {"A", "B"}


def test_mermaid_lists_every_edge():
    out = TaskGraph([t("A"), t("B", "A")]).to_mermaid()
    assert "A --> B" in out
