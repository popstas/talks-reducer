"""System tray launcher for the Talks Reducer Gradio server."""

from __future__ import annotations

import argparse
import atexit
import logging
import subprocess
import sys
import threading
import time
import webbrowser
from contextlib import suppress
from pathlib import Path
from typing import Any, Callable, Iterator, Optional, Sequence
from urllib.parse import urlsplit, urlunsplit

from PIL import Image

from .icons import iter_icon_candidates
from .server import build_interface
from .version_utils import resolve_version

try:  # pragma: no cover - import guarded for clearer error message at runtime
    import pystray
except ModuleNotFoundError as exc:  # pragma: no cover - handled in ``main``
    PYSTRAY_IMPORT_ERROR = exc
    pystray = None  # type: ignore[assignment]
except Exception as exc:  # pragma: no cover - handled in ``main``
    PYSTRAY_IMPORT_ERROR = exc
    pystray = None  # type: ignore[assignment]
else:
    PYSTRAY_IMPORT_ERROR = None


LOGGER = logging.getLogger(__name__)
APP_VERSION = resolve_version()


def _guess_local_url(host: Optional[str], port: int) -> str:
    """Return the URL the server is most likely reachable at locally."""

    if host in (None, "", "0.0.0.0"):
        hostname = "127.0.0.1"
    elif host == "::":
        hostname = "::1"
    else:
        hostname = host
    return f"http://{hostname}:{port}/"


def _coerce_url(value: Optional[Any]) -> Optional[str]:
    """Convert an arbitrary URL-like object to a trimmed string if possible."""

    if not value:
        return None

    try:
        text = str(value)
    except Exception:  # pragma: no cover - defensive fallback
        return None

    stripped = text.strip()
    return stripped or None


def _normalize_local_url(url: Optional[str], host: Optional[str], port: int) -> str:
    """Rewrite *url* when a wildcard host should map to the loopback address."""

    if not url:
        return _guess_local_url(host, port)

    if host not in (None, "", "0.0.0.0"):
        return url

    try:
        parsed = urlsplit(url)
    except ValueError:
        return _guess_local_url(host, port)

    hostname = parsed.hostname or ""
    if hostname in ("", "0.0.0.0"):
        netloc = f"127.0.0.1:{parsed.port or port}"
        return urlunsplit(
            (
                parsed.scheme or "http",
                netloc,
                parsed.path or "/",
                parsed.query,
                parsed.fragment,
            )
        )

    return url


if sys.platform.startswith("win"):
    _TRAY_ICON_FILENAMES = ("icon.ico", "icon.png", "app.ico", "app.png", "app-256.png")
else:
    _TRAY_ICON_FILENAMES = ("icon.png", "icon.ico", "app.png", "app.ico", "app-256.png")
_ICON_RELATIVE_PATHS = (
    Path("talks_reducer") / "resources" / "icons",
    Path("docs") / "assets",
)


def _iter_icon_candidates() -> Iterator[Path]:
    """Yield possible tray icon paths ordered from most to least specific."""

    yield from iter_icon_candidates(
        filenames=_TRAY_ICON_FILENAMES,
        relative_paths=_ICON_RELATIVE_PATHS,
        module_file=Path(__file__),
    )


def _generate_fallback_icon() -> Image.Image:
    """Return a simple multi-color square used when packaged icons are missing."""

    image = Image.new("RGBA", (64, 64), color=(37, 99, 235, 255))
    for index in range(64):
        image.putpixel((index, index), (17, 24, 39, 255))
        image.putpixel((63 - index, index), (59, 130, 246, 255))
    image.putpixel((0, 0), (255, 255, 255, 255))
    image.putpixel((63, 63), (59, 130, 246, 255))
    return image


