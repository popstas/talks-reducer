#!/usr/bin/env python3
"""Print the Talks Reducer version for packaging scripts."""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from typing import Optional

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - fallback for <3.11
    import tomli as tomllib  # type: ignore[no-redef]


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load_version_from_about() -> Optional[str]:
    """Return the package version declared in ``talks_reducer.__about__``."""

    about_path = REPO_ROOT / "talks_reducer" / "__about__.py"
    if not about_path.exists():
        return None

    spec = importlib.util.spec_from_file_location("talks_reducer.__about__", about_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    version = getattr(module, "__version__", None)
    return str(version) if version else None


def _load_version_from_pyproject() -> Optional[str]:
    """Return the package version parsed from ``pyproject.toml`` if present."""

    pyproject = REPO_ROOT / "pyproject.toml"
    if not pyproject.exists():
        return None

    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = data.get("project")
    if isinstance(project, dict):
        version = project.get("version")
        if isinstance(version, str) and version:
            return version

    tool_table = data.get("tool")
    if isinstance(tool_table, dict):
        poetry_table = tool_table.get("poetry")
        if isinstance(poetry_table, dict):
            version = poetry_table.get("version")
            if isinstance(version, str) and version:
                return version

    return None


def read_version() -> str:
    """Determine the application version from repository metadata."""

    version = _load_version_from_about() or _load_version_from_pyproject()
    return version or ""


def main() -> int:
    """Entry point for CLI invocation."""

    version = read_version()
    if not version:
        print(
            "Unable to determine package version. Ensure __about__ or pyproject.toml defines it.",
            file=sys.stderr,
        )
        return 1
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
