"""Tests for detecting and preserving 360° (spherical) video metadata."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from talks_reducer import spherical

_STEREO = {"side_data_type": "Stereo 3D", "type": "2D", "inverted": 0}
_SPHERICAL = {
    "side_data_type": "Spherical Mapping",
    "projection": "equirectangular",
    "yaw": 0,
    "pitch": 0,
    "roll": 0,
}


def _payload(*side_data):
    """Build ffprobe ``-of json`` output for one video stream."""

    stream = {"side_data_list": list(side_data)} if side_data else {}
    return json.dumps({"streams": [stream]})


def test_parse_detects_equirectangular_with_stereo() -> None:
    info = spherical.parse_spherical_side_data(_payload(_STEREO, _SPHERICAL))

    assert info == spherical.SphericalInfo(projection="equirectangular", stereo="2D")


def test_parse_without_stereo_entry() -> None:
    info = spherical.parse_spherical_side_data(_payload(_SPHERICAL))

    assert info == spherical.SphericalInfo(projection="equirectangular", stereo=None)


def test_parse_returns_none_for_flat_video() -> None:
    assert spherical.parse_spherical_side_data(_payload()) is None
    assert spherical.parse_spherical_side_data(_payload(_STEREO)) is None


def test_parse_returns_none_for_garbage() -> None:
    assert spherical.parse_spherical_side_data("not json") is None
    assert spherical.parse_spherical_side_data(json.dumps({"streams": []})) is None


def test_probe_spherical_runs_ffprobe(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(stdout=_payload(_SPHERICAL))

    monkeypatch.setattr(spherical, "_ffprobe_path", lambda: "ffprobe")
    monkeypatch.setattr(spherical.subprocess, "run", fake_run)

    info = spherical.probe_spherical("clip.mp4")

    assert info == spherical.SphericalInfo(projection="equirectangular")
    assert calls[0][0] == "ffprobe"
    assert "stream_side_data" in " ".join(calls[0])
    assert calls[0][-1] == "clip.mp4"


def test_probe_spherical_swallows_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_run(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(spherical, "_ffprobe_path", lambda: "ffprobe")
    monkeypatch.setattr(spherical.subprocess, "run", failing_run)

    assert spherical.probe_spherical("missing.mp4") is None


@pytest.mark.parametrize(
    ("width", "height", "target", "expected"),
    [
        (7680, 3840, 720, "v360=e:e:w=1440:h=720"),
        (7680, 3840, 480, "v360=e:e:w=960:h=480"),
        (5760, 2880, 720, "v360=e:e:w=1440:h=720"),
        # Non-2:1 source: width follows the source ratio, rounded to even.
        (1000, 562, 480, "v360=e:e:w=854:h=480"),
    ],
)
def test_spherical_scale_filter_keeps_aspect_and_even_width(
    width: int, height: int, target: int, expected: str
) -> None:
    assert spherical.spherical_scale_filter(width, height, target) == expected
