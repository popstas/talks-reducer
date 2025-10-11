"""Icon discovery helpers shared across Talks Reducer entry points."""

from __future__ import annotations

import logging
import sys
from contextlib import suppress
from pathlib import Path
from typing import Iterator, Optional, Sequence

LOGGER = logging.getLogger(__name__)

_ICON_RELATIVE_PATHS: Sequence[Path] = (
    Path("resources") / "icons",
    Path("talks_reducer") / "resources" / "icons",
    Path("talks_reducer") / "assets",
    Path("assets"),
    Path("docs") / "assets",
)
_ICON_PATH_SUFFIXES: Sequence[Path] = (
    Path(""),
    Path("_internal"),
    Path("_internal") / "talks_reducer",
    Path("Contents") / "Resources",
    Path("Resources"),
)


def _iter_base_roots(module_file: Optional[Path | str] = None) -> Iterator[Path]:
    """Yield base directories where icon assets may live."""

    module_path = Path(module_file or __file__).resolve()
    package_root = module_path.parent
    project_root = package_root.parent

    seen: set[Path] = set()

    def _yield(label: str, path: Optional[Path | str]) -> Iterator[Path]:
        if path is None:
            LOGGER.debug("Skipping %s icon root: value is not set", label)
            return iter(())
        try:
            resolved = Path(path).resolve()
        except Exception as exc:  # pragma: no cover - defensive logging
            LOGGER.debug("Failed to resolve %s icon root %r: %s", label, path, exc)
            return iter(())
        if resolved in seen:
            LOGGER.debug("Skipping duplicate %s icon root: %s", label, resolved)
            return iter(())
        seen.add(resolved)
        LOGGER.debug("Added %s icon root: %s", label, resolved)
        return iter((resolved,))

    yield from _yield("module", package_root)
    yield from _yield("project", project_root)

    try:
        cwd = Path.cwd()
    except Exception as exc:  # pragma: no cover - defensive logging
        LOGGER.debug("Failed to resolve working directory for icons: %s", exc)
    else:
        yield from _yield("working directory", cwd)

    frozen_value = getattr(sys, "_MEIPASS", None)
    if frozen_value:
        yield from _yield("frozen bundle", frozen_value)

    with suppress(Exception):
        executable_path = Path(sys.executable).resolve()
        LOGGER.debug("Executable path for icon search: %s", executable_path)
        yield from _yield("executable directory", executable_path.parent)

    with suppress(Exception):
        launcher_path = Path(sys.argv[0]).resolve()
        LOGGER.debug("Launcher path for icon search: %s", launcher_path)
        yield from _yield("launcher directory", launcher_path.parent)


def iter_icon_candidates(
    *,
    filenames: Sequence[str],
    relative_paths: Sequence[Path] | None = None,
    module_file: Optional[Path | str] = None,
) -> Iterator[Path]:
    """Yield possible icon paths ordered from most to least specific."""

    if relative_paths is None:
        relative_paths = _ICON_RELATIVE_PATHS

    seen: set[Path] = set()
    for base_root in _iter_base_roots(module_file=module_file):
        for suffix in _ICON_PATH_SUFFIXES:
            candidate_root = (base_root / suffix).resolve()
            if candidate_root in seen:
                continue
            seen.add(candidate_root)
            LOGGER.debug("Considering icon root: %s", candidate_root)

            if not candidate_root.exists():
                LOGGER.debug("Skipping missing icon root: %s", candidate_root)
                continue

            for relative in relative_paths:
                candidate_base = (candidate_root / relative).resolve()
                if not candidate_base.exists():
                    LOGGER.debug("Skipping missing icon directory: %s", candidate_base)
                    continue
                for name in filenames:
                    candidate = (candidate_base / name).resolve()
                    LOGGER.debug("Checking icon candidate: %s", candidate)
                    yield candidate


def find_icon_path(
    *,
    filenames: Sequence[str],
    relative_paths: Sequence[Path] | None = None,
    module_file: Optional[Path | str] = None,
) -> Optional[Path]:
    """Return the first existing icon path matching *filenames* or ``None``."""

    for candidate in iter_icon_candidates(
        filenames=filenames,
        relative_paths=relative_paths,
        module_file=module_file,
    ):
        if candidate.is_file():
            LOGGER.info("Found icon at %s", candidate)
            return candidate
    LOGGER.warning("Unable to locate Talks Reducer icon; checked %s", filenames)
    return None


__all__ = ["find_icon_path", "iter_icon_candidates"]
