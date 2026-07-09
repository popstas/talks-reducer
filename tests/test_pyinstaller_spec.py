"""Guard the PyInstaller spec against regressions that break the frozen bundle.

The spec is a PyInstaller build file that references ``Analysis``/``PYZ``/``EXE``
globals which only exist inside a PyInstaller build, so it cannot simply be
imported. Instead the ``DEFAULT_EXCLUDES`` list literal is extracted statically
with :mod:`ast` and asserted on.
"""

from __future__ import annotations

import ast
import pathlib

SPEC_PATH = pathlib.Path(__file__).resolve().parent.parent / "talks-reducer.spec"


def _default_excludes() -> list[str]:
    """Return the ``DEFAULT_EXCLUDES`` string list defined in the spec file."""

    tree = ast.parse(SPEC_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "DEFAULT_EXCLUDES" in targets and isinstance(node.value, ast.List):
                return [
                    element.value
                    for element in node.value.elts
                    if isinstance(element, ast.Constant)
                    and isinstance(element.value, str)
                ]
    raise AssertionError("DEFAULT_EXCLUDES list not found in talks-reducer.spec")


def test_pandas_is_not_excluded_from_bundle() -> None:
    """Newer gradio imports pandas eagerly, so excluding it breaks the bundle.

    ``gradio/caching.py`` imports pandas at module top-level (pulled in by
    ``import gradio`` via ``routes`` → ``networking`` → ``blocks``). Excluding
    pandas made ``import gradio`` raise ``ModuleNotFoundError`` inside the frozen
    bundle, killing both the web server and the "Run as server in tray" mode.
    """

    excludes = _default_excludes()
    assert "pandas" not in excludes
    # pandas needs its timezone data, so those must not be excluded either.
    assert "pytz" not in excludes
    assert "tzdata" not in excludes
