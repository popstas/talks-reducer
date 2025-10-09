"""System tray launcher for the Talks Reducer Gradio server."""

from __future__ import annotations

import argparse
import atexit
import base64
import logging
import subprocess
import sys
import threading
import time
import webbrowser
from contextlib import suppress
from importlib import resources
from io import BytesIO
from pathlib import Path
from typing import Any, Iterator, Optional, Sequence
from urllib.parse import urlsplit, urlunsplit

from PIL import Image

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


def _normalize_local_url(url: str, host: Optional[str], port: int) -> str:
    """Rewrite *url* when a wildcard host should map to the loopback address."""

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


def _iter_icon_candidates() -> Iterator[Path]:
    """Yield possible tray icon paths ordered from most to least specific."""

    module_path = Path(__file__).resolve()
    package_root = module_path.parent
    project_root = package_root.parent

    frozen_root: Optional[Path] = None
    frozen_value = getattr(sys, "_MEIPASS", None)
    if frozen_value:
        with suppress(Exception):
            frozen_root = Path(str(frozen_value)).resolve()

    executable_root: Optional[Path] = None
    with suppress(Exception):
        executable_root = Path(sys.executable).resolve().parent

    launcher_root: Optional[Path] = None
    with suppress(Exception):
        launcher_root = Path(sys.argv[0]).resolve().parent

    base_roots: list[Path] = []
    for candidate in (
        package_root,
        project_root,
        frozen_root,
        executable_root,
        launcher_root,
    ):
        if candidate and candidate not in base_roots:
            base_roots.append(candidate)

    expanded_roots: list[Path] = []
    suffixes = (
        Path(""),
        Path("_internal"),
        Path("Contents") / "Resources",
        Path("Resources"),
    )
    for root in base_roots:
        for suffix in suffixes:
            candidate_root = (root / suffix).resolve()
            if candidate_root not in expanded_roots:
                expanded_roots.append(candidate_root)

    icon_names = ("icon.ico", "icon.png") if sys.platform == "win32" else ("icon.png", "icon.ico")
    relative_paths = (
        Path("talks_reducer") / "resources" / "icons",
        Path("talks_reducer") / "assets",
        Path("docs") / "assets",
        Path("assets"),
        Path(""),
    )

    seen: set[Path] = set()
    for root in expanded_roots:
        if not root.exists():
            continue
        for relative in relative_paths:
            for icon_name in icon_names:
                candidate = (root / relative / icon_name).resolve()
                if candidate in seen:
                    continue
                seen.add(candidate)
                yield candidate


def _load_icon() -> Image.Image:
    """Load the tray icon image, falling back to the embedded pen artwork."""

    LOGGER.debug("Attempting to load tray icon image.")

    for candidate in _iter_icon_candidates():
        LOGGER.debug("Checking icon candidate at %s", candidate)
        if candidate.exists():
            try:
                with Image.open(candidate) as image:
                    loaded = image.copy()
            except Exception as exc:  # pragma: no cover - diagnostic log
                LOGGER.warning("Failed to load tray icon from %s: %s", candidate, exc)
            else:
                LOGGER.debug("Loaded tray icon from %s", candidate)
                return loaded

    LOGGER.warning("Falling back to generated tray icon; packaged image not found")
    image = Image.new("RGBA", (64, 64), color=(37, 99, 235, 255))
    image.putpixel((0, 0), (255, 255, 255, 255))
    image.putpixel((63, 63), (17, 24, 39, 255))
    return image


_EMBEDDED_ICON_BASE64 = (
    "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"
)


def _load_embedded_icon() -> Image.Image:
    """Decode and return the embedded Talks Reducer tray icon."""

    data = base64.b64decode(_EMBEDDED_ICON_BASE64)
    with Image.open(BytesIO(data)) as image:
        return image.copy()


