"""Any OpenAI-compatible Chat Completions endpoint, using the standard library only.

Covers OpenAI, Azure OpenAI, Ollama, vLLM, LM Studio and similar servers:

* OpenAI:  OPENAI_API_KEY, SDLC_MODEL (e.g. a GPT model id)
* Azure:   SDLC_OPENAI_BASE_URL=https://<resource>.openai.azure.com/openai/deployments/<deployment>
           SDLC_OPENAI_API_VERSION=<api version>, OPENAI_API_KEY=<azure key>
* Ollama:  SDLC_OPENAI_BASE_URL=http://localhost:11434/v1, SDLC_MODEL=<local model>, no key needed
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from .. import config
from ..http import check_url, http_open
from .base import LLMOutputError, LLMProvider, LLMRequest, TransientLLMError


class OpenAICompatibleProvider(LLMProvider):
    name = "openai"

    def __init__(self, model: str | None = None, base_url: str | None = None):
        self.base_url = check_url((base_url or config.get("SDLC_OPENAI_BASE_URL")).rstrip("/"))
        self.api_version = config.get("SDLC_OPENAI_API_VERSION")
        self.key = config.raw("OPENAI_API_KEY")
        self.model = model or config.get("SDLC_MODEL")
        self.timeout = config.get_int("SDLC_LLM_TIMEOUT")
        if not self.model and not self.api_version:
            raise RuntimeError("set SDLC_MODEL to the model id for the OpenAI-compatible provider")

    def complete(self, req: LLMRequest) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_version:  # Azure OpenAI
            url += f"?api-version={self.api_version}"
            headers["api-key"] = self.key
        elif self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        body = {
            "messages": [{"role": "system", "content": req.system}, {"role": "user", "content": req.prompt}],
            "response_format": {"type": "json_object"},
        }
        if self.model:
            body["model"] = self.model
        request = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
        try:
            with http_open(request, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                raise TransientLLMError(f"HTTP {e.code}") from e
            raise RuntimeError(f"LLM endpoint returned HTTP {e.code}: {e.read()[:300]!r}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise TransientLLMError(str(e)) from e
        choice = data["choices"][0]
        if choice.get("finish_reason") == "length":
            raise LLMOutputError(f"answer truncated ({req.agent})")
        return choice["message"]["content"] or ""
