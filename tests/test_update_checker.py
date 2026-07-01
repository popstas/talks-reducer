"""Tests for the cross-platform GitHub release update checker."""

from __future__ import annotations

import ssl
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from talks_reducer.gui import update_checker


class _FakeResponse:
    def __init__(self, final_url: str, body: str = "") -> None:
        self._final_url = final_url
        self._body = body

    def geturl(self) -> str:
        return self._final_url

    def read(self) -> bytes:
        return self._body.encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


def test_build_ssl_context_uses_certifi(monkeypatch):
    """The SSL context should be seeded from certifi's CA bundle when present."""

    captured: dict[str, object] = {}

    def fake_create_default_context(*, cafile=None):
        captured["cafile"] = cafile
        return "context-sentinel"

    monkeypatch.setattr(ssl, "create_default_context", fake_create_default_context)

    fake_certifi = SimpleNamespace(where=lambda: "/path/to/cacert.pem")
    monkeypatch.setitem(__import__("sys").modules, "certifi", fake_certifi)

    context = update_checker._build_ssl_context()

    assert context == "context-sentinel"
    assert captured["cafile"] == "/path/to/cacert.pem"


def test_fetch_latest_version_is_cross_platform(monkeypatch):
    """Fetching no longer refuses to run on non-Windows platforms."""

    seen: dict[str, object] = {}

    def fake_urlopen(request, timeout=None, context=None):
        seen["context"] = context
        return _FakeResponse(
            "https://github.com/popstas/talks-reducer/releases/tag/v1.2.3"
        )

    monkeypatch.setattr(update_checker, "is_windows", lambda: False)
    monkeypatch.setattr(update_checker.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(update_checker, "_build_ssl_context", lambda: "ctx")

    version, error = update_checker.fetch_latest_version()

    assert version == "1.2.3"
    assert error is None
    # The certifi-backed context must be forwarded to urlopen.
    assert seen["context"] == "ctx"


def test_fetch_latest_version_reports_network_errors(monkeypatch):
    """Network failures surface as a formatted error string, not an exception."""

    def fake_urlopen(request, timeout=None, context=None):
        raise update_checker.urllib.error.URLError("boom")

    monkeypatch.setattr(update_checker.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(update_checker, "_build_ssl_context", lambda: None)

    version, error = update_checker.fetch_latest_version()

    assert version is None
    assert error is not None
    assert "Network error" in error