def _load_icon() -> Image.Image:
    """Load the tray icon image, falling back to a generated placeholder."""

    LOGGER.info("Attempting to load tray icon image.")

    for candidate in _iter_icon_candidates():
        LOGGER.info("Checking icon candidate at %s", candidate)
        if not candidate.exists():
            continue
        try:
            with Image.open(candidate) as image:
                loaded = image.copy()
        except Exception as exc:  # pragma: no cover - diagnostic log
            LOGGER.warning("Failed to load tray icon from %s: %s", candidate, exc)
            continue

        LOGGER.info("Loaded tray icon from %s", candidate)
        return loaded

    LOGGER.warning("Falling back to generated tray icon; packaged image not found")
    return _generate_fallback_icon()


class _HeadlessTrayBackend:
    """Placeholder backend used when the tray icon is disabled."""

    def __getattr__(self, name: str) -> Any:
        raise RuntimeError(
            "System tray backend is unavailable when running in headless mode."
        )


class _ServerTrayApplication:
    """Coordinate the Gradio server lifecycle and the system tray icon."""

    def __init__(
        self,
        *,
        host: Optional[str],
        port: int,
        share: bool,
        open_browser: bool,
        tray_mode: str,
        tray_backend: Any,
        build_interface: Callable[[], Any],
        open_browser_callback: Callable[[str], Any],
    ) -> None:
        self._host = host
        self._port = port
        self._share = share
        self._open_browser_on_start = open_browser
        self._tray_mode = tray_mode
        self._tray_backend = tray_backend
        self._build_interface = build_interface
        self._open_browser = open_browser_callback

        self._stop_event = threading.Event()
        self._server_ready_event = threading.Event()
        self._ready_event = threading.Event()
        self._gui_lock = threading.Lock()

        self._server_handle: Optional[Any] = None
        self._local_url: Optional[str] = None
        self._share_url: Optional[str] = None
        self._icon: Optional[Any] = None
        self._gui_process: Optional[subprocess.Popen[Any]] = None
        self._startup_error: Optional[BaseException] = None

    # Server lifecycle -------------------------------------------------

    def _launch_server(self) -> None:
        """Start the Gradio server in the background and record its URLs."""

        LOGGER.info(
            "Starting Talks Reducer server on host=%s port=%s share=%s",
            self._host or "127.0.0.1",
            self._port,
            self._share,
        )
        demo = self._build_interface()
        server = demo.launch(
            server_name=self._host,
            server_port=self._port,
            share=self._share,
            inbrowser=False,
            prevent_thread_lock=True,
            show_error=True,
        )

        self._server_handle = server
        fallback_url = _guess_local_url(self._host, self._port)
        local_url = _coerce_url(getattr(server, "local_url", fallback_url))
        self._local_url = _normalize_local_url(local_url, self._host, self._port)
        self._share_url = _coerce_url(getattr(server, "share_url", None))
        self._server_ready_event.set()
        LOGGER.info("Server ready at %s", self._local_url)

        # Keep checking for a share URL while the server is running.
        while not self._stop_event.is_set():
            share_url = _coerce_url(getattr(server, "share_url", None))
            if share_url:
                self._share_url = share_url
                LOGGER.info("Share URL available: %s", share_url)
            time.sleep(0.5)

    # Tray helpers -----------------------------------------------------

    def _resolve_url(self) -> Optional[str]:
        if self._share_url:
            return self._share_url
        return self._local_url

    def _handle_open_webui(
        self,
        _icon: Optional[Any] = None,
        _item: Optional[Any] = None,
    ) -> None:
        url = self._resolve_url()
        if url:
            self._open_browser(url)
            LOGGER.info("Opened browser to %s", url)
        else:
            LOGGER.warning("Server URL not yet available; please try again.")

    def _gui_is_running(self) -> bool:
        """Return whether the GUI subprocess is currently active."""

        process = self._gui_process
        if process is None:
            return False
        if process.poll() is None:
            return True
        self._gui_process = None
        return False

    def _monitor_gui_process(self, process: subprocess.Popen[Any]) -> None:
        """Reset the GUI handle once the subprocess exits."""

        try:
            process.wait()
        except Exception as exc:  # pragma: no cover - best-effort cleanup
            LOGGER.info("GUI process monitor exited with %s", exc)
        finally:
            with self._gui_lock:
                if self._gui_process is process:
                    self._gui_process = None
            LOGGER.info("Talks Reducer GUI closed")

    def _launch_gui(
        self,
        _icon: Optional[Any] = None,
        _item: Optional[Any] = None,
    ) -> None:
        """Launch the Talks Reducer GUI in a background subprocess."""

        with self._gui_lock:
            if self._gui_is_running():
                LOGGER.info(
                    "Talks Reducer GUI already running; focusing existing window"
                )
                return

            try:
                LOGGER.info("Launching Talks Reducer GUI via %s", sys.executable)
                process = subprocess.Popen([sys.executable, "-m", "talks_reducer.gui"])
            except Exception as exc:  # pragma: no cover - platform specific
                LOGGER.error("Failed to launch Talks Reducer GUI: %s", exc)
                self._gui_process = None
                return

            self._gui_process = process

        watcher = threading.Thread(
            target=self._monitor_gui_process,
            args=(process,),
            name="talks-reducer-gui-monitor",
            daemon=True,
        )
        watcher.start()

    def _handle_quit(
        self,
        icon: Optional[Any] = None,
        _item: Optional[Any] = None,
    ) -> None:
        self.stop()
        if icon is not None:
            stop_method = getattr(icon, "stop", None)
            if callable(stop_method):
                with suppress(Exception):
                    stop_method()

    # Public API -------------------------------------------------------

    def _await_server_start(self, icon: Optional[Any]) -> None:
        """Wait for the server to signal readiness or trigger shutdown on failure."""

        if self._server_ready_event.wait(timeout=30):
            try:
                if self._open_browser_on_start and not self._stop_event.is_set():
                    self._handle_open_webui()
            finally:
                self._ready_event.set()
            return

        if self._stop_event.is_set():
            return

        error = RuntimeError(
            "Timed out while waiting for the Talks Reducer server to start."
        )
        self._startup_error = error
        LOGGER.error("%s", error)

        if icon is not None:
            notify = getattr(icon, "notify", None)
            if callable(notify):
                with suppress(Exception):
                    notify("Talks Reducer server failed to start.")

        self.stop()

    def run(self) -> None:
        """Start the server and block until the tray icon exits."""

        self._startup_error = None

        threading.Thread(
            target=self._launch_server, name="talks-reducer-server", daemon=True
        ).start()

        if self._tray_mode == "headless":
            LOGGER.warning(
                "Tray icon disabled (tray_mode=headless); press Ctrl+C to stop the server."
            )
            self._await_server_start(None)
            if self._startup_error is not None:
                raise self._startup_error
            try:
                while not self._stop_event.wait(0.5):
                    pass
            finally:
                self.stop()
            return

        icon_image = _load_icon()
        version_suffix = (
            f" v{APP_VERSION}" if APP_VERSION and APP_VERSION != "unknown" else ""
        )
        version_label = f"Talks Reducer{version_suffix}"
        menu = self._tray_backend.Menu(
            self._tray_backend.MenuItem(version_label, None, enabled=False),
            self._tray_backend.MenuItem(
                "Open GUI",
                self._launch_gui,
                default=True,
            ),
            self._tray_backend.MenuItem("Open WebUI", self._handle_open_webui),
            self._tray_backend.MenuItem("Quit", self._handle_quit),
        )
        self._icon = self._tray_backend.Icon(
            "talks-reducer",
            icon_image,
            f"{version_label} Server",
            menu=menu,
        )

        watcher = threading.Thread(
            target=self._await_server_start,
            args=(self._icon,),
            name="talks-reducer-server-watcher",
            daemon=True,
        )
        watcher.start()

        if self._tray_mode == "pystray-detached":
            LOGGER.info("Running tray icon in detached mode")
            self._icon.run_detached()
            try:
                while not self._stop_event.wait(0.5):
                    pass
            finally:
                self.stop()
            if self._startup_error is not None:
                raise self._startup_error
            return

        LOGGER.info("Running tray icon in blocking mode")
        self._icon.run()
        if self._startup_error is not None:
            raise self._startup_error

    def stop(self) -> None:
        """Stop the tray icon and shut down the Gradio server."""

        self._stop_event.set()
        self._server_ready_event.set()
        self._ready_event.set()

        if self._icon is not None:
            with suppress(Exception):
                if hasattr(self._icon, "visible"):
                    self._icon.visible = False
            stop_method = getattr(self._icon, "stop", None)
            if callable(stop_method):
                with suppress(Exception):
                    stop_method()

        self._stop_gui()

        if self._server_handle is not None:
            with suppress(Exception):
                self._server_handle.close()
            LOGGER.info("Shut down Talks Reducer server")

    def _stop_gui(self) -> None:
        """Terminate the GUI subprocess if it is still running."""

        with self._gui_lock:
            process = self._gui_process
            if process is None:
                return

            if process.poll() is None:
                LOGGER.info("Stopping Talks Reducer GUI")
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    LOGGER.warning(
                        "GUI process did not exit cleanly; forcing termination"
                    )
                    process.kill()
                    process.wait(timeout=5)
                except Exception as exc:  # pragma: no cover - defensive cleanup
                    LOGGER.info("Error while terminating GUI process: %s", exc)

            self._gui_process = None


