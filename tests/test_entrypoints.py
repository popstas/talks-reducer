"""Coverage tests for module-level entry points."""

from __future__ import annotations

import runpy
import sys


def test_package_main_invokes_cli(monkeypatch):
    """Running the package as a module should call the CLI entry point."""

    calls: list[str] = []

    def fake_main() -> None:
        calls.append("cli")

    monkeypatch.setattr("talks_reducer.cli.main", fake_main)
    sys.modules.pop("talks_reducer.__main__", None)

    runpy.run_module("talks_reducer.__main__", run_name="__main__")

    assert calls == ["cli"]


def test_gui_main_invokes_startup(monkeypatch):
    """Running the GUI package as a module should call the startup entry point."""

    calls: list[str] = []

    def fake_main() -> None:
        calls.append("gui")

    monkeypatch.setattr("talks_reducer.gui.startup.main", fake_main)
    sys.modules.pop("talks_reducer.gui.__main__", None)

    runpy.run_module("talks_reducer.gui.__main__", run_name="__main__")

    assert calls == ["gui"]


def test_package_main_routes_non_dock_argv_to_cli(monkeypatch):
    """Any argv other than the dock keywords still reaches the CLI entry point."""

    calls: list[str] = []

    monkeypatch.setattr("talks_reducer.cli.main", lambda: calls.append("cli"))
    monkeypatch.setattr(
        "talks_reducer.dock_server.main", lambda argv=None: calls.append("dock")
    )
    monkeypatch.setattr(sys, "argv", ["talks_reducer", "--version"])
    sys.modules.pop("talks_reducer.__main__", None)

    runpy.run_module("talks_reducer.__main__", run_name="__main__")

    assert calls == ["cli"]


def test_package_main_routes_obs_dock_alias_to_dock_server(monkeypatch):
    """The ``obs-dock`` alias reaches the dock server with the trailing argv."""

    calls: list[object] = []

    monkeypatch.setattr("talks_reducer.cli.main", lambda: calls.append("cli"))
    monkeypatch.setattr(
        "talks_reducer.dock_server.main", lambda argv=None: calls.append(list(argv))
    )
    monkeypatch.setattr(sys, "argv", ["talks_reducer", "obs-dock", "--port", "4242"])
    sys.modules.pop("talks_reducer.__main__", None)

    runpy.run_module("talks_reducer.__main__", run_name="__main__")

    assert calls == [["--port", "4242"]]
