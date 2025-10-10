"""Utilities for interacting with Talks Reducer remote servers."""

from __future__ import annotations

import importlib
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Dict, List, Optional

from ..pipeline import ProcessingAborted

if TYPE_CHECKING:  # pragma: no cover - imported for type checking only
    from .app import TalksReducerGUI


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


def check_remote_server_for_gui(
    gui: "TalksReducerGUI",
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
    """GUI-aware wrapper around :func:`check_remote_server`."""

    def log_callback(message: str) -> None:
        gui._schedule_on_ui_thread(lambda msg=message: gui._append_log(msg))

    def status_callback(status: str, message: str) -> None:
        gui._schedule_on_ui_thread(lambda s=status, m=message: gui._set_status(s, m))

    if switch_to_local_on_failure:

        def switch_callback() -> None:
            gui._schedule_on_ui_thread(lambda: gui.processing_mode_var.set("local"))

    else:
        switch_callback = None

    if alert_on_failure:

        def alert_callback(title: str, message: str) -> None:
            gui._schedule_on_ui_thread(
                lambda t=title, m=message: gui.messagebox.showwarning(t, m)
            )

    else:
        alert_callback = None

    return check_remote_server(
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
        on_log=log_callback,
        on_status=status_callback,
        on_switch_to_local=switch_callback,
        on_alert=alert_callback,
        ping=lambda url: gui._ping_server(url),
        sleep=time.sleep,
    )


def _load_service_client() -> object:
    """Return the Talks Reducer service client module."""

    return importlib.import_module("talks_reducer.service_client")


def process_files_via_server(
    gui: "TalksReducerGUI",
    files: List[str],
    args: Dict[str, object],
    server_url: str,
    *,
    open_after_convert: bool,
    default_remote_destination: Callable[[Path, bool], Path],
    parse_summary: Callable[[str], tuple[Optional[float], Optional[float]]],
    load_service_client: Callable[[], object] = _load_service_client,
    check_server: Callable[..., bool] = check_remote_server_for_gui,
) -> bool:
    """Send *files* to the configured server for processing."""

    def _ensure_not_stopped() -> None:
        if gui._stop_requested:
            raise ProcessingAborted("Remote processing cancelled by user.")

    try:
        service_module = load_service_client()
    except ModuleNotFoundError as exc:
        gui._append_log(f"Server client unavailable: {exc}")
        gui._schedule_on_ui_thread(
            lambda: gui.messagebox.showerror(
                "Server unavailable",
                "Remote processing requires the gradio_client package.",
            )
        )
        gui._schedule_on_ui_thread(lambda: gui._set_status("Error"))
        return False

    host_label = format_server_host(server_url)
    gui._schedule_on_ui_thread(
        lambda: gui._set_status("waiting", f"Waiting server {host_label}...")
    )

    available = check_server(
        gui,
        server_url,
        success_status="waiting",
        waiting_status="Error",
        failure_status="Error",
        failure_message=(
            "Server {host} is unreachable after {max_attempts} attempts. Switching to local mode."
        ),
        stop_check=lambda: gui._stop_requested,
        on_stop=_ensure_not_stopped,
        switch_to_local_on_failure=True,
        alert_on_failure=True,
        warning_message=(
            "Server {host} is not reachable. Switching to local processing mode."
        ),
    )

    _ensure_not_stopped()

    if not available:
        return False

    output_override = args.get("output_file") if len(files) == 1 else None
    allowed_remote_keys = {
        "output_file",
        "small",
        "silent_threshold",
        "sounded_speed",
        "silent_speed",
    }
    ignored = [key for key in args if key not in allowed_remote_keys]
    if ignored:
        ignored_options = ", ".join(sorted(ignored))
        gui._append_log(f"Server mode ignores the following options: {ignored_options}")

    small_mode = bool(args.get("small", False))

    for index, file in enumerate(files, start=1):
        _ensure_not_stopped()
        basename = os.path.basename(file)
        gui._append_log(f"Uploading {index}/{len(files)}: {basename} to {server_url}")
        input_path = Path(file)

        if output_override is not None:
            output_path = Path(output_override)
            if output_path.is_dir():
                output_path = (
                    output_path
                    / default_remote_destination(input_path, small=small_mode).name
                )
        else:
            output_path = default_remote_destination(input_path, small=small_mode)

        try:
            destination, summary, log_text = service_module.send_video(
                input_path=input_path,
                output_path=output_path,
                server_url=server_url,
                small=small_mode,
                silent_threshold=args.get("silent_threshold"),
                sounded_speed=args.get("sounded_speed"),
                silent_speed=args.get("silent_speed"),
                stream_updates=True,
                log_callback=gui._append_log,
                should_cancel=lambda: gui._stop_requested,
            )
            _ensure_not_stopped()
        except ProcessingAborted:
            raise
        except Exception as exc:  # pragma: no cover - network safeguard
            error_detail = f"{exc.__class__.__name__}: {exc}"
            error_msg = f"Processing failed: {error_detail}"
            gui._append_log(error_msg)
            gui._schedule_on_ui_thread(lambda: gui._set_status("Error"))
            gui._schedule_on_ui_thread(
                lambda: gui.messagebox.showerror(
                    "Server error", f"Failed to process {basename}: {error_detail}"
                )
            )
            return False

        gui._last_output = Path(destination)
        time_ratio, size_ratio = parse_summary(summary)
        gui._last_time_ratio = time_ratio
        gui._last_size_ratio = size_ratio
        for line in summary.splitlines():
            gui._append_log(line)
        if log_text.strip():
            gui._append_log("Server log:")
            for line in log_text.splitlines():
                gui._append_log(line)
        if open_after_convert:
            gui._schedule_on_ui_thread(
                lambda path=gui._last_output: gui._open_in_file_manager(path)
            )

    gui._append_log("All jobs finished successfully.")
    gui._schedule_on_ui_thread(lambda: gui.open_button.configure(state=gui.tk.NORMAL))
    gui._schedule_on_ui_thread(gui._clear_input_files)
    return True
