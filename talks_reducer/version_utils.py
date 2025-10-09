"""Utilities for retrieving the Talks Reducer version across environments."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as metadata_version

try:  # pragma: no cover - defensive fallback when metadata module missing
    from .__about__ import __version__ as _about_version
except Exception:  # pragma: no cover - runtime fallback in frozen apps
    _about_version = ""


def resolve_version(package_name: str = "talks-reducer") -> str:
    """Return the package version, preferring bundled metadata when available."""

    if _about_version:
        return _about_version

    try:
        return metadata_version(package_name)
    except (PackageNotFoundError, Exception):
        return "unknown"
