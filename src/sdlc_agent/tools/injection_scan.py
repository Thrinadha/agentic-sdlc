"""Prompt-injection screening for repository content that will be shown to agents.

Brownfield code, docs and comments go into agent prompts. Text that tries to instruct the model
("ignore previous instructions", "you are now ...") is flagged so a human sees it at the plan gate.
Screening is a tripwire, not a guarantee: the main defenses are that repository content is fenced as
untrusted data in every prompt, agents cannot run commands, and every write passes the sandbox and gates.
"""

from __future__ import annotations

import re

PATTERNS: list[tuple[str, re.Pattern]] = [
    ("override instructions", re.compile(
        r"(?i)\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|earlier|all|system)\b"
        r".{0,20}\b(instructions?|prompts?|rules?|messages?)")),
    ("role reassignment", re.compile(r"(?i)\byou are (now|no longer)\b|\bact as (an?|the) (ai|assistant|system)\b")),
    ("fake conversation turn", re.compile(r"(?im)^\s*(system|assistant)\s*:\s|</?(system|assistant)>")),
    ("exfiltration request", re.compile(
        r"(?i)\b(print|reveal|send|post|upload|exfiltrate|output)\b.{0,40}"
        r"\b(api[_ -]?keys?|tokens?|secrets?|credentials?|environment variables?|env vars?|system prompt)\b")),
    ("tool or gate tampering", re.compile(
        r"(?i)\b(skip|disable|bypass|turn off)\b.{0,30}\b(tests?|validation|review|approval|gates?|secret scan)\b")),
]


def scan(files: dict[str, str]) -> list[str]:
    """``path:line [rule]`` for each suspicious line (at most one finding per line)."""
    hits = []
    for path, text in sorted(files.items()):
        for i, line in enumerate(text.splitlines(), start=1):
            for rule, rx in PATTERNS:
                if rx.search(line):
                    hits.append(f"{path}:{i} [{rule}]")
                    break
    return hits
