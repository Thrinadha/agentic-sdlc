"""All configuration in one place: every setting is an environment variable with a safe default.

Precedence (highest first):
  1. a command-line flag (where one exists)
  2. the process environment
  3. on Windows, the **user** environment (HKCU\\Environment), so variables set with
     ``[Environment]::SetEnvironmentVariable(name, value, 'User')`` work even in terminals or editors
     that were opened before the variable was set
  4. the default below

Secrets are only ever read from the environment (never from files in the repo, never from flags), and are
never printed: ``describe()`` reports them as ``set`` / ``not set``. In GitHub Actions, put secrets in
repository *secrets* and other settings in repository *variables* (see .github/workflows/ci.yml).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Var:
    name: str
    default: str
    help: str
    secret: bool = False
    kind: str = "str"  # str | int | bool | choice
    choices: tuple[str, ...] = ()
    minimum: int | None = None


VARS: dict[str, Var] = {v.name: v for v in [
    # --- provider
    Var("SDLC_PROVIDER", "mock", "LLM provider", kind="choice", choices=("mock", "anthropic", "openai")),
    Var("SDLC_MODEL", "", "model id (anthropic default: claude-opus-5-5; required for openai)"),
    Var("SDLC_MAX_TOKENS", "16000", "max output tokens per LLM call (anthropic)", kind="int", minimum=1024),
    Var("SDLC_LLM_TIMEOUT", "600", "seconds per LLM HTTP request", kind="int", minimum=10),
    Var("SDLC_OPENAI_BASE_URL", "https://api.openai.com/v1", "OpenAI-compatible endpoint (Azure, Ollama, vLLM)"),
    Var("SDLC_OPENAI_API_VERSION", "", "Azure OpenAI api-version (enables Azure auth)"),
    Var("ANTHROPIC_API_KEY", "", "Claude API key", secret=True),
    Var("OPENAI_API_KEY", "", "OpenAI / Azure OpenAI key", secret=True),
    # --- orchestration limits
    Var("SDLC_MAX_LLM_CALLS", "80", "hard budget of LLM calls per run", kind="int", minimum=1),
    Var("SDLC_MAX_ATTEMPTS", "3", "attempts per task before escalating to a human", kind="int", minimum=1),
    Var("SDLC_WORKERS", "4", "tasks running in parallel", kind="int", minimum=1),
    Var("SDLC_TEST_TIMEOUT", "300", "seconds for the generated test suite", kind="int", minimum=10),
    Var("SDLC_GIT_TIMEOUT", "120", "seconds per git command", kind="int", minimum=5),
    Var("SDLC_MAX_FILE_BYTES", "200000", "largest file an agent may write", kind="int", minimum=1000),
    Var("SDLC_MAX_FILES_PER_TASK", "40", "most files one task may write", kind="int", minimum=1),
    # --- paths and policy
    Var("SDLC_HOME", "", "project root holding fixtures/, standards/, policies/ (default: this checkout)"),
    Var("SDLC_WORKSPACES_DIR", "", "where `implement` creates workspaces (default: <SDLC_HOME>/workspaces)"),
    Var("SDLC_POLICY_FILE", "", "gate policy for --policy auto (default: policies/auto.yaml)"),
    # --- security
    Var("SDLC_ALLOW_NETWORK", "0", "allow generated code to use the network", kind="bool"),
    Var("SDLC_DEPENDENCY_AUDIT", "0", "run pip-audit on generated projects (needs network)", kind="bool"),
    # --- observability
    Var("SDLC_DEBUG", "0", "save redacted LLM prompts/answers per run", kind="bool"),
    Var("SDLC_ALERT_WEBHOOK", "", "Slack/Teams/Mattermost/generic webhook URL for alerts", secret=True),
    Var("SDLC_ALERT_FORMAT", "slack", "webhook payload", kind="choice", choices=("slack", "json")),
    Var("SDLC_ALERT_MIN_SEVERITY", "warning", "lowest severity that alerts", kind="choice",
        choices=("info", "warning", "error", "critical")),
    # --- GitHub (optional)
    Var("GITHUB_TOKEN", "", "token to push the branch and open a real PR", secret=True),
    Var("SDLC_GITHUB_REPO", "", "owner/name of the GitHub repository for real PRs"),
]}


class ConfigError(ValueError):
    pass


def _user_scope(name: str) -> str | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            return str(value)
    except OSError:
        return None


def source(name: str) -> str:
    if os.environ.get(name):
        return "process"
    if _user_scope(name):
        return "user"
    return "default"


def raw(name: str) -> str:
    value = os.environ.get(name) or _user_scope(name)
    if value:
        return value.strip()
    return VARS[name].default if name in VARS else ""


def get(name: str) -> str:
    var = VARS[name]
    value = raw(name)
    if var.kind == "choice" and value not in var.choices:
        raise ConfigError(f"{name}={value!r} is not one of {', '.join(var.choices)}")
    return value


def get_int(name: str) -> int:
    var = VARS[name]
    value = raw(name)
    try:
        number = int(value)
    except ValueError:
        raise ConfigError(f"{name}={value!r} must be a whole number") from None
    if var.minimum is not None and number < var.minimum:
        raise ConfigError(f"{name}={number} must be at least {var.minimum}")
    return number


def get_bool(name: str) -> bool:
    return raw(name).lower() in ("1", "true", "yes", "on")


def export_to_process(*names: str) -> None:
    """Copy user-scope values into this process so child processes and SDKs see them too."""
    for name in names:
        if not os.environ.get(name):
            value = _user_scope(name)
            if value:
                os.environ[name] = value


def describe() -> list[tuple[str, str, str, str]]:
    """(name, value shown, source, help) for every setting. Secrets show only set / not set."""
    rows = []
    for var in VARS.values():
        value = raw(var.name)
        shown = ("set" if value else "not set") if var.secret else (value or "-")
        rows.append((var.name, shown, source(var.name), var.help))
    return rows


def validate_all() -> list[str]:
    errors = []
    for var in VARS.values():
        try:
            if var.kind == "int":
                get_int(var.name)
            elif var.kind == "choice":
                get(var.name)
        except ConfigError as e:
            errors.append(str(e))
    return errors