def create_tray_app(
    *,
    host: Optional[str],
    port: int,
    share: bool,
    open_browser: bool,
    tray_mode: str,
) -> _ServerTrayApplication:
    """Build a :class:`_ServerTrayApplication` wired to production dependencies."""

    if tray_mode != "headless" and (
        pystray is None or PYSTRAY_IMPORT_ERROR is not None
    ):
        raise RuntimeError(
            "System tray mode requires the 'pystray' dependency. Install it with "
            "`pip install pystray` or `pip install talks-reducer[dev]` and try again."
        ) from PYSTRAY_IMPORT_ERROR

    tray_backend: Any
    if pystray is None:
        tray_backend = _HeadlessTrayBackend()
    else:
        tray_backend = pystray

    return _ServerTrayApplication(
        host=host,
        port=port,
        share=share,
        open_browser=open_browser,
        tray_mode=tray_mode,
        tray_backend=tray_backend,
        build_interface=build_interface,
        open_browser_callback=webbrowser.open,
    )


def main(argv: Optional[Sequence[str]] = None) -> None:
    """Launch the Gradio server with a companion system tray icon."""

    parser = argparse.ArgumentParser(
        description="Launch the Talks Reducer server with a system tray icon."
    )
    parser.add_argument(
        "--host", dest="host", default="0.0.0.0", help="Custom host to bind."
    )
    parser.add_argument(
        "--port",
        dest="port",
        type=int,
        default=9005,
        help="Port number for the web server (default: 9005).",
    )
    parser.add_argument(
        "--share",
        action="store_true",
        help="Create a temporary public Gradio link.",
    )
    browser_group = parser.add_mutually_exclusive_group()
    browser_group.add_argument(
        "--open-browser",
        dest="open_browser",
        action="store_true",
        help="Automatically open the web interface after startup.",
    )
    browser_group.add_argument(
        "--no-browser",
        dest="open_browser",
        action="store_false",
        help="Do not open the web interface automatically (default).",
    )
    parser.set_defaults(open_browser=False)
    parser.add_argument(
        "--tray-mode",
        choices=("pystray", "pystray-detached", "headless"),
        default="pystray",
        help=(
            "Select how the tray runs: foreground pystray (default), detached "
            "pystray worker, or disable the tray entirely."
        ),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose logging for troubleshooting.",
    )

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    app = create_tray_app(
        host=args.host,
        port=args.port,
        share=args.share,
        open_browser=args.open_browser,
        tray_mode=args.tray_mode,
    )

    atexit.register(app.stop)

    try:
        app.run()
    except KeyboardInterrupt:  # pragma: no cover - interactive convenience
        app.stop()


__all__ = ["create_tray_app", "main"]


if __name__ == "__main__":  # pragma: no cover - convenience entry point
    main()
