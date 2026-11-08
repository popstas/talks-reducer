"""End-to-end check that remove ranges really drop frames and audio.

Runs the real pipeline on a generated clip, so it is skipped when FFmpeg is
not available. It verifies the assumption the feature rests on: frames whose
``setpts`` timestamps collapse are dropped, not muxed as duplicates.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from talks_reducer.models import ProcessingOptions
from talks_reducer.pipeline import speed_up_video
from talks_reducer.subprocess_utils import hidden_subprocess_kwargs

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="needs ffmpeg and ffprobe on PATH",
)


def _make_clip(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=160x120:rate=30:duration=10",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=10",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
        **hidden_subprocess_kwargs(),
    )


def _probe(path: Path) -> tuple[float, int]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "format=duration:stream=nb_read_frames",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        **hidden_subprocess_kwargs(),
    )
    data = json.loads(result.stdout)
    return float(data["format"]["duration"]), int(data["streams"][0]["nb_read_frames"])


@pytest.mark.parametrize("max_frame_rate, expected_frames", [(None, 240), (15.0, 120)])
def test_remove_range_shortens_output(
    tmp_path: Path, max_frame_rate: float | None, expected_frames: int
) -> None:
    source = tmp_path / "clip.mp4"
    _make_clip(source)
    output = tmp_path / "out.mp4"

    speed_up_video(
        ProcessingOptions(
            input_file=source,
            output_file=output,
            temp_folder=tmp_path / "temp",
            silent_speed=1.0,
            sounded_speed=1.0,
            max_frame_rate=max_frame_rate,
            remove_ranges=((3.0, 5.0),),
            prefer_global_ffmpeg=True,
        )
    )

    duration, frames = _probe(output)
    print(f"MEASURED cap={max_frame_rate} duration={duration} frames={frames}")
    assert duration == pytest.approx(8.0, abs=0.15)
    assert abs(frames - expected_frames) <= 2
