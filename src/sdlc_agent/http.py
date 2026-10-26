"""Outbound HTTP for the orchestrator (LLM endpoints, GitHub, alert webhooks).

The opener only has HTTP(S) handlers, so ``file://``, ``ftp://`` or custom schemes cannot be opened even
if a URL comes from misconfigured environment variables. Proxy settings from the environment are honoured.
"""

from __future__ import annotations

import urllib.request
from urllib.parse import urlsplit

ALLOWED_SCHEMES = ("http", "https")


def check_url(url: str) -> str:
    if urlsplit(url).scheme.lower() not in ALLOWED_SCHEMES or not urlsplit(url).netloc:
        raise ValueError(f"only http(s) URLs are allowed, got scheme {urlsplit(url).scheme!r}")
    return url


def _opener() -> urllib.request.OpenerDirector:
    opener = urllib.request.OpenerDirector()
    for handler in (urllib.request.ProxyHandler(), urllib.request.HTTPHandler(), urllib.request.HTTPSHandler(),
                    urllib.request.HTTPDefaultErrorHandler(), urllib.request.HTTPRedirectHandler(),
                    urllib.request.HTTPErrorProcessor()):
        opener.add_handler(handler)
    return opener


def http_open(req: urllib.request.Request, timeout: float):
    check_url(req.full_url)
    return _opener().open(req, timeout=timeout)
