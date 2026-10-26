"""A local stand-in for an OpenAI-compatible model endpoint (``POST /v1/chat/completions``).

It reads each request the way a model would see it (system prompt = role, user prompt = sections) and
answers with the scenario's fixture for that role and task. It can also misbehave on purpose: return
HTTP 429/500 or a malformed answer once for chosen agents, so the client's retry and repair paths run.

Only the answer content is scripted; everything on the client side (HTTP, auth headers, parsing, schema
validation, retries, repair prompts, the whole workflow) is the production code path.
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from sdlc_agent.llm.base import LLMRequest
from sdlc_agent.llm.mock import MockProvider
from sdlc_agent.orchestrator.models import TaskOutput

ROLES = {
    "Requirement Analyst": "requirement_analyst", "Codebase Analyst": "codebase_analyst", "Planner": "planner",
    "Architect": "architect", "Coder": "coder", "Tester": "tester", "Documentation Writer": "doc_writer",
    "Code Reviewer": "reviewer",
}


class FakeLLMServer:
    def __init__(self, fixtures_root: Path, scenario: str, *, transient_once: set[str] = frozenset(),
                 malformed_once: set[str] = frozenset()):
        self.replay = MockProvider(fixtures_root)
        self.scenario = scenario
        self.transient_once = set(transient_once)
        self.malformed_once = set(malformed_once)
        self.requests: list[dict] = []  # what the client sent: path, headers, key
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - http.server API
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                status, payload = server.answer(self.path, self.headers, body)  # case-insensitive headers
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self.httpd.server_port}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.httpd.shutdown()

    # -- the "model" --------------------------------------------------------------
    def key_for(self, system: str, prompt: str) -> tuple[str, int]:
        role = re.search(r"^# Role: ([A-Za-z ]+?)(?: \(|$)", system, re.M).group(1).strip()
        agent = ROLES[role]
        if agent == "requirement_analyst" and "## Answers from the human" in prompt:
            return "requirement_analyst.refine", 1
        if agent in ("requirement_analyst", "codebase_analyst", "planner", "reviewer"):
            return agent, 1
        task = re.search(r'## Your task\n\{.*?"id": "(T\d+)"', prompt, re.S).group(1)
        attempt = 2 if "## Feedback from validation / previous attempts" in prompt else 1
        return f"{agent}.{task}", attempt

    def answer(self, path: str, headers, body: dict) -> tuple[int, dict]:
        system = next(m["content"] for m in body["messages"] if m["role"] == "system")
        prompt = next(m["content"] for m in body["messages"] if m["role"] == "user")
        key, attempt = self.key_for(system, prompt)
        repairing = "Your previous reply was rejected" in prompt
        self.requests.append({"path": path, "key": key, "attempt": attempt, "repair": repairing,
                              "auth": headers.get("Authorization", ""), "api_key": headers.get("api-key", ""),
                              "model": body.get("model"), "json_mode": body.get("response_format")})
        agent = key.split(".")[0]
        if agent in self.transient_once:
            self.transient_once.discard(agent)
            return 429, {"error": {"message": "rate limited"}}
        content = self.replay.complete(LLMRequest(agent=agent, system=system, prompt=prompt, schema=TaskOutput,
                                                  key=key, scenario=self.scenario, attempt=attempt))
        if agent in self.malformed_once and not repairing:
            self.malformed_once.discard(agent)
            content = "Sure! Here is my plan:\n" + content[: len(content) // 2]  # prose + truncated JSON
        return 200, {"choices": [{"index": 0, "finish_reason": "stop",
                                  "message": {"role": "assistant", "content": content}}],
                     "model": body.get("model", "fake")}
