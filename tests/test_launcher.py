"""Tests for the PyInstaller launcher script."""

from __future__ import annotations

import json
import multiprocessing
import runpy
import subprocess
import sys
from pathlib import Path

LAUNCHER = Path(__file__).resolve().parents[1] / "launcher.py"

HEAVY_MODULES = ("numpy", "tkinter", "gradio", "talks_reducer.cli", "talks_reducer.gui")


def test_launcher_prepares_multiprocessing_before_starting_the_app(monkeypatch):
    """Frozen builds re-run the launcher per worker, so the bootstrap comes first."""

    events: list[str] = []

    monkeypatch.setattr(
        multiprocessing, "freeze_support", lambda: events.append("freeze_support")
    )
    monkeypatch.setattr("talks_reducer.gui.main", lambda: events.append("gui") or True)

    runpy.run_path(str(LAUNCHER), run_name="__main__")

    assert events == ["freeze_support", "gui"]


def test_launcher_dispatches_dock_server_before_importing_the_gui(
    tmp_path: Path,
) -> None:
    """``talks-reducer.exe dock-server`` must not load the GUI, cli or numpy.

    Runs in a child interpreter so this process's already-imported modules do
    not pollute the measurement. The stub reports through a file rather than
    stdout because the launcher's Windows console-attachment block can reopen
    ``sys.stdout`` and swallow anything printed afterwards.
    """

    report_path = tmp_path / "report.json"

    script = "\n".join(
        [
            "import json, runpy, sys",
            "import talks_reducer.dock_server as dock",
            "report = {}",
            "def stub(argv=None):",
            "    report['argv'] = list(argv or [])",
            "    report['modules'] = sorted(sys.modules)",
            f"    open({json.dumps(str(report_path))}, 'w').write(json.dumps(report))",
            "dock.main = stub",
            f"sys.argv = {json.dumps([str(LAUNCHER), 'dock-server', '--port', '4242'])}",
            f"runpy.run_path({json.dumps(str(LAUNCHER))}, run_name='__main__')",
        ]
    )
    subprocess.run(
        [sys.executable, "-c", script],
        cwd=LAUNCHER.parent,
        capture_output=True,
        text=True,
        check=True,
    )
    report = json.loads(report_path.read_text())

    assert report["argv"] == ["--port", "4242"]
    heavy = [
        name
        for name in report["modules"]
        if name in HEAVY_MODULES or name.split(".")[0] in HEAVY_MODULES
    ]
    assert heavy == []
