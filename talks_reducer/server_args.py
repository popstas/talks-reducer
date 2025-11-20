"""Shared argument parsing helpers for server entrypoints."""

from __future__ import annotations

import argparse


def build_server_parser(
    *, description: str, default_open_browser: bool
) -> argparse.ArgumentParser:
    """Return an ``ArgumentParser`` with common server flags preconfigured."""

    parser = argparse.ArgumentParser(description=description)
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
        help=(
            "Do not automatically open the browser window."
            if default_open_browser
            else "Do not open the web interface automatically (default)."
        ),
    )
    parser.set_defaults(open_browser=default_open_browser)

    return parser


__all__ = ["build_server_parser"]
