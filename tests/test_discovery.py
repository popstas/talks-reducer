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


def test_probe_host_detects_running_instance() -> None:
    """The host probe should report a reachable local server."""

    with _http_server() as (host, port):
        result = discovery._probe_host(host, port, timeout=0.5)

    assert result == f"http://{host}:{port}/"


def test_discover_servers_handles_missing_hosts() -> None:
    """Scanning an unreachable host should return an empty result list."""

    results = discovery.discover_servers(port=65500, hosts=["192.0.2.123"])
    assert results == []


def test_discover_servers_skips_local_endpoints() -> None:
    """Local-only hosts should be filtered from the scan list."""

    observed_hosts: list[str] = []

    def fake_probe(host: str, port: int, timeout: float) -> str:
        observed_hosts.append(host)
        return f"http://{host}:{port}/"

    results = discovery.discover_servers(
        port=9005,
        hosts=["localhost", "127.0.0.1", "0.0.0.0", "192.0.2.42"],
        probe_host=fake_probe,
    )

    assert observed_hosts == ["192.0.2.42"]
    assert results == ["http://192.0.2.42:9005/"]


def test_discover_servers_filters_default_candidates() -> None:
    """Automatically detected hosts should also respect the exclusion list."""

    address_sources = (lambda: ["localhost", "127.0.0.1", "192.0.2.99"],)

    observed_hosts: list[str] = []

    def fake_probe(host: str, port: int, timeout: float) -> str | None:
        observed_hosts.append(host)
        if host == "192.0.2.99":
            return f"http://{host}:{port}/"
        return None

    results = discovery.discover_servers(
        port=8080,
        address_sources=address_sources,
        probe_host=fake_probe,
    )

    assert "localhost" not in observed_hosts
    assert "127.0.0.1" not in observed_hosts
    assert results == ["http://192.0.2.99:8080/"]


def test_discover_servers_reports_progress() -> None:
    """Discovery should surface progress updates as hosts are scanned."""

    progress_updates: list[tuple[int, int]] = []

    discovery.discover_servers(
        port=9005,
        hosts=["192.0.2.10", "192.0.2.11"],
        progress_callback=lambda current, total: progress_updates.append(
            (current, total)
        ),
        probe_host=lambda host, port, timeout: None,
    )

    assert progress_updates == [(0, 2), (1, 2), (2, 2)]


def test_iter_local_ipv4_addresses_uses_custom_sources() -> None:
    """Custom address sources should feed the local address iterator."""

    address_sources = (
        lambda: ["192.0.2.1", "192.0.2.2", ""],
        lambda: ["192.0.2.2", "198.51.100.1"],
    )

    addresses = list(
        discovery._iter_local_ipv4_addresses(address_sources=address_sources)
    )

    assert addresses == ["192.0.2.1", "192.0.2.2", "198.51.100.1"]


def test_build_default_host_candidates_filters_excluded_hosts() -> None:
    """Hosts excluded by `_should_include_host` should be omitted from defaults."""

    address_sources = (lambda: ["127.0.0.1", "192.0.2.1"],)

    candidates = discovery._build_default_host_candidates(
        prefix_length=32, address_sources=address_sources
    )

    assert candidates == ["192.0.2.1"]
