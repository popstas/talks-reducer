"""Coverage tests for module-level entry points."""

from __future__ import annotations

import builtins
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


def test_package_main_falls_back_to_absolute_import(monkeypatch):
    """If the relative import fails, the absolute fallback should execute."""

    calls: list[str] = []
    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level == 1 and name == "cli":
            raise ImportError("relative import blocked")
        return original_import(name, globals, locals, fromlist, level)

    def fake_main() -> None:
        calls.append("cli-fallback")

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr("talks_reducer.cli.main", fake_main)
    sys.modules.pop("talks_reducer.__main__", None)

    runpy.run_module("talks_reducer.__main__", run_name="__main__")

    assert calls == ["cli-fallback"]
