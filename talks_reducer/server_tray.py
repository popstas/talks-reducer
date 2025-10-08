"""System tray launcher for the Talks Reducer Gradio server."""

from __future__ import annotations

import argparse
import atexit
import logging
import threading
import time
import webbrowser
from contextlib import suppress
from importlib import resources
from pathlib import Path
from typing import Any, Optional, Sequence

from PIL import Image

from .server import build_interface

try:  # pragma: no cover - import guarded for clearer error message at runtime
    import pystray
except ModuleNotFoundError as exc:  # pragma: no cover - handled in ``main``
    PYSTRAY_IMPORT_ERROR = exc
    pystray = None  # type: ignore[assignment]
else:
    PYSTRAY_IMPORT_ERROR = None


LOGGER = logging.getLogger(__name__)


def _guess_local_url(host: Optional[str], port: int) -> str:
    """Return the URL the server is most likely reachable at locally."""

    if host in (None, "", "0.0.0.0", "::"):
        hostname = "127.0.0.1"
    else:
        hostname = host
    return f"http://{hostname}:{port}/"


def _load_icon() -> Image.Image:
    """Load the tray icon image, falling back to a solid accent square."""

    LOGGER.debug("Attempting to load tray icon image.")

    candidates = [
        Path(__file__).resolve().parent.parent / "docs" / "assets" / "icon.png",
        Path(__file__).resolve().parent / "icon.png",
    ]

    for candidate in candidates:
        LOGGER.debug("Checking icon candidate at %s", candidate)
        if candidate.exists():
            try:
                image = Image.open(candidate).copy()
            except Exception as exc:  # pragma: no cover - diagnostic log
                LOGGER.warning("Failed to load tray icon from %s: %s", candidate, exc)
            else:
                LOGGER.debug("Loaded tray icon from %s", candidate)
                return image

    with suppress(FileNotFoundError):
        resource_icon = resources.files("talks_reducer") / "assets" / "icon.png"
        if resource_icon.is_file():
            LOGGER.debug("Loading tray icon from package resources")
            with resource_icon.open("rb") as handle:
                try:
                    return Image.open(handle).copy()
                except Exception as exc:  # pragma: no cover - diagnostic log
                    LOGGER.warning(
                        "Failed to load tray icon from package resources: %s", exc
                    )

    LOGGER.warning("Falling back to generated tray icon; packaged image not found")
    # Fallback to a simple accent-colored square to avoid import errors
    image = Image.new("RGBA", (64, 64), color=(37, 99, 235, 255))
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

        self._server_handle: Optional[Any] = None
        self._local_url: Optional[str] = None
        self._share_url: Optional[str] = None
        self._icon: Optional[pystray.Icon] = None

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
        self._local_url = getattr(
            server, "local_url", _guess_local_url(self._host, self._port)
        )
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

    def _handle_open(
        self,
        _icon: Optional[pystray.Icon] = None,
        _item: Optional[pystray.MenuItem] = None,
    ) -> None:
        url = self._resolve_url()
        if url:
            webbrowser.open(url)
            LOGGER.debug("Opened browser to %s", url)

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
            self._handle_open()

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
        menu = pystray.Menu(
            pystray.MenuItem("Open Talks Reducer", self._handle_open),
            pystray.MenuItem("Quit", self._handle_quit),
        )
        self._icon = pystray.Icon(
            "talks-reducer", icon_image, "Talks Reducer Server", menu=menu
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

        if self._server_handle is not None:
            with suppress(Exception):
                self._server_handle.close()
            LOGGER.info("Shut down Talks Reducer server")


def main(argv: Optional[Sequence[str]] = None) -> None:
    """Launch the Gradio server with a companion system tray icon."""

    parser = argparse.ArgumentParser(
        description="Launch the Talks Reducer server with a system tray icon."
    )
    parser.add_argument(
        "--host", dest="host", default=None, help="Custom host to bind."
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
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not automatically open the browser window.",
    )
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
        open_browser=not args.no_browser,
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
