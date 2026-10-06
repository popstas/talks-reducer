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
