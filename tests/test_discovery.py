"""Tests for the network discovery helper utilities."""

from __future__ import annotations

import http.server
import socket
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


def test_create_udp_socket_delegates_to_socket_module(monkeypatch) -> None:
    """The helper should forward parameters to :func:`socket.socket`."""

    captured_args: tuple[int, int] | None = None

    class DummySocket:
        pass

    def fake_socket(family: int, type_: int) -> DummySocket:
        nonlocal captured_args
        captured_args = (family, type_)
        return DummySocket()

    monkeypatch.setattr(discovery.socket, "socket", fake_socket)

    result = discovery._create_udp_socket(1, 2)

    assert isinstance(result, DummySocket)
    assert captured_args == (1, 2)


def test_iter_getaddrinfo_addresses_handles_hostname_errors() -> None:
    """Hostname resolution errors should terminate the iterator silently."""

    def failing_resolver() -> str:
        raise OSError("hostname unavailable")

    addresses = list(
        discovery._iter_getaddrinfo_addresses(hostname_resolver=failing_resolver)
    )

    assert addresses == []


def test_iter_getaddrinfo_addresses_filters_invalid_entries() -> None:
    """The iterator should ignore malformed or empty address tuples."""

    def fake_resolver() -> str:
        return "example-host"

    def fake_getaddrinfo(hostname: str, *_args, **_kwargs):
        return [
            tuple(),
            (None, None, None, None, ("192.0.2.50", 0)),
            (None, None, None, None, ("", 0)),
        ]

    addresses = list(
        discovery._iter_getaddrinfo_addresses(
            hostname_resolver=fake_resolver, getaddrinfo=fake_getaddrinfo
        )
    )

    assert addresses == ["192.0.2.50"]


def test_iter_getaddrinfo_addresses_handles_socket_errors() -> None:
    """Socket-level errors while querying should result in no addresses."""

    def fake_getaddrinfo(hostname: str, *_args, **_kwargs):
        raise socket.gaierror("lookup failed")

    addresses = list(
        discovery._iter_getaddrinfo_addresses(
            hostname_resolver=lambda: "example", getaddrinfo=fake_getaddrinfo
        )
    )

    assert addresses == []


def test_iter_probe_addresses_recovers_from_socket_errors() -> None:
    """Probe failures should not interrupt iteration over remaining hosts."""

    behaviours = iter(
        [
            ("error", ""),
            ("ok", ""),
            ("ok", "192.0.2.77"),
        ]
    )

    class DummySocket:
        def __init__(self, mode: str, address: str):
            self.mode = mode
            self.address = address

        def connect(self, _target):
            if self.mode == "error":
                raise OSError("network unreachable")

        def getsockname(self):
            return (self.address, 1234)

        def close(self):
            return None

    def fake_socket_factory(_family: int, _type: int) -> DummySocket:
        mode, address = next(behaviours)
        return DummySocket(mode, address)

    addresses = list(
        discovery._iter_probe_addresses(
            probes=("first", "second", "third"), socket_factory=fake_socket_factory
        )
    )

    assert addresses == ["192.0.2.77"]


def test_should_include_host_handles_empty_values() -> None:
    """Hosts without a value or in the exclusion set should be ignored."""

    assert discovery._should_include_host("") is False
    assert discovery._should_include_host(None) is False
    assert discovery._should_include_host("localhost") is False
    assert discovery._should_include_host("192.0.2.55") is True


def test_iter_local_ipv4_addresses_uses_default_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default address sources should be consulted when none are provided."""

    monkeypatch.setattr(
        discovery,
        "_iter_getaddrinfo_addresses",
        lambda: iter(["", "192.0.2.15"]),
    )
    monkeypatch.setattr(
        discovery,
        "_iter_probe_addresses",
        lambda: iter(["192.0.2.15", "198.51.100.7"]),
    )

    addresses = list(discovery._iter_local_ipv4_addresses())

    assert addresses == ["192.0.2.15", "198.51.100.7"]


def test_probe_host_handles_close_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Errors raised while closing the connection should be suppressed."""

    events: dict[str, bool] = {"closed": False, "read": False}

    class DummyResponse:
        status = 503

        def read(self) -> None:
            events["read"] = True

    class DummyConnection:
        def __init__(self, host: str, port: int, timeout: float) -> None:
            self.host = host
            self.port = port
            self.timeout = timeout

        def request(self, method: str, path: str, headers: dict[str, str]) -> None:
            assert method == "GET"
            assert path == "/"
            assert "User-Agent" in headers

        def getresponse(self) -> DummyResponse:
            return DummyResponse()

        def close(self) -> None:
            events["closed"] = True
            raise RuntimeError("close failed")

    monkeypatch.setattr(discovery, "HTTPConnection", DummyConnection)

    result = discovery._probe_host("example.com", 8080, timeout=0.1)

    assert result is None
    assert events == {"closed": True, "read": True}
