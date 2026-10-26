"""Provider-neutral LLM layer: parsing, repair, retries, budget, replay and recording."""

import json

import pytest
from pydantic import BaseModel

from sdlc_agent.llm.base import (
    Budget,
    BudgetExceeded,
    LLMOutputError,
    LLMProvider,
    LLMRequest,
    StructuredLLM,
    TransientLLMError,
    extract_json,
)
from sdlc_agent.llm.mock import MissingFixture, MockProvider, RecordingProvider


class Out(BaseModel):
    answer: int


class Scripted(LLMProvider):
    name = "scripted"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def complete(self, req):
        self.prompts.append(req.prompt)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def req(key="k", attempt=1, scenario="s"):
    return LLMRequest(agent="a", system="sys", prompt="p", schema=Out, key=key, scenario=scenario, attempt=attempt)


def test_extract_json_keeps_code_fences_inside_strings():
    payload = {"files": [{"path": "README.md", "content": "Run:\n```bash\npytest\n```\n"}]}
    assert extract_json(json.dumps(payload)) == payload
    assert extract_json("```json\n" + json.dumps(payload) + "\n```") == payload
    assert extract_json('Sure! Here it is: {"answer": 1} hope that helps') == {"answer": 1}


def test_invalid_output_gets_a_repair_prompt_with_the_error():
    p = Scripted('{"answer": "not a number"}', '{"answer": 42}')
    assert StructuredLLM(p, Budget(10)).call(req()).answer == 42
    assert "rejected" in p.prompts[1] and "answer" in p.prompts[1]


def test_gives_up_after_repairs():
    p = Scripted("nope", "still nope", "never")
    with pytest.raises(LLMOutputError):
        StructuredLLM(p, Budget(10), repairs=2).call(req())


def test_transient_errors_are_retried_with_backoff():
    p = Scripted(TransientLLMError("429"), TransientLLMError("503"), '{"answer": 1}')
    assert StructuredLLM(p, Budget(10), backoff=0).call(req()).answer == 1


def test_budget_is_a_hard_cap():
    p = Scripted('{"answer": 1}', '{"answer": 2}')
    llm = StructuredLLM(p, Budget(1))
    llm.call(req())
    with pytest.raises(BudgetExceeded):
        llm.call(req())


def test_mock_inlines_content_files_and_prefers_attempt_specific_fixtures(tmp_path):
    d = tmp_path / "s"
    (d / "files").mkdir(parents=True)
    (d / "files" / "a.py").write_text("print(1)\n")
    (d / "coder.T1.json").write_text(json.dumps({"files": [{"path": "a.py", "content_file": "files/a.py"}]}))
    (d / "coder.T1.attempt2.json").write_text(json.dumps({"files": [], "notes": "second"}))
    m = MockProvider(tmp_path)
    first = json.loads(m.complete(req("coder.T1")))
    assert first["files"][0]["content"] == "print(1)\n"
    assert json.loads(m.complete(req("coder.T1", attempt=2)))["notes"] == "second"
    assert json.loads(m.complete(req("coder.T1", attempt=3)))["files"][0]["path"] == "a.py"  # falls back
    with pytest.raises(MissingFixture):
        m.complete(req("planner"))


def test_recording_provider_writes_replayable_fixtures(tmp_path):
    rec = RecordingProvider(Scripted('{"answer": 7}'), tmp_path)
    rec.complete(req("planner", scenario="new"))
    assert json.loads(MockProvider(tmp_path).complete(req("planner", scenario="new"))) == {"answer": 7}
