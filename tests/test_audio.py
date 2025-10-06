"""Tests for the audio helper utilities."""

from __future__ import annotations

import types

from talks_reducer import audio


def _make_completed_process(stdout: str = "", stderr: str = "", returncode: int = 0):
    """Create a minimal object emulating :class:`subprocess.CompletedProcess`."""

    completed = types.SimpleNamespace()
    completed.stdout = stdout
    completed.stderr = stderr
    completed.returncode = returncode
    return completed


def test_is_valid_input_file_accepts_warnings(monkeypatch):
    """A warning written to stderr should not invalidate a valid audio file."""

    monkeypatch.setattr(audio, "get_ffprobe_path", lambda: "ffprobe")

    def fake_run(*args, **kwargs):
        return _make_completed_process(
            stdout="[STREAM]\ncodec_type=audio\n[/STREAM]\n",
            stderr="Configuration warning",
            returncode=0,
        )

    monkeypatch.setattr(audio.subprocess, "run", fake_run)

    assert audio.is_valid_input_file("example.mp4") is True


def test_is_valid_input_file_requires_audio_stream(monkeypatch):
    """Return ``False`` when ffprobe completes but finds no audio stream."""

    monkeypatch.setattr(audio, "get_ffprobe_path", lambda: "ffprobe")

    def fake_run(*args, **kwargs):
        return _make_completed_process(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(audio.subprocess, "run", fake_run)

    assert audio.is_valid_input_file("silent.mp4") is False
