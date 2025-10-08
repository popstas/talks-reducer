"""Tests for the network discovery helper utilities."""

from __future__ import annotations

import http.server
import threading
from contextlib import contextmanager

from talks_reducer import discovery


@contextmanager
def _http_server() -> tuple[str, int]:
    """Start a lightweight HTTP server for discovery tests."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # pragma: no cover - exercised via discovery
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")

        def log_message(self, *args, **kwargs):  # type: ignore[override]
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    host, port = server.server_address

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        yield host, port
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_discover_servers_detects_running_instance() -> None:
    """The discovery helper should report a reachable local server."""

    with _http_server() as (host, port):
        results = discovery.discover_servers(port=port, hosts=[host])

    expected_url = f"http://{host}:{port}/"
    assert expected_url in results


def test_discover_servers_handles_missing_hosts() -> None:
    """Scanning an unreachable host should return an empty result list."""

    results = discovery.discover_servers(port=65500, hosts=["192.0.2.123"])
    assert results == []
