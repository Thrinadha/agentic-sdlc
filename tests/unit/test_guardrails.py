"""Sandbox, secret scan and unsafe-code guardrails."""

import pytest

from sdlc_agent.tools.secret_scan import scan_text
from sdlc_agent.tools.static_checks import unsafe_code_check
from sdlc_agent.tools.workspace import MAX_FILE_BYTES, GuardrailError, Workspace


@pytest.fixture
def ws(tmp_path):
    return Workspace(tmp_path / "ws")


@pytest.mark.parametrize("bad", ["../escape.py", "a/../../escape.py", "/etc/passwd", "C:/Windows/x.py",
                                 ".git/config", ".sdlc/runs/x/state.json", ".github/workflows/ci.yml", ""])
def test_writes_outside_or_into_protected_paths_are_refused(ws, bad):
    with pytest.raises(GuardrailError):
        ws.write(bad, "x")


def test_normal_write_read_and_listing(ws):
    ws.write("app/main.py", "print('hi')\n")
    assert ws.read("app/main.py") == "print('hi')\n"
    assert ws.files() == ["app/main.py"]


def test_oversized_file_is_refused(ws):
    with pytest.raises(GuardrailError, match="exceeds"):
        ws.write("big.txt", "x" * (MAX_FILE_BYTES + 1))


# Fake values, assembled at runtime so this file never contains a secret-looking string itself
# (otherwise this repo's own secret scan and GitHub secret scanning would flag it).
AWS = "AKIA" + "ABCDEFGHIJKLMNOP"
GH = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
PW_LINE = "pass" + 'word = "' + "Zq8!kP2#vR9x" + '"'
DSN_LINE = "db = 'postgresql://app" + ":" + "S3cr3tPassw0rd" + "@db.internal/app'"
KEY_LINE = "-----BEGIN RSA " + "PRIVATE KEY-----"


@pytest.mark.parametrize("line,rule", [
    (f'key = "{AWS}"', "aws-access-key-id"),
    (f"token: {GH}", "github-token"),
    (PW_LINE, "hardcoded-credential"),
    (DSN_LINE, "connection-string-password"),
    (KEY_LINE, "private-key"),
])
def test_secrets_are_detected(line, rule):
    findings = scan_text("cfg.py", line)
    assert [f.rule for f in findings] == [rule]
    assert line.split()[-1].strip("'\"") not in str(findings[0])  # value is never echoed


@pytest.mark.parametrize("line", [
    'password = os.getenv("DB_PASSWORD")',
    'password = "changeme"',
    'api_key = "${API_KEY}"',
    "DATABASE_URL=sqlite:///./app.db",
    'token = "xxxxxxxxxxxx"',
])
def test_placeholders_and_env_lookups_are_not_flagged(line):
    assert scan_text("cfg.py", line) == []


def test_allow_marker_suppresses_a_reviewed_false_positive():
    assert scan_text("t.py", f'k = "{AWS}"  # secret-scan: allow') == []


def test_unsafe_patterns_are_reported(ws):
    ws.write("app/bad.py", "import os\nos.system('rm -rf /')\nresult = eval(user_input)\n")
    ws.write("app/ok.py", "# eval( in a comment is fine\nvalue = evaluate(x)\n")
    check = unsafe_code_check(ws)
    assert check.status == "failed"
    assert "app/bad.py:2 os.system" in check.details and "app/bad.py:3 eval/exec" in check.details
    assert "ok.py" not in check.details
