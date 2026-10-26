"""Loaded automatically by Python in sandboxed subprocesses (it is first on PYTHONPATH).

Blocks DNS resolution and socket connections to non-loopback addresses, so generated code and its
tests cannot reach the network. In-process test clients (FastAPI/Starlette TestClient) are unaffected.
"""

import ipaddress
import os
import socket

if os.environ.get("SDLC_ALLOW_NETWORK") != "1":
    _LOCAL_NAMES = {"localhost", "localhost.localdomain", "", None}

    def _is_local(host):
        if isinstance(host, bytes):
            host = host.decode(errors="ignore")
        if host in _LOCAL_NAMES:
            return True
        try:
            return ipaddress.ip_address(str(host).split("%")[0]).is_loopback
        except ValueError:
            return False

    def _refuse(target):
        raise PermissionError(f"network access blocked by the sdlc sandbox: {target!r} "
                              "(set SDLC_ALLOW_NETWORK=1 to allow)")

    _getaddrinfo = socket.getaddrinfo
    _connect = socket.socket.connect
    _connect_ex = socket.socket.connect_ex

    def getaddrinfo(host, *args, **kwargs):
        if not _is_local(host):
            _refuse(host)
        return _getaddrinfo(host, *args, **kwargs)

    def _check(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6) and not _is_local(address[0]):
            _refuse(address)

    def connect(self, address):
        _check(self, address)
        return _connect(self, address)

    def connect_ex(self, address):
        _check(self, address)
        return _connect_ex(self, address)

    socket.getaddrinfo = getaddrinfo
    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
