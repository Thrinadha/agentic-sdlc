"""Pick a provider by name: mock (default) | anthropic | openai."""

from __future__ import annotations

from pathlib import Path

from .base import LLMProvider
from .mock import MockProvider, RecordingProvider

PROVIDERS = ("mock", "anthropic", "openai")


def get_provider(name: str, fixtures_root: Path, record: bool = False) -> LLMProvider:
    if name == "mock":
        if record:
            raise ValueError("--record needs a live provider")
        return MockProvider(fixtures_root)
    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider
        provider: LLMProvider = AnthropicProvider()
    elif name == "openai":
        from .openai_compat import OpenAICompatibleProvider
        provider = OpenAICompatibleProvider()
    else:
        raise ValueError(f"unknown provider {name!r}; choose one of {', '.join(PROVIDERS)}")
    return RecordingProvider(provider, fixtures_root) if record else provider
