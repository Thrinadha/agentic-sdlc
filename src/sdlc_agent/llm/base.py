"""Provider-neutral LLM interface plus the structured-output wrapper every agent uses.

A provider only has to turn (system, prompt, schema) into JSON text. The wrapper handles:
* call budget (a hard cap on LLM calls per run)
* transient errors (rate limits, timeouts): exponential backoff
* invalid output: a repair prompt that shows the model its validation error
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace

from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMRequest:
    agent: str
    system: str
    prompt: str
    schema: type[BaseModel]
    key: str  # stable id of this call within a run, e.g. "coder.T4" (used for replay/recording)
    scenario: str = ""
    attempt: int = 1


class TransientLLMError(Exception):
    """Retryable: rate limit, overload, timeout, connection reset."""


class LLMOutputError(Exception):
    """The model's answer could not be turned into the expected schema."""


class BudgetExceeded(Exception):
    pass


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def complete(self, req: LLMRequest) -> str:
        """Return the model's answer as JSON text matching ``req.schema``."""


class Budget:
    def __init__(self, max_calls: int):
        self.max_calls = max_calls
        self.used = 0
        self._lock = threading.Lock()

    def consume(self) -> None:
        with self._lock:
            if self.used >= self.max_calls:
                raise BudgetExceeded(f"LLM call budget of {self.max_calls} exhausted")
            self.used += 1


def extract_json(text: str) -> object:
    """Parse a model answer. Plain JSON first; only then a ```json fence or the outermost {...}.

    The order matters: generated file contents often contain ``` fences of their own.
    """
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    if text.startswith("```"):
        fenced = re.match(r"```(?:json)?\s*(.*)```$", text, re.S)
        if fenced:
            try:
                return json.loads(fenced.group(1))
            except json.JSONDecodeError:
                pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start:end + 1])
    return json.loads(text)  # raises with a useful message


class StructuredLLM:
    def __init__(self, provider: LLMProvider, budget: Budget, on_call=None,
                 transport_retries: int = 3, repairs: int = 2, backoff: float = 1.5, transcripts=None):
        self.provider = provider
        self.budget = budget
        self.on_call = on_call or (lambda **_: None)
        self.transcripts = transcripts  # observability.TranscriptWriter when --debug is on
        self.transport_retries = transport_retries
        self.repairs = repairs
        self.backoff = backoff

    def call(self, req: LLMRequest) -> BaseModel:
        current = req
        last_error = ""
        for repair in range(self.repairs + 1):
            raw = self._complete_with_retry(current)
            try:
                return req.schema.model_validate(extract_json(raw))
            except (json.JSONDecodeError, ValidationError) as e:
                last_error = str(e)[:2000]
                self.on_call(outcome="repair", agent=req.agent, key=req.key, error=last_error[:300])
                current = replace(
                    req,
                    prompt=f"{req.prompt}\n\n---\nYour previous reply was rejected:\n{last_error}\n"
                           "Reply again with ONLY a JSON object that matches the schema.",
                    key=f"{req.key}.repair{repair + 1}",
                )
        raise LLMOutputError(f"{req.agent}: output still invalid after {self.repairs} repair attempts: {last_error}")

    def _complete_with_retry(self, req: LLMRequest) -> str:
        delay = self.backoff
        for i in range(self.transport_retries + 1):
            self.budget.consume()
            t0 = time.time()
            try:
                out = self.provider.complete(req)
                seconds = round(time.time() - t0, 2)
                self.on_call(outcome="ok", agent=req.agent, key=req.key, seconds=seconds)
                log.debug("llm %s %s attempt=%s prompt=%d chars answer=%d chars in %.2fs (budget %d/%d)",
                          self.provider.name, req.key, req.attempt, len(req.prompt), len(out), seconds,
                          self.budget.used, self.budget.max_calls)
                if self.transcripts is not None:
                    self.transcripts.write(req.key, req.attempt, req.system, req.prompt, out)
                return out
            except TransientLLMError as e:
                log.debug("llm %s %s transient error: %s", self.provider.name, req.key, e)
                self.on_call(outcome="transient", agent=req.agent, key=req.key, error=str(e)[:200])
                if i == self.transport_retries:
                    raise
                time.sleep(delay)
                delay *= 2
        raise AssertionError("unreachable")
