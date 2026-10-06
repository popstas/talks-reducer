"""Import-weight tests: the dock server must not drag in the processing stack."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

HEAVY_MODULES = ("numpy", "tkinter", "gradio", "talks_reducer.cli", "talks_reducer.gui")


def _loaded_modules_after(code: str) -> list[str]:
    """Run ``code`` in a fresh interpreter and return the modules it left loaded."""

    script = "import json, sys\n" f"{code}\n" "print(json.dumps(sorted(sys.modules)))\n"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_importing_dock_server_skips_the_processing_stack() -> None:
    """``import talks_reducer.dock_server`` must not load numpy, tkinter or cli."""

    loaded = _loaded_modules_after("import talks_reducer.dock_server")

    assert "talks_reducer.dock_server" in loaded
    assert not [
        name
        for name in loaded
        if name.split(".")[0] in HEAVY_MODULES or name in HEAVY_MODULES
    ]


def test_package_main_still_resolves_to_cli_main() -> None:
    """``talks_reducer.main`` stays available for callers that import it lazily."""

    import talks_reducer
    from talks_reducer import cli

    assert talks_reducer.main is cli.main


def test_package_main_is_resolved_lazily() -> None:
    """Importing the package leaves ``cli`` unloaded until ``main`` is accessed.

    The "not loaded before" half is an inline ``assert`` in the child, so a
    regression to an eager import fails the subprocess and ``check=True``.
    """

    loaded = _loaded_modules_after(
        "\n".join(
            [
                "import talks_reducer",
                "assert 'talks_reducer.cli' not in sys.modules",
                "talks_reducer.main",
                "assert 'talks_reducer.cli' in sys.modules",
            ]
        )
    )

    assert "talks_reducer.cli" in loaded


def _run_entry_point_with_stubbed_dock(
    args: list[str], *, runner: str, report_path: Path
) -> dict:
    """Invoke an entry point with ``dock_server.main`` stubbed; report what loaded.

    ``runner`` is Python source that starts the entry point. The stub records
    the argv it received and the modules present at that moment, writing them
    to ``report_path`` so entry points that reopen stdout cannot swallow them.
    """

    script = "\n".join(
        [
            "import json, sys",
            "import talks_reducer.dock_server as dock",
            "report = {}",
            "def stub(argv=None):",
            "    report['argv'] = list(argv or [])",
            "    report['modules'] = sorted(sys.modules)",
            f"    open({json.dumps(str(report_path))}, 'w').write(json.dumps(report))",
            "dock.main = stub",
            f"sys.argv = {json.dumps(args)}",
            runner,
        ]
    )
    subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(report_path.read_text())


def _heavy(loaded: list[str]) -> list[str]:
    return [
        name
        for name in loaded
        if name in HEAVY_MODULES or name.split(".")[0] in HEAVY_MODULES
    ]


def test_module_entry_point_dispatches_dock_server_lightly(tmp_path: Path) -> None:
    """``python -m talks_reducer dock-server`` never imports cli, numpy or the GUI."""

    report = _run_entry_point_with_stubbed_dock(
        ["talks_reducer", "dock-server", "--port", "4242"],
        runner="import runpy; runpy.run_module('talks_reducer', run_name='__main__')",
        report_path=tmp_path / "report.json",
    )

    assert report["argv"] == ["--port", "4242"]
    assert _heavy(report["modules"]) == []
