"""Secret scanner: blocks commits that contain credentials.

Findings report file, line and rule. They never include the matched value.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

RULES: list[tuple[str, re.Pattern]] = [
    ("aws-access-key-id", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("private-key", re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("github-token", re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}\b")),
    ("slack-token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}\b")),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("openai-key", re.compile(r"\bsk-(proj-)?[A-Za-z0-9]{32,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("connection-string-password", re.compile(r"\b[a-z+]+://[^/\s:@]+:([^@\s/]{6,})@", re.I)),
    (
        "hardcoded-credential",
        re.compile(
            r"""(?ix)\b(password|passwd|secret|api[_-]?key|token|access[_-]?key)\b\s*[:=]\s*["']([^"'\s]{8,})["']"""
        ),
    ),
]

# Values that are obviously placeholders, not secrets.
PLACEHOLDER = re.compile(r"(?i)^(x+|\*+|changeme|example|placeholder|dummy|test|<.*>|\$\{.*\}|your[-_].*)$")
ALLOW_MARKER = "secret-scan: allow"


@dataclass(frozen=True)
class SecretFinding:
    file: str
    line: int
    rule: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line} [{self.rule}]"


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    freq = {c: s.count(c) / len(s) for c in set(s)}
    return -sum(p * math.log2(p) for p in freq.values())


def scan_text(path: str, text: str) -> list[SecretFinding]:
    findings = []
    for i, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARKER in line:
            continue
        for rule, rx in RULES:
            m = rx.search(line)
            if not m:
                continue
            if rule in ("hardcoded-credential", "connection-string-password"):
                value = m.group(m.lastindex or 0)
                if PLACEHOLDER.match(value) or _entropy(value) < 3.0:
                    continue
            findings.append(SecretFinding(path, i, rule))
            break
    return findings


_SENSITIVE_ENV = re.compile(r"(?i)(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|WEBHOOK|AUTH)")


def redact(text: str) -> str:
    """Remove secrets from text before it is written to a log, transcript or alert.

    Two layers: the scan rules above, and the literal values of any credential-like environment variable
    (``*_KEY``, ``*_TOKEN``, ``*_SECRET``, ``*WEBHOOK*`` ...) of this process.
    """
    import os

    for name, value in os.environ.items():
        if _SENSITIVE_ENV.search(name) and len(value) >= 8:
            text = text.replace(value, f"[REDACTED:{name}]")
    for rule, rx in RULES:
        if rule in ("hardcoded-credential", "connection-string-password"):
            def _value_only(m: re.Match, rule: str = rule) -> str:
                g = m.lastindex or 0
                value = m.group(g)
                if PLACEHOLDER.match(value) or _entropy(value) < 3.0:
                    return m.group(0)
                s, e = m.start(g) - m.start(0), m.end(g) - m.start(0)
                return m.group(0)[:s] + f"[REDACTED:{rule}]" + m.group(0)[e:]
            text = rx.sub(_value_only, text)
        else:
            text = rx.sub(f"[REDACTED:{rule}]", text)
    return text


def scan_files(files: dict[str, str]) -> list[SecretFinding]:
    out: list[SecretFinding] = []
    for path, text in sorted(files.items()):
        out.extend(scan_text(path, text))
    return out
