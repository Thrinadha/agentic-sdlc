"""Shared fixtures: a local webhook receiver, and isolation from the developer's own SDLC_* settings."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from sdlc_agent import config


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch):
    """Tests must not depend on (or leak into) the machine's process or user-scope settings."""
    for name in config.VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "_user_scope", lambda name: None)


class Receiver:
    def __init__(self):
        self.posts: list[dict] = []
        self.fail = False
        received = self.posts
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - http.server API
                body = self.rfile.read(int(self.headers["Content-Length"]))
                if owner.fail:
                    self.send_response(500)
                else:
                    received.append(json.loads(body))
                    self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/hooks/abc123secretpath"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


@pytest.fixture
def webhook():
    r = Receiver()
    yield r
    r.close()
