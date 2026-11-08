"""Fail when a subprocess spawn could flash a console window on Windows.

A console program started from the windowed Windows build opens its own
console unless it gets ``CREATE_NO_WINDOW``. The flag used to be copied by hand
into each call, and a call that missed it (``pipeline._extract_video_metadata``)
flashed a window at the start and end of every conversion. Every spawn must now
pass ``**hidden_subprocess_kwargs()`` in the call itself, or be listed in
``ALLOWED`` with the reason it is safe.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterator, Optional, Tuple

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "talks_reducer"
SPAWN_FUNCTIONS = {"run", "Popen", "call", "check_call", "check_output"}
HELPER_NAME = "hidden_subprocess_kwargs"

# (path relative to talks_reducer/, enclosing function) -> why it is safe.
ALLOWED = {
    (
        "cli.py",
        "_launch_server_tray_binary",
    ): "own _should_hide_subprocess_console() gating; see tests/test_cli.py",
    (
        "gui/relaunch.py",
        "spawn_detached",
    ): "deliberately DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP",
    (
        "server_tray.py",
        "_launch_gui",
    ): "launches the GUI, which has no console in the frozen build",
    (
        "gui/app.py",
        "_on_download_complete",
    ): "non-Windows branch; Windows uses os.startfile",
    (
        "gui/app.py",
        "_open_in_file_manager",
    ): "explorer / open / xdg-open are GUI programs",
    ("gui/theme.py", "run_defaults_command"): "macOS only",
}

Spawn = Tuple[str, int, str]


def _passes_helper(call: ast.Call) -> bool:
    """Return True when *call* has ``**hidden_subprocess_kwargs()``."""

    for keyword in call.keywords:
        value = keyword.value
        if keyword.arg is not None or not isinstance(value, ast.Call):
            continue
        func = value.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name == HELPER_NAME:
            return True
    return False


def _is_subprocess_spawn(call: ast.Call) -> bool:
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr in SPAWN_FUNCTIONS
        and isinstance(func.value, ast.Name)
        and func.value.id == "subprocess"
    )


def _unhidden_spawns() -> Iterator[Spawn]:
    """Yield ``(relative path, line, enclosing function)`` for each bad spawn."""

    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        relative = path.relative_to(PACKAGE_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        yield from _walk(tree, relative, None)


def _walk(node: ast.AST, relative: str, function: Optional[str]) -> Iterator[Spawn]:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            inner = child.name
        else:
            inner = function
        if (
            isinstance(child, ast.Call)
            and _is_subprocess_spawn(child)
            and not _passes_helper(child)
        ):
            yield relative, child.lineno, function or "<module>"
        yield from _walk(child, relative, inner)


def test_every_subprocess_spawn_hides_its_console() -> None:
    offenders = [
        f"talks_reducer/{path}:{line} in {function}()"
        for path, line, function in _unhidden_spawns()
        if (path, function) not in ALLOWED
    ]

    assert not offenders, (
        "These subprocess calls can flash a console window on Windows. Pass "
        "**hidden_subprocess_kwargs() (talks_reducer/subprocess_utils.py), or "
        "add them to ALLOWED with a reason:\n  " + "\n  ".join(offenders)
    )


def test_allowlist_has_no_stale_entries() -> None:
    """An entry whose call was fixed or removed must leave the allowlist."""

    seen = {(path, function) for path, _, function in _unhidden_spawns()}
    stale = sorted(set(ALLOWED) - seen)

    assert not stale, f"Remove these ALLOWED entries, they match nothing: {stale}"


def test_guard_flags_a_spawn_without_the_helper() -> None:
    """The detector itself must catch the bug that started this."""

    bad = ast.parse("subprocess.Popen(cmd, stdout=subprocess.PIPE)").body[0].value
    good = ast.parse("subprocess.run(cmd, **hidden_subprocess_kwargs())").body[0].value

    assert _is_subprocess_spawn(bad) and not _passes_helper(bad)
    assert _is_subprocess_spawn(good) and _passes_helper(good)
