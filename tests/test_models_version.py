"""Tests covering models defaults and version resolution helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from talks_reducer import models, version_utils


def test_default_temp_folder_on_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    """macOS should place the temporary folder under Application Support."""

    fake_home = Path("/Users/tester")
    monkeypatch.setattr(models.sys, "platform", "darwin")
    monkeypatch.setattr(models.Path, "home", lambda: fake_home)

    result = models.default_temp_folder()

    expected = (
        fake_home
        / "Library"
        / "Application Support"
        / "talks-reducer"
        / "talks-reducer-temp"
    )
    assert result == expected


def test_default_temp_folder_on_windows_with_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Windows should prioritise LOCALAPPDATA before APPDATA when available."""

    monkeypatch.setattr(models.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\\Temp\\Local")
    monkeypatch.setenv("APPDATA", r"C:\\Temp\\Roaming")

    result = models.default_temp_folder()

    expected = Path(r"C:\\Temp\\Local") / "talks-reducer-temp"
    assert result == expected


def test_default_temp_folder_on_windows_without_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Windows should fall back to the user's local AppData when env vars missing."""

    fake_home = Path(r"C:\\Users\\tester")
    monkeypatch.setattr(models.sys, "platform", "win32")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setattr(models.Path, "home", lambda: fake_home)

    result = models.default_temp_folder()

    expected = fake_home / "AppData" / "Local" / "talks-reducer" / "talks-reducer-temp"
    assert result == expected


def test_default_temp_folder_on_other_system(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-macOS/Windows platforms should honour XDG_RUNTIME_DIR when present."""

    monkeypatch.setattr(models.sys, "platform", "linux")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")

    result = models.default_temp_folder()

    expected = Path("/run/user/1000") / "talks-reducer" / "talks-reducer-temp"
    assert result == expected


def test_default_temp_folder_on_other_system_without_xdg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-macOS/Windows platforms should fall back to the system temp directory."""

    monkeypatch.setattr(models.sys, "platform", "linux")
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setattr(models.tempfile, "gettempdir", lambda: "/var/tmp")

    result = models.default_temp_folder()

    expected = Path("/var/tmp") / "talks-reducer" / "talks-reducer-temp"
    assert result == expected


def test_processing_options_temp_folder_defaults() -> None:
    """ProcessingOptions should use default_temp_folder unless overridden."""

    expected = models.default_temp_folder()

    options = models.ProcessingOptions(input_file=Path("input.mp4"))

    assert options.temp_folder == expected

    custom_path = Path("/override/temp")
    overridden = models.ProcessingOptions(
        input_file=Path("input.mp4"),
        temp_folder=custom_path,
    )

    assert overridden.temp_folder == custom_path


def test_resolve_version_prefers_about(monkeypatch: pytest.MonkeyPatch) -> None:
    """resolve_version should return the bundled __about__ version when present."""

    monkeypatch.setattr(version_utils, "_about_version", "1.2.3")

    def fail_metadata(_name: str) -> str:
        raise AssertionError(
            "metadata_version should not be called when __about__ present"
        )

    monkeypatch.setattr(version_utils, "metadata_version", fail_metadata)

    assert version_utils.resolve_version() == "1.2.3"


def test_resolve_version_falls_back_to_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When __about__ is empty the metadata version should be used."""

    monkeypatch.setattr(version_utils, "_about_version", "")
    monkeypatch.setattr(version_utils, "metadata_version", lambda name: f"meta:{name}")

    assert version_utils.resolve_version("pkg") == "meta:pkg"


def test_resolve_version_handles_missing_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any metadata lookup failure should return "unknown"."""

    monkeypatch.setattr(version_utils, "_about_version", "")

    class DummyError(version_utils.PackageNotFoundError):
        pass

    def raise_missing(_name: str) -> str:
        raise DummyError("missing")

    monkeypatch.setattr(version_utils, "metadata_version", raise_missing)

    assert version_utils.resolve_version() == "unknown"
