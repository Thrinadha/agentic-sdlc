"""sdlc: requirement -> plan -> code/tests/docs -> PR -> review -> change request -> release.

Every option has an environment-variable equivalent (see `sdlc config`); flags win over variables.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

from . import config
from .diagnostics import _jsonl, debug_report, filter_events, format_event
from .observability import Alerter, setup_console
from .orchestrator.events import console, verify_log
from .orchestrator.gates import Approver, InteractiveApprover, PolicyApprover
from .orchestrator.models import Phase
from .reports import render_validation, write
from .requirement import load_requirement
from .tools.git_tool import Git
from .tools.sandbox import safe_env
from .tools.workspace import Workspace
from .workflow import PROJECT_ROOT, Run, Settings, change_request, latest_run_id, release, run_validation

log = logging.getLogger(__name__)


def default_policy() -> Path:
    return Path(config.get("SDLC_POLICY_FILE") or PROJECT_ROOT / "policies" / "auto.yaml")


def default_workspaces() -> Path:
    return Path(config.get("SDLC_WORKSPACES_DIR") or PROJECT_ROOT / "workspaces")


def _approver(args) -> Approver:
    if args.policy == "auto":
        return PolicyApprover.from_files(Path(args.policy_file) if args.policy_file else default_policy(),
                                         Path(args.answers) if args.answers else None)
    answers = PolicyApprover.from_files(None, Path(args.answers)).answers if args.answers else None
    return InteractiveApprover(answers=answers)


def _settings(args) -> Settings:
    return Settings(provider=args.provider, record=getattr(args, "record", False),
                    max_llm_calls=args.max_llm_calls, max_attempts=args.max_attempts, workers=args.workers,
                    quiet=getattr(args, "quiet", False), debug=True if args.debug else None)


# ====================================================================== parser


def build_parser() -> argparse.ArgumentParser:
    base = argparse.ArgumentParser(add_help=False)
    base.add_argument("-v", "--verbose", action="store_true", help="print debug logs to the console")

    run_opts = argparse.ArgumentParser(add_help=False)
    run_opts.add_argument("--provider", choices=["mock", "anthropic", "openai"],
                          help="LLM provider [SDLC_PROVIDER, default mock]")
    run_opts.add_argument("--policy", default="interactive", choices=["interactive", "auto"],
                          help="who approves gates: you at the terminal (default) or a written policy")
    run_opts.add_argument("--policy-file", help="gate policy for --policy auto [SDLC_POLICY_FILE]")
    run_opts.add_argument("--answers", help="YAML answers to clarification questions (<id>: <answer>)")
    run_opts.add_argument("--max-llm-calls", type=int, help="LLM call budget per run [SDLC_MAX_LLM_CALLS]")
    run_opts.add_argument("--max-attempts", type=int, help="attempts per task before escalating [SDLC_MAX_ATTEMPTS]")
    run_opts.add_argument("--workers", type=int, help="tasks in parallel [SDLC_WORKERS]")
    run_opts.add_argument("--debug", action="store_true", help="save redacted LLM prompts/answers [SDLC_DEBUG]")

    ws_req = argparse.ArgumentParser(add_help=False)
    ws_req.add_argument("--workspace", "-w", required=True, help="workspace (target repository) folder")
    ws_req.add_argument("--run", help="run id (default: the latest run in the workspace)")

    ap = argparse.ArgumentParser(prog="sdlc", description=__doc__, parents=[base])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("implement", parents=[base, run_opts], help="requirement -> plan -> code -> commit -> PR")
    p.add_argument("requirement", help="requirement markdown file")
    p.add_argument("--workspace", "-w", help="workspace folder [default: SDLC_WORKSPACES_DIR/<scenario>]")
    p.add_argument("--record", action="store_true", help="save live LLM answers as replay fixtures")

    for name, help_ in (("resume", "continue a stopped or failed run"),
                        ("review", "review the PR against the coding standards (Gate 4 for fixes)"),
                        ("cr", "draft the change request"),
                        ("release", "merge gate + release gate, then tag the semver release")):
        sub.add_parser(name, parents=[base, run_opts, ws_req], help=help_)

    p = sub.add_parser("validate", parents=[base], help="run the validation suite on a workspace")
    p.add_argument("--workspace", "-w", required=True)

    p = sub.add_parser("logs", parents=[base, ws_req], help="show and filter a run's event log")
    p.add_argument("--type", help="comma-separated event types, e.g. task.failed,gate,validate,warn")
    p.add_argument("--task", help="only events about this task id, e.g. T3")
    p.add_argument("--grep", help="only events containing this text")
    p.add_argument("--tail", type=int, help="only the last N events")
    p.add_argument("--json", action="store_true", help="raw JSON lines")
    p.add_argument("--release", action="store_true", help="the release log instead of a run log")
    p.add_argument("--debug-log", action="store_true", help="print the run's debug log (commands, timings)")

    sub.add_parser("debug", parents=[base, ws_req], help="diagnose a run: what failed, why, and the next step")

    p = sub.add_parser("alerts", parents=[base], help="list a run's alerts, or send a test alert")
    p.add_argument("--workspace", "-w")
    p.add_argument("--run")
    p.add_argument("--test", action="store_true", help="send a test alert to the configured sinks")

    p = sub.add_parser("audit", parents=[base], help="verify the tamper-evident logs of a workspace")
    p.add_argument("--workspace", "-w", required=True)

    sub.add_parser("config", parents=[base], help="show every setting, its value and where it came from")
    sub.add_parser("doctor", parents=[base], help="check that this machine is ready to run the system")

    p = sub.add_parser("demo", parents=[base], help="run all example scenarios end to end (offline)")
    p.add_argument("--out", default=str(PROJECT_ROOT / "examples" / "outputs"))
    p.add_argument("--workspaces", help="where demo workspaces go [default: SDLC_WORKSPACES_DIR/demo]")
    p.add_argument("--quiet", action="store_true")
    return ap


# ====================================================================== commands


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_console(args.verbose)
    try:
        return _dispatch(args)
    except config.ConfigError as e:
        console(f"configuration error: {e}  (see `sdlc config`)")
        return 2
    except KeyboardInterrupt:
        console("\ninterrupted; the run is checkpointed, continue it with `sdlc resume`")
        return 130
    except Exception as e:  # noqa: BLE001 - one readable line instead of a traceback, unless -v
        if args.verbose:
            traceback.print_exc()
        ws = getattr(args, "workspace", None)
        console(f"error: {type(e).__name__}: {e}")
        if ws:
            console(f"diagnose with: sdlc debug -w {ws}")
        return 1


def _dispatch(args) -> int:
    cmd = args.cmd
    if cmd == "demo":
        workspaces = Path(args.workspaces) if args.workspaces else default_workspaces() / "demo"
        return demo(Path(args.out), workspaces, quiet=args.quiet)
    if cmd == "config":
        return cmd_config()
    if cmd == "doctor":
        return cmd_doctor()
    if cmd == "alerts":
        return cmd_alerts(args)
    if cmd == "validate":
        report = run_validation(Workspace(Path(args.workspace)))
        console(render_validation(report))
        return 0 if report.passed else 1
    if cmd == "audit":
        return cmd_audit(Path(args.workspace))
    if cmd == "logs":
        return cmd_logs(args)
    if cmd == "debug":
        ws = Path(args.workspace)
        run_dir = ws / ".sdlc" / "runs" / (args.run or latest_run_id(ws))
        report = debug_report(run_dir, ws)
        write(run_dir / "reports" / "debug.md", report)
        console(report)
        return 0

    approver, settings = _approver(args), _settings(args)
    if cmd == "implement":
        req = load_requirement(Path(args.requirement))
        ws = Path(args.workspace) if args.workspace else default_workspaces() / req.scenario
        state = Run.new(Path(args.requirement), ws, approver, settings).implement()
        return _report(state, ws)
    ws = Path(args.workspace)
    if cmd == "resume":
        state = Run.load(ws, args.run, approver, settings).implement()
        return _report(state, ws)
    if cmd == "review":
        state = Run.load(ws, args.run, approver, settings).review()
        console(f"review: {state.review.verdict} -> {ws / '.sdlc' / 'runs' / state.run_id / 'reports' / 'review.md'}")
        return 0
    if cmd == "cr":
        console(f"change request: {change_request(ws, approver, settings, args.run)}")
        return 0
    if cmd == "release":
        path = release(ws, approver, settings)
        console(f"release notes: {path}" if path else "nothing released")
        return 0 if path else 1
    return 2


def _report(state, ws: Path) -> int:
    run_dir = ws / ".sdlc" / "runs" / state.run_id
    console("")
    console(f"run {state.run_id}: phase = {state.phase.value}")
    console(f"reports: {run_dir / 'reports'}")
    if state.error:
        console(f"error: {state.error}")
    ok = state.phase in (Phase.PR_READY, Phase.REVIEWED, Phase.DONE)
    if not ok:
        console(f"diagnose with: sdlc debug -w {ws} --run {state.run_id}")
    return 0 if ok else 1


def cmd_config() -> int:
    rows = config.describe()
    width = max(len(r[0]) for r in rows)
    console(f"{'VARIABLE':<{width}}  {'VALUE':<28} {'SOURCE':<8} DESCRIPTION")
    for name, value, src, help_ in rows:
        shown = value if len(value) <= 28 else value[:25] + "..."
        console(f"{name:<{width}}  {shown:<28} {src:<8} {help_}")
    errors = config.validate_all()
    for e in errors:
        console(f"INVALID: {e}")
    console("\nsource: process = this shell, user = your user environment (Windows), default = built in."
            "\nSecrets are never shown. Set one for your user, e.g. PowerShell:"
            "\n  [Environment]::SetEnvironmentVariable('ANTHROPIC_API_KEY', '<key>', 'User')")
    return 1 if errors else 0


def cmd_audit(ws: Path) -> int:
    logs = sorted((ws / ".sdlc").rglob("*events.jsonl"))
    results = [(p, *verify_log(p)) for p in logs]
    for p, ok, msg in results:
        console(f"{'OK  ' if ok else 'FAIL'} {p.relative_to(ws)}: {msg}")
    if not logs:
        console(f"no logs found under {ws / '.sdlc'}")
    return 0 if logs and all(ok for _, ok, _ in results) else 1


def cmd_logs(args) -> int:
    ws = Path(args.workspace)
    if args.release:
        path = ws / ".sdlc" / ("release-debug.log" if args.debug_log else "release-events.jsonl")
    else:
        run_dir = ws / ".sdlc" / "runs" / (args.run or latest_run_id(ws))
        path = run_dir / ("debug.log" if args.debug_log else "events.jsonl")
    if not path.exists():
        console(f"no log at {path}")
        return 1
    if args.debug_log:
        lines = path.read_text(encoding="utf-8").splitlines()
        if args.grep:
            lines = [x for x in lines if args.grep.lower() in x.lower()]
        for line in lines[-args.tail:] if args.tail else lines:
            console(line)
        return 0
    types = [t.strip() for t in args.type.split(",")] if args.type else None
    events = filter_events(_jsonl(path), types, args.task, args.grep, args.tail)
    for e in events:
        console(json.dumps(e) if args.json else format_event(e))
    if not events:
        console("(no matching events)")
    return 0


def cmd_alerts(args) -> int:
    if args.test:
        sink_file = Path(tempfile.gettempdir()) / "sdlc-test-alerts.jsonl"
        alerter = Alerter.from_env(sink_file, context={"run_id": "test", "requirement": "TEST-0"})
        sent = alerter.alert("warning", "Test alert", "If you can read this, sdlc alerts reach you.")
        names = ", ".join(s.name for s in alerter.sinks)
        console(f"test alert sent to: {names}" if sent else "alert filtered by SDLC_ALERT_MIN_SEVERITY")
        if len(alerter.sinks) == 1:
            console("no webhook configured: set SDLC_ALERT_WEBHOOK (process or user environment) to get alerts "
                    "in Slack/Teams/Mattermost")
        return 0
    if not args.workspace:
        console("give --workspace (or --test)")
        return 2
    ws = Path(args.workspace)
    run_dir = ws / ".sdlc" / "runs" / (args.run or latest_run_id(ws))
    alerts = _jsonl(run_dir / "alerts.jsonl")
    for a in alerts:
        console(f"[{a['severity']:<8}] {a['title']}: {a['message'][:160]}")
    if not alerts:
        console("(no alerts)")
    return 0


def _check(results: list, status: str, name: str, detail: str) -> None:
    results.append((status, name, detail))


def cmd_doctor() -> int:
    r: list[tuple[str, str, str]] = []
    v = sys.version_info
    _check(r, "OK" if v >= (3, 10) else "FAIL", "python", f"{v.major}.{v.minor}.{v.micro} (needs >= 3.10)")
    git = shutil.which("git")
    if git:
        out = subprocess.run([git, "--version"], capture_output=True, text=True, timeout=60).stdout.strip()
        _check(r, "OK", "git", out)
    else:
        _check(r, "FAIL", "git", "not found on PATH")
    for module, need, why in (("pydantic", "FAIL", "core"), ("yaml", "FAIL", "core"),
                              ("fastapi", "FAIL", "generated apps (pip install -e .[app])"),
                              ("sqlalchemy", "FAIL", "generated apps"), ("httpx", "FAIL", "generated app tests"),
                              ("pytest", "FAIL", "test check"), ("ruff", "WARN", "lint check"),
                              ("bandit", "WARN", "security check"), ("pip_audit", "WARN", "dependency audit"),
                              ("anthropic", "INFO", "only for --provider anthropic")):
        found = importlib.util.find_spec(module) is not None
        _check(r, "OK" if found else need, f"package {module}", "installed" if found else f"missing: {why}")
    errors = config.validate_all()
    _check(r, "FAIL" if errors else "OK", "configuration", "; ".join(errors) or "all settings valid")
    provider = config.get("SDLC_PROVIDER") if not errors else "mock"
    if provider == "anthropic":
        _check(r, "OK" if config.raw("ANTHROPIC_API_KEY") else "FAIL", "provider anthropic",
               "ANTHROPIC_API_KEY " + ("set" if config.raw("ANTHROPIC_API_KEY") else "not set"))
    elif provider == "openai":
        _check(r, "OK" if config.raw("SDLC_MODEL") else "FAIL", "provider openai",
               "SDLC_MODEL " + ("set" if config.raw("SDLC_MODEL") else "not set"))
    else:
        _check(r, "OK", "provider mock", "offline replay, no key needed")
    for d in ("fixtures", "standards", "policies"):
        _check(r, "OK" if (PROJECT_ROOT / d).is_dir() else "FAIL", f"SDLC_HOME/{d}", str(PROJECT_ROOT / d))
    try:
        target = default_workspaces()
        target.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target):
            pass
        _check(r, "OK", "workspaces writable", str(target))
    except OSError as e:
        _check(r, "FAIL", "workspaces writable", str(e))
    probe = ("import socket\ntry:\n    socket.getaddrinfo('example.com', 443)\n    print('open')\n"
             "except PermissionError:\n    print('blocked')")
    with tempfile.TemporaryDirectory() as tmp:
        out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=60,
                             env=safe_env(Path(tmp)), cwd=tmp).stdout.strip()
    allowed = config.get_bool("SDLC_ALLOW_NETWORK")
    _check(r, "OK" if out == ("open" if allowed else "blocked") else "FAIL", "sandbox network guard",
           f"generated code network: {out or 'probe failed'}" + (" (SDLC_ALLOW_NETWORK=1)" if allowed else ""))
    webhook = config.raw("SDLC_ALERT_WEBHOOK")
    _check(r, "OK" if webhook else "INFO", "alerts", "webhook configured (`sdlc alerts --test` to try)" if webhook
           else "file only; set SDLC_ALERT_WEBHOOK for Slack/Teams/Mattermost")
    gh = bool(config.raw("GITHUB_TOKEN") and config.raw("SDLC_GITHUB_REPO"))
    _check(r, "OK" if gh else "INFO", "github",
           "real PRs enabled" if gh else "local PR packages (set GITHUB_TOKEN + SDLC_GITHUB_REPO)")
    for status, name, detail in r:
        console(f"[{status:<4}] {name:<26} {detail}")
    failed = [x for x in r if x[0] == "FAIL"]
    console("\nready" if not failed else f"\nNOT ready: {len(failed)} problem(s) above")
    return 1 if failed else 0


# ====================================================================== demo

SCENARIOS = [
    # name, requirement, answers file, expected final phase
    ("greenfield-url-shortener", "url-shortener.md", None, "reviewed"),
    ("brownfield-bookmarks", "brownfield-bookmarks.md", None, "reviewed"),
    ("ambiguous-notifications", "ambiguous-notifications.md", "ambiguous-notifications.answers.yaml", "reviewed"),
    ("failure-recovery-exhausted", "failing-calculator.md", None, "failed"),
]


def _rmtree(path: Path) -> None:
    def onerror(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    if path.exists():
        shutil.rmtree(path, onerror=onerror)


def _export(ws: Path, run_id: str, out: Path) -> None:
    _rmtree(out)
    out.mkdir(parents=True)
    run_dir = ws / ".sdlc" / "runs" / run_id
    write(run_dir / "reports" / "debug.md", debug_report(run_dir, ws))
    for f in (run_dir / "reports").glob("*.md"):
        shutil.copy2(f, out / f.name)
    # Reviewer-facing deliverables only; state.json and debug.log stay in the workspace (regenerable).
    for name in ("events.jsonl", "alerts.jsonl"):
        if (run_dir / name).exists():
            shutil.copy2(run_dir / name, out / name)
    for f in (ws / ".sdlc" / "releases").glob("*.md") if (ws / ".sdlc" / "releases").exists() else []:
        shutil.copy2(f, out / f"release-notes-{f.stem}.md")
    code = out / "workspace"
    # Only what git tracks: ignored build/test artifacts (databases, caches) never reach the sample outputs.
    for rel in Git(ws).run("ls-files").splitlines():
        (code / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ws / rel, code / rel)
    _scrub_paths(out, ws)


def _scrub_paths(out: Path, ws: Path) -> None:
    """Committed sample outputs must not contain local absolute paths (user names, home folders)."""
    replacements = []
    for path, label in ((ws.resolve(), "<workspace>"), (PROJECT_ROOT.resolve(), "<repo>"),
                        (Path(tempfile.gettempdir()).resolve(), "<tmp>"), (Path.home().resolve(), "<home>")):
        raw = str(path)
        replacements += [(raw.replace("\\", "\\\\"), label), (raw, label), (raw.replace("\\", "/"), label)]
    for f in out.rglob("*"):
        if (f.is_file() and f.suffix in {".md", ".json", ".jsonl", ".log", ".txt"}
                and "workspace" not in f.relative_to(out).parts):
            text = f.read_text(encoding="utf-8")
            for old, new in replacements:
                text = text.replace(old, new)
            f.write_text(text, encoding="utf-8")


def demo(out: Path, workspaces: Path, quiet: bool = False) -> int:
    req_dir = PROJECT_ROOT / "examples" / "requirements"
    policy = default_policy()
    results = []
    for name, req_file, answers, expected in SCENARIOS:
        console(f"\n{'#' * 78}\n# scenario: {name}\n{'#' * 78}")
        ws = workspaces / name
        _rmtree(ws)
        settings = Settings(provider="mock", quiet=quiet, debug=True)

        if answers:  # first show the run stopping on blocking ambiguities, then resume with the answers
            state = Run.new(req_dir / req_file, ws, PolicyApprover.from_files(policy, None), settings).implement()
            _export(ws, state.run_id, out / name / "1-stopped-for-clarification")
            results.append((f"{name} (no answers)", state.phase.value, "needs_clarification"))
            approver = PolicyApprover.from_files(policy, req_dir / answers)
            state = Run.load(ws, state.run_id, approver, settings).implement()
        else:
            approver = PolicyApprover.from_files(policy, None)
            state = Run.new(req_dir / req_file, ws, approver, settings).implement()

        if state.phase == Phase.PR_READY:
            Run.load(ws, state.run_id, approver, settings).review()
            change_request(ws, approver, settings, state.run_id)
            release(ws, approver, settings)
            state = Run.load(ws, state.run_id, approver, settings).state
        _export(ws, state.run_id, out / name / ("2-completed" if answers else ""))
        results.append((name, state.phase.value, expected))

    console("\n" + "=" * 78)
    for name, phase, expected in results:
        verdict = "as expected" if phase == expected else f"UNEXPECTED (wanted {expected})"
        console(f"  {name:45s} {phase:<20} {verdict}")
    console(f"\noutputs: {out}")
    return 0 if all(p == e for _, p, e in results) else 1


if __name__ == "__main__":
    sys.exit(main())