def _load_icon() -> Image.Image:
    """Load the tray icon image, falling back to the embedded pen artwork."""

    LOGGER.debug("Attempting to load tray icon image.")

    for candidate in _iter_icon_candidates():
        LOGGER.debug("Checking icon candidate at %s", candidate)
        if candidate.exists():
            try:
                with Image.open(candidate) as image:
                    loaded = image.copy()
            except Exception as exc:  # pragma: no cover - diagnostic log
                LOGGER.warning("Failed to load tray icon from %s: %s", candidate, exc)
            else:
                LOGGER.debug("Loaded tray icon from %s", candidate)
                return loaded

    with suppress(FileNotFoundError):
        resource_icon = resources.files("talks_reducer") / "assets" / "icon.png"
        if resource_icon.is_file():
            LOGGER.debug("Loading tray icon from package resources")
            with resource_icon.open("rb") as handle:
                try:
                    with Image.open(handle) as image:
                        return image.copy()
                except Exception as exc:  # pragma: no cover - diagnostic log
                    LOGGER.warning(
                        "Failed to load tray icon from package resources: %s", exc
                    )

    LOGGER.warning("Falling back to generated tray icon; packaged image not found")
    image = Image.new("RGBA", (64, 64), color=(37, 99, 235, 255))
    image.putpixel((0, 0), (255, 255, 255, 255))
    image.putpixel((63, 63), (17, 24, 39, 255))
    return image


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
    ) -> None:
        self._host = host
        self._port = port
        self._share = share
        self._open_browser_on_start = open_browser
        self._tray_mode = tray_mode

        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._gui_lock = threading.Lock()

        self._server_handle: Optional[Any] = None
        self._local_url: Optional[str] = None
        self._share_url: Optional[str] = None
        self._icon: Optional[pystray.Icon] = None
        self._gui_process: Optional[subprocess.Popen[Any]] = None

    # Server lifecycle -------------------------------------------------

    def _launch_server(self) -> None:
        """Start the Gradio server in the background and record its URLs."""

        LOGGER.info(
            "Starting Talks Reducer server on host=%s port=%s share=%s",
            self._host or "127.0.0.1",
            self._port,
            self._share,
        )
        demo = build_interface()
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
        local_url = getattr(server, "local_url", fallback_url)
        self._local_url = _normalize_local_url(local_url, self._host, self._port)
        self._share_url = getattr(server, "share_url", None)
        self._ready_event.set()
        LOGGER.info("Server ready at %s", self._local_url)

        # Keep checking for a share URL while the server is running.
        while not self._stop_event.is_set():
            share_url = getattr(server, "share_url", None)
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
        _icon: Optional[pystray.Icon] = None,
        _item: Optional[pystray.MenuItem] = None,
    ) -> None:
        url = self._resolve_url()
        if url:
            webbrowser.open(url)
            LOGGER.debug("Opened browser to %s", url)
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
            LOGGER.debug("GUI process monitor exited with %s", exc)
        finally:
            with self._gui_lock:
                if self._gui_process is process:
                    self._gui_process = None
            LOGGER.info("Talks Reducer GUI closed")

    def _launch_gui(
        self,
        _icon: Optional[pystray.Icon] = None,
        _item: Optional[pystray.MenuItem] = None,
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
                process = subprocess.Popen(
                    [sys.executable, "-m", "talks_reducer.gui"]
                )
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
        icon: Optional[pystray.Icon] = None,
        _item: Optional[pystray.MenuItem] = None,
    ) -> None:
        self.stop()
        if icon is not None:
            icon.stop()

    # Public API -------------------------------------------------------

    def run(self) -> None:
        """Start the server and block until the tray icon exits."""

        server_thread = threading.Thread(
            target=self._launch_server, name="talks-reducer-server", daemon=True
        )
        server_thread.start()

        if not self._ready_event.wait(timeout=30):
            raise RuntimeError(
                "Timed out while waiting for the Talks Reducer server to start."
            )

        if self._open_browser_on_start:
            self._handle_open_webui()

        if self._tray_mode == "headless":
            LOGGER.warning(
                "Tray icon disabled (tray_mode=headless); press Ctrl+C to stop the server."
            )
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
        menu = pystray.Menu(
            pystray.MenuItem(version_label, None, enabled=False),
            pystray.MenuItem(
                "Open GUI",
                self._launch_gui,
                default=True,
            ),
            pystray.MenuItem("Open WebUI", self._handle_open_webui),
            pystray.MenuItem("Quit", self._handle_quit),
        )
        self._icon = pystray.Icon(
            "talks-reducer",
            icon_image,
            f"{version_label} Server",
            menu=menu,
        )

        if self._tray_mode == "pystray-detached":
            LOGGER.info("Running tray icon in detached mode")
            self._icon.run_detached()
            try:
                while not self._stop_event.wait(0.5):
                    pass
            finally:
                self.stop()
            return

        LOGGER.info("Running tray icon in blocking mode")
        self._icon.run()

    def stop(self) -> None:
        """Stop the tray icon and shut down the Gradio server."""

        self._stop_event.set()

        if self._icon is not None:
            with suppress(Exception):
                self._icon.visible = False
            with suppress(Exception):
                self._icon.stop()

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
                    LOGGER.debug("Error while terminating GUI process: %s", exc)

            self._gui_process = None


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

    if args.tray_mode != "headless" and PYSTRAY_IMPORT_ERROR is not None:
        raise RuntimeError(
            "System tray mode requires the 'pystray' dependency. Install it with "
            "`pip install pystray` or `pip install talks-reducer[dev]` and try again."
        ) from PYSTRAY_IMPORT_ERROR

    app = _ServerTrayApplication(
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


__all__ = ["main"]


if __name__ == "__main__":  # pragma: no cover - convenience entry point
    main()
