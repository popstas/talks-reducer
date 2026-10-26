"""Detect and preserve 360° (spherical) video metadata.

360° cameras tag the video stream with *Spherical Mapping* and *Stereo 3D*
side data (MP4 ``sv3d``/``st3d`` boxes). FFmpeg's MOV muxer only writes those
boxes under ``-strict unofficial``, and the ``scale`` filter drops Spherical
Mapping because it depends on the frame size. ``v360`` rescales an
equirectangular frame while keeping it, so the pipeline swaps it in.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

EQUIRECTANGULAR = "equirectangular"
PRESERVE_SPHERICAL_ARGS = "-strict unofficial"


@dataclass(frozen=True)
class SphericalInfo:
    """360° metadata found on a source's first video stream."""

    projection: str
    stereo: Optional[str] = None


def _ffprobe_path() -> str:
    """Return the ffprobe binary the rest of the app uses."""

    from .ffmpeg import get_ffprobe_path

    return get_ffprobe_path()


def parse_spherical_side_data(payload: str) -> Optional[SphericalInfo]:
    """Return the spherical metadata in ffprobe JSON *payload*, if any.

    *payload* is the output of ``ffprobe -show_entries stream_side_data -of
    json`` for one video stream. ``None`` means the stream is a flat video or
    the payload could not be read.
    """

    try:
        streams = json.loads(payload).get("streams") or []
    except (ValueError, AttributeError):
        return None
    if not streams:
        return None

    projection: Optional[str] = None
    stereo: Optional[str] = None
    for entry in streams[0].get("side_data_list") or []:
        kind = entry.get("side_data_type")
        if kind == "Spherical Mapping":
            projection = entry.get("projection") or "unknown"
        elif kind == "Stereo 3D":
            stereo = entry.get("type")

    if projection is None:
        return None
    return SphericalInfo(projection=projection, stereo=stereo)


def probe_spherical(path: Path | str) -> Optional[SphericalInfo]:
    """Probe *path* for 360° metadata; never raises.

    Any probe failure (missing ffprobe, unreadable file) returns ``None`` so a
    flat-video run is never broken by this check.
    """

    command = [
        _ffprobe_path(),
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream_side_data=side_data_type,projection,type",
        "-of",
        "json",
        str(path),
    ]
    creationflags = 0x08000000 if sys.platform == "win32" else 0
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            creationflags=creationflags,
        )
    except Exception:
        return None
    return parse_spherical_side_data(completed.stdout or "")


def spherical_scale_filter(
    source_width: int, source_height: int, target_height: int
) -> str:
    """Return a ``v360`` filter rescaling an equirectangular frame to *target_height*.

    The width follows the source aspect ratio and is rounded to an even number,
    matching what ``scale=-2:H`` would produce for a flat video.
    """

    width = int(round(source_width * target_height / source_height / 2.0)) * 2
    return f"v360=e:e:w={width}:h={target_height}"


__all__ = [
    "EQUIRECTANGULAR",
    "PRESERVE_SPHERICAL_ARGS",
    "SphericalInfo",
    "parse_spherical_side_data",
    "probe_spherical",
    "spherical_scale_filter",
]
