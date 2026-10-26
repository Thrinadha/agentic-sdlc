"""Optional GitHub integration: push the branch and open a real PR.

Used only when ``GITHUB_TOKEN`` (secret) and ``SDLC_GITHUB_REPO`` (owner/name) are set, from the process or
the user environment; otherwise the PR stays a local package under ``.sdlc/``. The token is sent as an HTTP
header for one command at a time. It is never written to git config, a remote URL, or a log.
"""

from __future__ import annotations

import base64
import json
import re
import urllib.request

from .. import config
from ..http import http_open
from .git_tool import PROTECTED_BRANCHES, Git

REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def configured() -> bool:
    return bool(config.raw("GITHUB_TOKEN") and config.raw("SDLC_GITHUB_REPO"))


def _repo_and_token() -> tuple[str, str]:
    repo, token = config.get("SDLC_GITHUB_REPO"), config.raw("GITHUB_TOKEN")
    if not REPO.match(repo):
        raise ValueError(f"SDLC_GITHUB_REPO must look like owner/name, got {repo!r}")
    return repo, token


def push_branch(git: Git, branch: str) -> None:
    if branch in PROTECTED_BRANCHES:
        raise RuntimeError(f"refusing to push {branch!r}")
    repo, token = _repo_and_token()
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    git.run("-c", f"http.extraHeader=Authorization: Basic {basic}",
            "push", f"https://github.com/{repo}.git", f"{branch}:{branch}")


def open_pr(branch: str, title: str, body: str, base: str = "main") -> str:
    repo, token = _repo_and_token()
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/pulls",
        data=json.dumps({"title": title, "head": branch, "base": base, "body": body}).encode(),
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28"},
        method="POST",
    )
    with http_open(req, timeout=30) as resp:
        return json.loads(resp.read())["html_url"]
