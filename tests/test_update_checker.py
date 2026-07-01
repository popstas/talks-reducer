"""Unit tests for the platform-aware update checker helpers."""

from __future__ import annotations

import sys
from contextlib import contextmanager

import pytest

from talks_reducer.gui import update_checker


def test_is_macos_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    assert update_checker.is_macos() is True
    assert update_checker.is_windows() is False


def test_is_macos_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert update_checker.is_macos() is False


@pytest.mark.parametrize(
    "platform, expected",
    [("win32", True), ("darwin", True), ("linux", False), ("freebsd", False)],
)
def test_is_update_check_supported(
    monkeypatch: pytest.MonkeyPatch, platform: str, expected: bool
) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    assert update_checker.is_update_check_supported() is expected


def test_get_macos_app_url() -> None:
    assert update_checker.get_macos_app_url("9.9.9") == (
        "https://github.com/popstas/talks-reducer/releases/download/"
        "v9.9.9/talks-reducer-macos.app-9.9.9.zip"
    )


def test_get_brew_upgrade_command() -> None:
    assert update_checker.get_brew_upgrade_command() == (
        "brew upgrade --cask talks-reducer"
    )


@pytest.mark.parametrize(
    "current, latest, expected",
    [
        ("0.9.4", "0.9.5", True),  # newer
        ("0.9.5", "0.9.4", False),  # older
        ("0.9.5", "0.9.5", False),  # equal
        ("0.9", "0.9.1", True),  # padded shorter current
        ("0.9.1", "0.9", False),  # padded shorter latest
        ("1.0", "1.0.0", False),  # padded equal
        ("abc", "def", True),  # malformed falls back to string compare
    ],
)
def test_compare_versions(current: str, latest: str, expected: bool) -> None:
    assert update_checker.compare_versions(current, latest) is expected


def test_build_update_message_macos() -> None:
    presentation = update_checker.build_update_message("9.9.9", platform="darwin")

    # Assert the full documented string so a spacing/wording regression in the
    # concatenated f-string is caught (mirrors the Windows test's rigor).
    assert presentation.status_text == (
        "New version 9.9.9 is available! "
        "Update with: brew upgrade --cask talks-reducer"
    )
    assert presentation.button_text == "Check updates"
    assert presentation.enable_download is False
    # Only the releases page link; no installer/portable download on macOS.
    assert presentation.links == [
        ("Releases page", update_checker.get_releases_page_url())
    ]


def test_build_update_message_windows() -> None:
    presentation = update_checker.build_update_message("9.9.9", platform="win32")

    assert presentation.status_text == "New version 9.9.9 is available!"
    assert "brew" not in presentation.status_text
    assert presentation.button_text == "Download 9.9.9"
    assert presentation.enable_download is True
    assert presentation.links == [
        ("Releases page", update_checker.get_releases_page_url()),
    ]


def test_build_update_message_defaults_to_current_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    presentation = update_checker.build_update_message("1.2.3")
    assert presentation.enable_download is False
    assert "brew upgrade --cask talks-reducer" in presentation.status_text


class _FakeResponse:
    """Minimal context-manager response mimicking urllib's urlopen result."""

    def __init__(self, final_url: str, body: bytes = b"") -> None:
        self._final_url = final_url
        self._body = body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def geturl(self) -> str:
        return self._final_url

    def read(self) -> bytes:
        return self._body


def test_fetch_latest_version_on_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")

    def fake_urlopen(req, timeout=10):  # noqa: ANN001
        return _FakeResponse(
            "https://github.com/popstas/talks-reducer/releases/tag/v9.9.9"
        )

    monkeypatch.setattr(update_checker.urllib.request, "urlopen", fake_urlopen)

    version, error = update_checker.fetch_latest_version()
    assert version == "9.9.9"
    assert error is None


def test_fetch_latest_version_unsupported_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")

    version, error = update_checker.fetch_latest_version()
    assert version is None
    assert error == "Update checking is only available on Windows and macOS"
