"""Join several media files into a single input for the processing pipeline.

The GUI and the CLI can be handed more than one recording at a time. When the
user asks for a single result the parts are concatenated *before* the speed-up
pipeline runs, so silence detection spans the seams and one summary describes
the whole talk.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from .ffmpeg import get_ffmpeg_path, run_timed_ffmpeg_command
from .pipeline import ProcessingAborted, _stop_requested
from .progress import ProgressReporter

_FFMPEG_LOG_ARGS = "-hide_banner -loglevel warning -stats"


def build_concat_list(inputs: Sequence[Path | str]) -> str:
    """Return the body of an FFmpeg concat demuxer list describing *inputs*.

    Paths are made absolute and single-quoted the way the demuxer expects, with
    embedded quotes escaped so a file named ``it's a talk.mp4`` still resolves.
    """

    lines: List[str] = []
    for item in inputs:
        resolved = Path(item).resolve().as_posix()
        escaped = resolved.replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    return "\n".join(lines)


def _probe_streams(path: Path | str) -> Optional[dict]:
    """Return the video/audio stream parameters ``ffprobe`` reports for *path*.

    The result maps ``"video"`` and ``"audio"`` to comparable parameter tuples,
    or to ``None`` when the file carries no such stream. ``None`` is returned
    when the probe itself fails, which callers treat as "unknown" rather than
    as a mismatch.
    """

    from .ffmpeg import get_ffprobe_path

    command = [
        get_ffprobe_path(),
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type,codec_name,width,height,sample_rate,channels",
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
        streams = json.loads(completed.stdout).get("streams", [])
    except Exception:  # pragma: no cover - defensive probe failure
        return None

    result: dict = {"video": None, "audio": None}
    for stream in streams:
        kind = stream.get("codec_type")
        if kind == "video" and result["video"] is None:
            result["video"] = (
                stream.get("codec_name"),
                stream.get("width"),
                stream.get("height"),
            )
        elif kind == "audio" and result["audio"] is None:
            result["audio"] = (
                stream.get("codec_name"),
                stream.get("sample_rate"),
                stream.get("channels"),
            )
    return result


def _has_video_stream(path: Path | str) -> bool:
    """Return ``True`` when ``ffprobe`` finds a video stream in *path*."""

    info = _probe_streams(path)
    if info is None:
        return True
    return info["video"] is not None


def inputs_can_be_copied(inputs: Sequence[Path | str]) -> bool:
    """Return ``True`` when every input shares the same stream parameters.

    FFmpeg happily stream-copies parts that disagree about resolution: the
    result plays at whatever size each part was encoded at while the container
    advertises only the first, which the pipeline then re-encodes into a broken
    video. Copying is therefore only attempted when the parts match.
    """

    signatures = [_probe_streams(item) for item in inputs]
    if any(signature is None for signature in signatures):
        # An unavailable probe should not force a slow re-encode; the copy
        # attempt still falls back when FFmpeg rejects the inputs.
        return True
    return all(signature == signatures[0] for signature in signatures)


def build_concat_copy_command(
    list_file: Path | str,
    destination: Path | str,
    *,
    ffmpeg_path: Optional[str] = None,
) -> str:
    """Build the stream-copy concatenation command for a demuxer *list_file*."""

    ffmpeg_path = ffmpeg_path or get_ffmpeg_path()
    return " ".join(
        [
            f'"{ffmpeg_path}"',
            "-y",
            "-f concat",
            "-safe 0",
            f'-i "{list_file}"',
            "-c copy",
            f'"{destination}"',
            _FFMPEG_LOG_ARGS,
        ]
    )


def build_concat_filter_command(
    inputs: Sequence[Path | str],
    destination: Path | str,
    *,
    ffmpeg_path: Optional[str] = None,
    include_video: bool = True,
    width: Optional[int] = None,
    height: Optional[int] = None,
) -> str:
    """Build the re-encoding concatenation command used when copying fails.

    Sources that disagree about codec, resolution or frame rate cannot be
    stream-copied into one container, so the concat *filter* rebuilds them into
    a single stream. ``include_video`` is ``False`` for audio-only inputs, and
    ``width``/``height`` pin every part to the first part's frame size, since
    the concat filter rejects links whose parameters differ.
    """

    ffmpeg_path = ffmpeg_path or get_ffmpeg_path()
    destination = Path(destination)
    count = len(inputs)

    parts: List[str] = [f'"{ffmpeg_path}"', "-y"]
    for item in inputs:
        parts.append(f'-i "{item}"')

    if include_video:
        chains: List[str] = []
        labels: List[str] = []
        for index in range(count):
            video_filters = []
            if width and height:
                video_filters.append(
                    f"scale={width}:{height}:force_original_aspect_ratio=decrease"
                )
                video_filters.append(f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2")
            video_filters.append("setsar=1")
            chains.append(f"[{index}:v:0]{','.join(video_filters)}[v{index}]")
            chains.append(
                f"[{index}:a:0]aresample=async=1,aformat="
                f"sample_fmts=fltp:channel_layouts=stereo[a{index}]"
            )
            labels.append(f"[v{index}][a{index}]")
        graph = (
            ";".join(chains) + ";" + "".join(labels) + f"concat=n={count}:v=1:a=1[v][a]"
        )
        parts.extend(
            [
                f'-filter_complex "{graph}"',
                '-map "[v]"',
                '-map "[a]"',
                "-c:v libx264",
                "-crf 20",
                "-preset veryfast",
                "-c:a aac",
                "-b:a 192k",
            ]
        )
    else:
        streams = "".join(f"[{index}:a:0]" for index in range(count))
        graph = f"{streams}concat=n={count}:v=0:a=1[a]"
        audio_codec = (
            "-c:a libmp3lame -q:a 2"
            if destination.suffix.lower() == ".mp3"
            else "-c:a aac -b:a 192k"
        )
        parts.extend([f'-filter_complex "{graph}"', '-map "[a]"', audio_codec])

    parts.extend([f'"{destination}"', _FFMPEG_LOG_ARGS])
    return " ".join(parts)


def concatenate_media(
    inputs: Sequence[Path | str],
    destination: Path | str,
    *,
    ffmpeg_path: Optional[str] = None,
    reporter: Optional[ProgressReporter] = None,
    process_callback: Optional[Callable[[subprocess.Popen], None]] = None,
    runner: Callable[..., None] = run_timed_ffmpeg_command,
) -> Path:
    """Concatenate *inputs* into *destination* and return the written path.

    A stream copy is attempted first because parts recorded in one session
    usually share their encoding parameters and copying is close to instant.
    Only when FFmpeg rejects that does the slower re-encoding concat filter
    run. A stop requested by the user aborts instead of triggering the retry.
    """

    if len(inputs) < 2:
        raise ValueError("Gluing requires at least two input files.")

    destination = Path(destination)
    ffmpeg_path = ffmpeg_path or get_ffmpeg_path()
    list_file = destination.parent / f"{destination.stem}_concat.txt"
    list_file.parent.mkdir(parents=True, exist_ok=True)
    list_file.write_text(build_concat_list(inputs), encoding="utf-8")

    def _run(command: str, desc: str) -> None:
        if reporter is not None:
            reporter.log(f"Executing FFmpeg command:\n{command}")
        runner(
            command,
            reporter=reporter,
            desc=desc,
            unit="frames",
            process_callback=process_callback,
            stop_requested=(
                (lambda: _stop_requested(reporter)) if reporter is not None else None
            ),
        )

    def _reencode() -> None:
        first = _probe_streams(inputs[0]) or {}
        video = first.get("video")
        _run(
            build_concat_filter_command(
                inputs,
                destination,
                ffmpeg_path=ffmpeg_path,
                include_video=_has_video_stream(inputs[0]),
                width=video[1] if video else None,
                height=video[2] if video else None,
            ),
            "Gluing (re-encode):",
        )

    try:
        if not inputs_can_be_copied(inputs):
            if reporter is not None:
                reporter.log(
                    "The parts use different stream parameters, "
                    "re-encoding them into one file..."
                )
            _reencode()
        else:
            try:
                _run(
                    build_concat_copy_command(
                        list_file, destination, ffmpeg_path=ffmpeg_path
                    ),
                    "Gluing:",
                )
            except subprocess.CalledProcessError:
                if _stop_requested(reporter):
                    raise ProcessingAborted("Processing aborted by user request.")
                if reporter is not None:
                    reporter.log(
                        "Copying the parts failed, re-encoding them into one file..."
                    )
                _reencode()
    finally:
        list_file.unlink(missing_ok=True)

    return destination


def prepare_glued_input(
    inputs: Sequence[Path | str],
    *,
    temp_folder: Path | str,
    ffmpeg_path: Optional[str] = None,
    reporter: Optional[ProgressReporter] = None,
    process_callback: Optional[Callable[[subprocess.Popen], None]] = None,
    runner: Callable[..., None] = run_timed_ffmpeg_command,
) -> Tuple[Path, Path]:
    """Glue *inputs* inside *temp_folder* and return ``(glued_file, temp_dir)``.

    The glued file keeps the first part's name so the pipeline derives the same
    output name it would have produced for that part alone. The returned
    directory is the caller's to delete once processing finishes.
    """

    if len(inputs) < 2:
        raise ValueError("Gluing requires at least two input files.")

    temp_folder = Path(temp_folder)
    temp_folder.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="glue_", dir=str(temp_folder)))
    destination = temp_dir / Path(inputs[0]).name

    if reporter is not None:
        names = ", ".join(Path(item).name for item in inputs)
        reporter.log(f"Gluing {len(inputs)} files into one video: {names}")

    concatenate_media(
        inputs,
        destination,
        ffmpeg_path=ffmpeg_path,
        reporter=reporter,
        process_callback=process_callback,
        runner=runner,
    )
    return destination, temp_dir
