"""Claude via the official Anthropic SDK (``pip install -e .[anthropic]``).

Uses structured outputs (``messages.parse`` with the pydantic schema), so the answer is schema-valid JSON.
Settings: ``ANTHROPIC_API_KEY`` (secret), ``SDLC_MODEL``, ``SDLC_MAX_TOKENS``, ``SDLC_LLM_TIMEOUT``. The key
is read like every other setting (process environment, then the Windows user environment).
"""

from __future__ import annotations

from .. import config
from .base import LLMOutputError, LLMProvider, LLMRequest, TransientLLMError

DEFAULT_MODEL = "claude-opus-5-5"


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, model: str | None = None):
        try:
            import anthropic
        except ImportError as e:  # pragma: no cover - depends on optional extra
            raise RuntimeError("Anthropic SDK not installed: pip install -e .[anthropic]") from e
        key = config.raw("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set (process or user environment)")
        self._anthropic = anthropic
        # SDK retries are off: StructuredLLM owns retries, backoff and the call budget.
        self.client = anthropic.Anthropic(api_key=key, timeout=config.get_int("SDLC_LLM_TIMEOUT"), max_retries=0)
        self.model = model or config.get("SDLC_MODEL") or DEFAULT_MODEL
        self.max_tokens = config.get_int("SDLC_MAX_TOKENS")

    def complete(self, req: LLMRequest) -> str:
        a = self._anthropic
        try:
            resp = self.client.messages.parse(
                model=self.model,
                max_tokens=self.max_tokens,
                system=req.system,
                messages=[{"role": "user", "content": req.prompt}],
                output_format=req.schema,
            )
        except (a.RateLimitError, a.APIConnectionError, a.InternalServerError) as e:
            raise TransientLLMError(f"{type(e).__name__}: {e}") from e
        except (a.AuthenticationError, a.PermissionDeniedError) as e:
            raise RuntimeError("Anthropic rejected the credentials: check ANTHROPIC_API_KEY") from e
        if resp.stop_reason == "refusal":
            raise LLMOutputError(f"model declined the request ({req.agent})")
        if resp.stop_reason == "max_tokens":
            raise LLMOutputError(f"answer truncated at SDLC_MAX_TOKENS={self.max_tokens} ({req.agent})")
        if resp.parsed_output is None:
            raise LLMOutputError(f"no structured output returned ({req.agent})")
        return resp.parsed_output.model_dump_json()
