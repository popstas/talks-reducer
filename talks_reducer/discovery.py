"""Utilities for discovering Talks Reducer servers on the local network."""

from __future__ import annotations

import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from http.client import HTTPConnection
from typing import Callable, Iterable, Iterator, List, Optional, Sequence, Set

DEFAULT_PORT = 9005
DEFAULT_TIMEOUT = 0.4

_EXCLUDED_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0"}


AddressSource = Callable[[], Iterable[str]]
ProbeHost = Callable[[str, int, float], Optional[str]]


def _should_include_host(host: Optional[str]) -> bool:
    """Return ``True`` when *host* should be scanned for discovery."""

    if not host:
        return False
    return host not in _EXCLUDED_HOSTS


def _create_udp_socket(family: int, type_: int) -> socket.socket:
    """Return a UDP socket created with :func:`socket.socket`."""

    return socket.socket(family, type_)


def _iter_getaddrinfo_addresses(
    *,
    hostname_resolver: Callable[[], str] = socket.gethostname,
    getaddrinfo: Callable[..., Sequence[Sequence[object]]] = socket.getaddrinfo,
) -> Iterator[str]:
    """Yield IPv4 addresses discovered via ``getaddrinfo``."""

    try:
        hostname = hostname_resolver()
    except OSError:
        return

    try:
        for info in getaddrinfo(hostname, None, family=socket.AF_INET):
            try:
                address = info[4][0]  # type: ignore[index]
            except (IndexError, TypeError):
                continue
            if address:
                yield str(address)
    except socket.gaierror:
        return


def _iter_probe_addresses(
    probes: Iterable[str] = ("8.8.8.8", "1.1.1.1"),
    *,
    socket_factory: Callable[[int, int], socket.socket] = _create_udp_socket,
) -> Iterator[str]:
    """Yield IPv4 addresses by opening UDP sockets to well-known hosts."""

    for probe in probes:
        try:
            with closing(socket_factory(socket.AF_INET, socket.SOCK_DGRAM)) as sock:
                sock.connect((probe, 80))
                address = sock.getsockname()[0]
                if address:
                    yield address
        except OSError:
            continue


def _iter_local_ipv4_addresses(
    *, address_sources: Optional[Iterable[AddressSource]] = None
) -> Iterator[str]:
    """Yield IPv4 addresses that belong to the local machine."""

    seen: Set[str] = set()
    sources: Iterable[AddressSource]
    if address_sources is None:
        sources = (_iter_getaddrinfo_addresses, _iter_probe_addresses)
    else:
        sources = address_sources

    for source in sources:
        for address in source():
            if not address:
                continue
            if address not in seen:
                seen.add(address)
                yield address


def _build_default_host_candidates(
    prefix_length: int = 24,
    *,
    address_sources: Optional[Iterable[AddressSource]] = None,
) -> List[str]:
    """Return a list of host candidates based on detected local networks."""

    hosts: Set[str] = set()

    for address in _iter_local_ipv4_addresses(address_sources=address_sources):
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
    address_sources: Optional[Iterable[AddressSource]] = None,
    probe_host: Optional[ProbeHost] = None,
) -> List[str]:
    """Scan *hosts* for running Talks Reducer servers on *port*.

    When *hosts* is omitted, the local /24 networks derived from available IPv4
    addresses are scanned. ``127.0.0.1``, ``localhost``, and ``0.0.0.0`` are
    excluded to avoid duplicating local endpoints. The optional
    *progress_callback* receives the number of scanned hosts and the total
    candidate count whenever discovery advances. Supply *address_sources* to
    override the IPv4 detection logic with custom iterables, and *probe_host*
    to replace the HTTP-based reachability probe. The function returns a sorted
    list of unique base URLs.
    """

    if hosts is None:
        candidates = sorted(
            {
                host
                for host in _build_default_host_candidates(
                    address_sources=address_sources
                )
                if _should_include_host(host)
            }
        )
    else:
        candidates = sorted({host for host in hosts if _should_include_host(host)})

    results: List[str] = []
    total = len(candidates)

    if progress_callback is not None:
        progress_callback(0, total)

    probe_fn: ProbeHost = _probe_host if probe_host is None else probe_host

    with ThreadPoolExecutor(max_workers=32) as executor:
        scanned = 0
        for url in executor.map(lambda host: probe_fn(host, port, timeout), candidates):
            if url and url not in results:
                results.append(url)
            scanned += 1
            if progress_callback is not None:
                progress_callback(scanned, total)

    return results


__all__ = ["discover_servers"]
