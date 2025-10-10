"""Utilities for interacting with Talks Reducer remote servers."""

from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional


def normalize_server_url(server_url: str) -> str:
    """Return *server_url* with a scheme and default path when missing."""

    parsed = urllib.parse.urlsplit(server_url)
    if not parsed.scheme:
        parsed = urllib.parse.urlsplit(f"http://{server_url}")

    netloc = parsed.netloc or parsed.path
    if not netloc:
        return server_url

    path = parsed.path if parsed.netloc else ""
    normalized_path = path or "/"
    return urllib.parse.urlunsplit((parsed.scheme, netloc, normalized_path, "", ""))


def format_server_host(server_url: str) -> str:
    """Return the host label for *server_url* suitable for log messages."""

    parsed = urllib.parse.urlsplit(server_url)
    if not parsed.scheme:
        parsed = urllib.parse.urlsplit(f"http://{server_url}")

    host = parsed.netloc or parsed.path or server_url
    if parsed.netloc and parsed.path and parsed.path not in {"", "/"}:
        host = f"{parsed.netloc}{parsed.path}"

    host = host.rstrip("/").split(":")[0]
    return host or server_url


def ping_server(server_url: str, *, timeout: float = 5.0) -> bool:
    """Return ``True`` if *server_url* responds with an HTTP status."""

    normalized = normalize_server_url(server_url)
    request = urllib.request.Request(
        normalized,
        headers={"User-Agent": "talks-reducer-gui"},
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # type: ignore[arg-type]
            status = getattr(response, "status", None)
            if status is None:
                status = response.getcode()
            if status is None:
                return False
            return 200 <= int(status) < 500
    except (urllib.error.URLError, ValueError):
        return False


def check_remote_server(
    server_url: str,
    *,
    success_status: str,
    waiting_status: str,
    failure_status: str,
    on_log: Callable[[str], None],
    on_status: Callable[[str, str], None],
    success_message: Optional[str] = None,
    waiting_message_template: str = "Waiting server {host} (attempt {attempt}/{max_attempts})",
    failure_message: Optional[str] = None,
    stop_check: Optional[Callable[[], bool]] = None,
    on_stop: Optional[Callable[[], None]] = None,
    switch_to_local_on_failure: bool = False,
    alert_on_failure: bool = False,
    warning_title: str = "Server unavailable",
    warning_message: Optional[str] = None,
    max_attempts: int = 5,
    delay: float = 1.0,
    on_switch_to_local: Optional[Callable[[], None]] = None,
    on_alert: Optional[Callable[[str, str], None]] = None,
    ping: Callable[[str], bool] = ping_server,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Ping *server_url* until it responds or attempts are exhausted."""

    host_label = format_server_host(server_url)
    format_kwargs = {"host": host_label, "max_attempts": max_attempts}

    success_text = (
        success_message.format(**format_kwargs)
        if success_message
        else f"Server {host_label} is ready"
    )
    failure_text = (
        failure_message.format(**format_kwargs)
        if failure_message
        else f"Server {host_label} is unreachable"
    )

    for attempt in range(1, max_attempts + 1):
        if stop_check and stop_check():
            if on_stop:
                on_stop()
            return False

        if ping(server_url):
            on_log(success_text)
            on_status(success_status, success_text)
            return True

        if attempt < max_attempts:
            wait_text = waiting_message_template.format(
                attempt=attempt, max_attempts=max_attempts, host=host_label
            )
            on_log(wait_text)
            on_status(waiting_status, wait_text)
            if stop_check and stop_check():
                if on_stop:
                    on_stop()
                return False
            if delay:
                sleep(delay)

    on_log(failure_text)
    on_status(failure_status, failure_text)

    if switch_to_local_on_failure and on_switch_to_local:
        on_switch_to_local()

    if alert_on_failure and on_alert:
        message = (
            warning_message.format(**format_kwargs) if warning_message else failure_text
        )
        on_alert(warning_title, message)

    return False
