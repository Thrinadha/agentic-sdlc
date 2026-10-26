"""Thin, guarded wrapper around git for the workspace repository."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .. import config
from .proc import mask, run_logged

PROTECTED_BRANCHES = {"main", "master"}
SEMVER_TAG = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


class GitError(RuntimeError):
    pass


class Git:
    def __init__(self, root: Path):
        self.root = root

    def run(self, *args: str, check: bool = True, timeout: int | None = None) -> str:
        timeout = timeout or config.get_int("SDLC_GIT_TIMEOUT")
        cmd = ["git", "-c", "core.autocrlf=false", "-c", "commit.gpgsign=false", *args]
        try:
            proc = run_logged(cmd, cwd=self.root, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
        except subprocess.TimeoutExpired as e:
            raise GitError(f"git {' '.join(mask(a) for a in args)} did not finish within {timeout}s "
                           "(SDLC_GIT_TIMEOUT); the run can be resumed "
                           "with `sdlc resume`") from e
        if check and proc.returncode != 0:
            raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
        return proc.stdout.strip()

    # -- setup -------------------------------------------------------------
    def is_repo(self) -> bool:
        return (self.root / ".git").exists()

    def init(self, author: str = "sdlc-agent", email: str = "sdlc-agent@example.invalid") -> None:
        if not self.is_repo():
            self.run("init", "-q", "-b", "main")
        self.run("config", "user.name", author)
        self.run("config", "user.email", email)

    def ensure_ignored(self, *patterns: str) -> None:
        gi = self.root / ".gitignore"
        existing = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
        missing = [p for p in patterns if p not in existing]
        if missing:
            gi.write_text("\n".join([*existing, *missing]) + "\n", encoding="utf-8")

    def has_commits(self) -> bool:
        return self.run("rev-parse", "--verify", "HEAD", check=False) != ""

    # -- branches ----------------------------------------------------------
    def current_branch(self) -> str:
        return self.run("rev-parse", "--abbrev-ref", "HEAD", check=False) or "main"

    def head(self) -> str:
        return self.run("rev-parse", "HEAD", check=False)

    def checkout_new(self, branch: str, base: str = "main") -> None:
        if branch in PROTECTED_BRANCHES:
            raise GitError(f"refusing to work directly on {branch!r}")
        exists = self.run("branch", "--list", branch)
        if exists:
            self.run("checkout", "-q", branch)
        else:
            self.run("checkout", "-q", "-b", branch, base)

    def checkout(self, branch: str) -> None:
        self.run("checkout", "-q", branch)

    # -- changes -----------------------------------------------------------
    def status_files(self) -> list[str]:
        out = self.run("status", "--porcelain", "-uall")
        return [line[3:].strip().strip('"') for line in out.splitlines() if line.strip()]

    def diff_stat(self) -> str:
        self.run("add", "-A", "--intent-to-add")
        return self.run("diff", "--stat")

    def diff(self, base: str = "", paths: list[str] | None = None) -> str:
        args = ["diff", base] if base else ["diff"]
        return self.run(*args, "--", *(paths or []))

    def commit_all(self, message: str, allow_protected: bool = False) -> str:
        branch = self.current_branch()
        if branch in PROTECTED_BRANCHES and not allow_protected:
            raise GitError(f"refusing to commit to {branch!r}; work on a feature branch")
        self.run("add", "-A")
        self.run("commit", "-q", "-m", message)
        return self.head()

    def merge_no_ff(self, branch: str, message: str) -> str:
        self.checkout("main")
        self.run("merge", "--no-ff", "-q", "-m", message, branch)
        return self.head()

    # -- tags --------------------------------------------------------------
    def latest_semver_tag(self) -> str | None:
        tags = [t for t in self.run("tag", "--list").splitlines() if SEMVER_TAG.match(t)]
        if not tags:
            return None
        return max(tags, key=lambda t: tuple(int(x) for x in SEMVER_TAG.match(t).groups()))

    def tag(self, name: str, message: str) -> None:
        self.run("tag", "-a", name, "-m", message)

    def log_since(self, ref: str | None) -> list[str]:
        rng = f"{ref}..HEAD" if ref else "HEAD"
        return self.run("log", rng, "--first-parent", "--pretty=%s").splitlines()


def bump(version: str | None, size: str) -> str:
    major, minor, patch = (int(x) for x in SEMVER_TAG.match(version).groups()) if version else (0, 0, 0)
    if size == "major":
        return f"{major + 1}.0.0"
    if size == "minor":
        return f"{major}.{minor + 1}.0"
    if size == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError(f"unknown change size {size!r}")
