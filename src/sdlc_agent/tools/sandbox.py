"""Environment for running generated code: no credentials, no outbound network.

Generated code is untrusted (an LLM wrote it). It runs only in subprocesses that get:

* an **allowlisted environment**: only what Python and the OS need. API keys, tokens and every other
  variable of the orchestrator's process are dropped, so generated code cannot read them.
* a **network guard** (``_sandbox/sitecustomize.py``) that refuses DNS lookups and connections to anything
  but loopback. Set ``SDLC_ALLOW_NETWORK=1`` to disable it for a run that legitimately needs the network.

The network guard runs inside the same interpreter as the code it guards, so it stops accidental and
casual access, not a determined attacker. For hard isolation run the validator in a container with
networking disabled (see docs/security.md).
"""

from __future__ import annotations

import os
from pathlib import Path

from .. import config

GUARD_DIR = Path(__file__).resolve().parent.parent / "_sandbox"

# Needed by Python, git, compilers and temp files on Windows, macOS and Linux. Nothing secret.
ALLOWED_ENV = {
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR",
    "HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "LANG", "LC_ALL", "LC_CTYPE", "TZ",
    "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS", "VIRTUAL_ENV", "PYTHONIOENCODING",
    "SDLC_ALLOW_NETWORK",
}


def safe_env(root: Path, network_guard: bool = True) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k.upper() in ALLOWED_ENV}
    env["SDLC_ALLOW_NETWORK"] = "1" if config.get_bool("SDLC_ALLOW_NETWORK") else "0"
    paths = [str(GUARD_DIR)] if network_guard else []
    env["PYTHONPATH"] = os.pathsep.join([*paths, str(root)])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    return env
