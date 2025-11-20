"""Remote processing helpers for Talks Reducer GUI workflows."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, List, Optional

from .remote import (
    check_remote_server_for_gui,
    format_server_host,
    normalize_server_url,
    ping_server,
    process_files_via_server,
)

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from .app import TalksReducerGUI


class RemoteController:
    """Coordinate discovery, connectivity checks, and remote job submission."""

    def __init__(self, gui: "TalksReducerGUI") -> None:
        self.gui = gui

    def normalize_server_url(self, server_url: str) -> str:
        return normalize_server_url(server_url)

    def format_server_host(self, server_url: str) -> str:
        return format_server_host(server_url)

    def check_remote_server(
        self,
        server_url: str,
        *,
        success_status: str,
        waiting_status: str,
        failure_status: str,
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
    ) -> bool:
        return check_remote_server_for_gui(
            self.gui,
            server_url,
            success_status=success_status,
            waiting_status=waiting_status,
            failure_status=failure_status,
            success_message=success_message,
            waiting_message_template=waiting_message_template,
            failure_message=failure_message,
            stop_check=stop_check,
            on_stop=on_stop,
            switch_to_local_on_failure=switch_to_local_on_failure,
            alert_on_failure=alert_on_failure,
            warning_title=warning_title,
            warning_message=warning_message,
            max_attempts=max_attempts,
            delay=delay,
        )

    def ping_server(self, server_url: str, *, timeout: float = 5.0) -> bool:
        return ping_server(server_url, timeout=timeout)

    def process_files_via_server(
        self,
        files: List[str],
        args: dict[str, object],
        server_url: str,
        *,
        open_after_convert: bool,
        default_remote_destination,
        parse_summary,
    ) -> bool:
        return process_files_via_server(
            self.gui,
            files,
            args,
            server_url,
            open_after_convert=open_after_convert,
            default_remote_destination=default_remote_destination,
            parse_summary=parse_summary,
        )
