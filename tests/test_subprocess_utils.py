"""Tests for the console-hiding subprocess helper."""

from __future__ import annotations

import sys

import pytest

from talks_reducer import subprocess_utils


def test_hidden_subprocess_kwargs_sets_create_no_window_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")

    assert subprocess_utils.hidden_subprocess_kwargs() == {"creationflags": 0x08000000}


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_hidden_subprocess_kwargs_is_empty_elsewhere(
    monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    monkeypatch.setattr(sys, "platform", platform)

    assert subprocess_utils.hidden_subprocess_kwargs() == {}


def test_hidden_subprocess_kwargs_returns_a_fresh_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Callers may mutate the result; that must not leak into the next call."""

    monkeypatch.setattr(sys, "platform", "win32")
    first = subprocess_utils.hidden_subprocess_kwargs()
    first["creationflags"] = 0

    assert subprocess_utils.hidden_subprocess_kwargs() == {"creationflags": 0x08000000}
