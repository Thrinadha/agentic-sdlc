from sdlc_agent.orchestrator.gates import GateRequest, InteractiveApprover, PolicyApprover
from sdlc_agent.orchestrator.models import Ambiguity

Q = [Ambiguity(id="Q1", question="Which channel?", severity="blocking", assumption="in-app")]


def scripted(*answers):
    it = iter(answers)
    return InteractiveApprover(input_fn=lambda _prompt: next(it))


def test_policy_follows_its_rules():
    p = PolicyApprover({"plan": "approve", "release": "reject"})
    assert p.decide(GateRequest(gate="plan", summary="")).approved
    assert not p.decide(GateRequest(gate="release", summary="")).approved
    assert not p.decide(GateRequest(gate="unknown-gate", summary="")).approved  # default deny


def test_blockers_are_never_auto_approved():
    p = PolicyApprover({"commit": "approve"})
    d = p.decide(GateRequest(gate="commit", summary="", blockers=["secret: app.py:3 [aws-access-key-id]"]))
    assert not d.approved and "secret" in d.note


def test_clarify_needs_answers_or_stops():
    req = GateRequest(gate="clarify", summary="", questions=Q)
    assert not PolicyApprover().decide(req).approved
    with_answers = PolicyApprover(answers={"Q1": "email"}).decide(req)
    assert with_answers.approved and with_answers.answers == {"Q1": "email"}
    assumed = PolicyApprover({"clarify": "assume"}).decide(req)
    assert assumed.approved and assumed.answers == {"Q1": "in-app"}


def test_interactive_yes_no():
    assert scripted("y").decide(GateRequest(gate="plan", summary="s")).approved
    assert not scripted("n").decide(GateRequest(gate="plan", summary="s")).approved


def test_interactive_override_requires_the_word_and_a_reason():
    req = GateRequest(gate="commit", summary="s", blockers=["tests failing"])
    assert not scripted("y").decide(req).approved
    d = scripted("override", "false positive, reviewed").decide(req)
    assert d.approved and d.note == "false positive, reviewed"


def test_interactive_clarify_collects_answers_and_defaults():
    req = GateRequest(gate="clarify", summary="s", questions=Q)
    assert scripted("").decide(req).answers == {"Q1": "in-app"}
    assert scripted("email").decide(req).answers == {"Q1": "email"}
    assert not scripted("stop").decide(req).approved
