"""Configuration: env vars with defaults, user-scope fallback, validation, secrets never shown."""

import pytest

from sdlc_agent import config
from sdlc_agent.workflow import Settings


def test_defaults_apply_when_nothing_is_set():
    assert config.get("SDLC_PROVIDER") == "mock"
    assert config.get_int("SDLC_MAX_ATTEMPTS") == 3
    assert config.get_bool("SDLC_ALLOW_NETWORK") is False


def test_process_environment_overrides_default(monkeypatch):
    monkeypatch.setenv("SDLC_MAX_ATTEMPTS", "5")
    assert config.get_int("SDLC_MAX_ATTEMPTS") == 5
    assert config.source("SDLC_MAX_ATTEMPTS") == "process"


def test_user_scope_is_used_when_process_has_nothing(monkeypatch):
    monkeypatch.setattr(config, "_user_scope", lambda n: "7" if n == "SDLC_WORKERS" else None)
    assert config.get_int("SDLC_WORKERS") == 7
    assert config.source("SDLC_WORKERS") == "user"
    monkeypatch.setenv("SDLC_WORKERS", "2")  # process still wins
    assert config.get_int("SDLC_WORKERS") == 2


@pytest.mark.parametrize("name,value,match", [
    ("SDLC_MAX_ATTEMPTS", "many", "whole number"),
    ("SDLC_MAX_ATTEMPTS", "0", "at least 1"),
    ("SDLC_PROVIDER", "gpt", "not one of"),
])
def test_invalid_values_fail_with_the_variable_name(monkeypatch, name, value, match):
    monkeypatch.setenv(name, value)
    with pytest.raises(config.ConfigError, match=match):
        config.get_int(name) if config.VARS[name].kind == "int" else config.get(name)
    assert any(name in e for e in config.validate_all())


def test_secrets_are_never_shown(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-" + "q" * 30)
    monkeypatch.setenv("SDLC_ALERT_WEBHOOK", "https://hooks.example/" + "z" * 20)
    rows = {name: value for name, value, _src, _help in config.describe()}
    assert rows["ANTHROPIC_API_KEY"] == "set" and rows["SDLC_ALERT_WEBHOOK"] == "set"
    assert rows["GITHUB_TOKEN"] == "not set"


def test_settings_read_config_and_flags_win(monkeypatch):
    monkeypatch.setenv("SDLC_MAX_LLM_CALLS", "12")
    monkeypatch.setenv("SDLC_WORKERS", "2")
    s = Settings(workers=6)
    assert s.max_llm_calls == 12 and s.workers == 6
