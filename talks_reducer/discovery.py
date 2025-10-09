"""Utilities for discovering Talks Reducer servers on the local network."""

from __future__ import annotations

import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from http.client import HTTPConnection
from typing import Callable, Iterable, Iterator, List, Optional, Set

DEFAULT_PORT = 9005
DEFAULT_TIMEOUT = 0.4

_EXCLUDED_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0"}


def _should_include_host(host: Optional[str]) -> bool:
    """Return ``True`` when *host* should be scanned for discovery."""

    if not host:
        return False
    return host not in _EXCLUDED_HOSTS


def _iter_local_ipv4_addresses() -> Iterator[str]:
    """Yield IPv4 addresses that belong to the local machine."""

    seen: Set[str] = set()

    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, family=socket.AF_INET):
            address = info[4][0]
            if address and address not in seen:
                seen.add(address)
                yield address
    except socket.gaierror:
        pass

    for probe in ("8.8.8.8", "1.1.1.1"):
        try:
            with closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM)) as sock:
                sock.connect((probe, 80))
                address = sock.getsockname()[0]
                if address and address not in seen:
                    seen.add(address)
                    yield address
        except OSError:
            continue


def _build_default_host_candidates(prefix_length: int = 24) -> List[str]:
    """Return a list of host candidates based on detected local networks."""

    hosts: Set[str] = set()

    for address in _iter_local_ipv4_addresses():
        if _should_include_host(address):
            hosts.add(address)
        try:
            network = ipaddress.ip_network(f"{address}/{prefix_length}", strict=False)
        except ValueError:
            continue
        for host in network.hosts():
            host_str = str(host)
            if _should_include_host(host_str):
                hosts.add(host_str)

    return sorted(hosts)


def _probe_host(host: str, port: int, timeout: float) -> Optional[str]:
    """Return the URL if *host* responds on *port* within *timeout* seconds."""

    connection: Optional[HTTPConnection] = None
    try:
        connection = HTTPConnection(host, port, timeout=timeout)
        connection.request(
            "GET", "/", headers={"User-Agent": "talks-reducer-discovery"}
        )
        response = connection.getresponse()
        # Drain the response to avoid ResourceWarning in some Python versions.
        response.read()
        if 200 <= response.status < 500:
            return f"http://{host}:{port}/"
    except OSError:
        return None
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
    return None


ProgressCallback = Callable[[int, int], None]


def discover_servers(
    *,
    port: int = DEFAULT_PORT,
    timeout: float = DEFAULT_TIMEOUT,
    hosts: Optional[Iterable[str]] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> List[str]:
    """Scan *hosts* for running Talks Reducer servers on *port*.

    When *hosts* is omitted, the local /24 networks derived from available IPv4
    addresses are scanned. ``127.0.0.1``, ``localhost``, and ``0.0.0.0`` are
    excluded to avoid duplicating local endpoints. The optional
    *progress_callback* receives the number of scanned hosts and the total
    candidate count whenever discovery advances. The function returns a sorted
    list of unique base URLs.
    """

    if hosts is None:
        candidates = sorted(
            {
                host
                for host in _build_default_host_candidates()
                if _should_include_host(host)
            }
        )
    else:
        candidates = sorted({host for host in hosts if _should_include_host(host)})

    results: List[str] = []
    total = len(candidates)

    if progress_callback is not None:
        progress_callback(0, total)

    with ThreadPoolExecutor(max_workers=32) as executor:
        scanned = 0
        for url in executor.map(
            lambda host: _probe_host(host, port, timeout), candidates
        ):
            if url and url not in results:
                results.append(url)
            scanned += 1
            if progress_callback is not None:
                progress_callback(scanned, total)

    return results


__all__ = ["discover_servers"]
