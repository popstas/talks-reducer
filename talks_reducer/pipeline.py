"""High-level pipeline orchestration for Talks Reducer."""

from __future__ import annotations

import math
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict

import numpy as np
from scipy.io import wavfile

from . import audio as audio_utils
from . import chunks as chunk_utils
from .ffmpeg import (
    build_extract_audio_command,
    build_video_commands,
    check_cuda_available,
    get_ffmpeg_path,
    run_timed_ffmpeg_command,
)
from .models import ProcessingOptions, ProcessingResult
from .progress import NullProgressReporter, ProgressReporter


def _input_to_output_filename(
    filename: Path, small: bool = False, use_vad: bool = False
) -> Path:
    dot_index = filename.name.rfind(".")
    suffix_parts = []

    if use_vad:
        suffix_parts.append("_vad")

    if small:
        suffix_parts.append("_small")

    if not suffix_parts:
        suffix_parts.append("")  # Default case

    suffix = "_speedup" + "".join(suffix_parts)
    new_name = (
        filename.name[:dot_index] + suffix + filename.name[dot_index:]
        if dot_index != -1
        else filename.name + suffix
    )
    return filename.with_name(new_name)


def _create_path(path: Path) -> None:
    try:
        path.mkdir()
    except OSError as exc:  # pragma: no cover - defensive logging
        raise AssertionError(
            "Creation of the directory failed. (The TEMP folder may already exist. Delete or rename it, and try again.)"
        ) from exc


def _delete_path(path: Path) -> None:
    import time
    from shutil import rmtree

    try:
        rmtree(path, ignore_errors=False)
        for i in range(5):
            if not path.exists():
                return
            time.sleep(0.01 * i)
    except OSError as exc:  # pragma: no cover - defensive logging
        print(f"Deletion of the directory {path} failed")
        print(exc)


def _extract_video_metadata(input_file: Path, frame_rate: float) -> Dict[str, float]:
    from .ffmpeg import get_ffprobe_path

    ffprobe_path = get_ffprobe_path()
    command = [
        ffprobe_path,
        "-i",
        os.fspath(input_file),
        "-hide_banner",
        "-loglevel",
        "error",
        "-select_streams",
        "v",
        "-show_entries",
        "format=duration:stream=avg_frame_rate,nb_frames",
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
        universal_newlines=True,
    )
    stdout, _ = process.communicate()

    match_frame_rate = re.search(r"frame_rate=(\d*)/(\d*)", str(stdout))
    if match_frame_rate is not None:
        frame_rate = float(match_frame_rate.group(1)) / float(match_frame_rate.group(2))

    match_duration = re.search(r"duration=([\d.]*)", str(stdout))
    original_duration = float(match_duration.group(1)) if match_duration else 0.0

    match_frames = re.search(r"nb_frames=(\d+)", str(stdout))
    frame_count = int(match_frames.group(1)) if match_frames else 0

    return {
        "frame_rate": frame_rate,
        "duration": original_duration,
        "frame_count": frame_count,
    }


def _ensure_two_dimensional(audio_data: np.ndarray) -> np.ndarray:
    if audio_data.ndim == 1:
        return audio_data[:, np.newaxis]
    return audio_data


def _prepare_output_audio(output_audio_data: np.ndarray) -> np.ndarray:
    if output_audio_data.ndim == 2 and output_audio_data.shape[1] == 1:
        return output_audio_data[:, 0]
    return output_audio_data


def speed_up_video(
    options: ProcessingOptions, reporter: ProgressReporter | None = None
) -> ProcessingResult:
    """Speed up a video by shortening silent sections while keeping sounded sections intact."""

    reporter = reporter or NullProgressReporter()

    input_path = Path(options.input_file)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    ffmpeg_path = get_ffmpeg_path()

    output_path = options.output_file or _input_to_output_filename(
        input_path, options.small, options.use_vad
    )
    output_path = Path(output_path)

    cuda_available = check_cuda_available(ffmpeg_path)

    temp_path = Path(options.temp_folder)
    if temp_path.exists():
        _delete_path(temp_path)
    _create_path(temp_path)

    metadata = _extract_video_metadata(input_path, options.frame_rate)
    frame_rate = metadata["frame_rate"]
    original_duration = metadata["duration"]
    frame_count = metadata.get("frame_count", 0)

    reporter.log("Processing on: {}".format("GPU (CUDA)" if cuda_available else "CPU"))
    if options.small:
        reporter.log(
            "Small mode enabled: 720p video, 128k audio, optimized compression"
        )

    hwaccel = (
        ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"] if cuda_available else []
    )
    audio_bitrate = "128k" if options.small else "160k"
    audio_wav = temp_path / "audio.wav"

    # Adjust sample rate for VAD if needed
    extraction_sample_rate = options.sample_rate
    if options.use_vad:
        supported_rates = [8000, 16000, 32000, 48000]
        extraction_sample_rate = min(
            supported_rates, key=lambda x: abs(x - options.sample_rate)
        )

    extract_command = build_extract_audio_command(
        os.fspath(input_path),
        os.fspath(audio_wav),
        extraction_sample_rate,
        audio_bitrate,
        hwaccel,
        ffmpeg_path=ffmpeg_path,
    )

    reporter.log("Extracting audio...")
    process_callback = getattr(reporter, "process_callback", None)
    estimated_total_frames = frame_count
    if estimated_total_frames <= 0 and original_duration > 0 and frame_rate > 0:
        estimated_total_frames = int(math.ceil(original_duration * frame_rate))

    run_timed_ffmpeg_command(
        extract_command,
        reporter=reporter,
        total=estimated_total_frames if estimated_total_frames > 0 else None,
        unit="frames",
        desc="Extracting audio:",
        process_callback=process_callback,
    )

    wav_sample_rate, audio_data = wavfile.read(os.fspath(audio_wav))
    audio_data = _ensure_two_dimensional(audio_data)
    audio_sample_count = audio_data.shape[0]
    max_audio_volume = audio_utils.get_max_volume(audio_data)

    reporter.log("\nProcessing Information:")
    reporter.log(f"- Max Audio Volume: {max_audio_volume}")

    samples_per_frame = wav_sample_rate / frame_rate
    audio_frame_count = int(math.ceil(audio_sample_count / samples_per_frame))

    if options.use_vad:
        reporter.log("Detecting speech with Silero VAD...")
        # Silero VAD requires specific sample rates: 8000 or 16000 (or multiples of 16000)
        supported_rates = [8000, 16000, 32000, 48000]
        original_sample_rate = options.sample_rate

        # Find closest supported rate
        vad_sample_rate = min(
            supported_rates, key=lambda x: abs(x - original_sample_rate)
        )

        if vad_sample_rate != original_sample_rate:
            reporter.log(
                f"VAD sample rate adjusted from {original_sample_rate}Hz to {vad_sample_rate}Hz "
                "(required by Silero VAD model)"
            )

        # Run VAD detection with timing
        import time

        from . import vad as vad_utils

        vad_start_time = time.time()
        has_loud_audio_vad = vad_utils.detect_speech_frames(
            audio_data,
            wav_sample_rate,
            audio_frame_count,
            samples_per_frame,
            options.silent_threshold,
            max_audio_volume,
        )
        vad_end_time = time.time()
        vad_duration = vad_end_time - vad_start_time

        # Also run traditional loud frame detection for comparison with timing
        traditional_start_time = time.time()
        has_loud_audio_traditional = chunk_utils.detect_loud_frames(
            audio_data,
            audio_frame_count,
            samples_per_frame,
            max_audio_volume,
            options.silent_threshold,
        )
        traditional_end_time = time.time()
        traditional_duration = traditional_end_time - traditional_start_time

        # Compare results
        vad_true_count = np.sum(has_loud_audio_vad)
        traditional_true_count = np.sum(has_loud_audio_traditional)
        agreement_count = np.sum(has_loud_audio_vad == has_loud_audio_traditional)
        total_frames = len(has_loud_audio_vad)

        comparison_msg = "VAD Comparison Results:"
        vad_msg = f"- VAD detected {vad_true_count} loud frames ({vad_true_count/total_frames*100:.1f}%) in {vad_duration:.2f}s"
        traditional_msg = f"- Traditional detected {traditional_true_count} loud frames ({traditional_true_count/total_frames*100:.1f}%) in {traditional_duration:.2f}s"
        agreement_msg = f"- Agreement: {agreement_count}/{total_frames} frames ({agreement_count/total_frames*100:.1f}%)"

        performance_msg = ""
        if vad_duration > 0 and traditional_duration > 0:
            if vad_duration < traditional_duration:
                speedup = traditional_duration / vad_duration
                performance_msg = (
                    f"- VAD is {speedup:.1f}x faster than traditional method"
                )
            elif traditional_duration < vad_duration:
                slowdown = vad_duration / traditional_duration
                performance_msg = (
                    f"- VAD is {slowdown:.1f}x slower than traditional method"
                )
            else:
                performance_msg = (
                    "- VAD and traditional method have similar performance"
                )

        # Log to both GUI and console
        messages = [comparison_msg, vad_msg, traditional_msg, agreement_msg]
        if performance_msg:
            messages.append(performance_msg)

        for msg in messages:
            reporter.log(msg)
            print(msg, file=sys.stderr)

        # Use VAD results but log if there's significant disagreement
        if (
            abs(vad_true_count - traditional_true_count) / total_frames > 0.1
        ):  # >10% difference
            warning_msg = "Warning: VAD and traditional detection differ significantly"
            reporter.log(warning_msg)
            print(warning_msg, file=sys.stderr)

        has_loud_audio = has_loud_audio_vad

    else:
        has_loud_audio = chunk_utils.detect_loud_frames(
            audio_data,
            audio_frame_count,
            samples_per_frame,
            max_audio_volume,
            options.silent_threshold,
        )

    chunks, _ = chunk_utils.build_chunks(has_loud_audio, options.frame_spreadage)

    reporter.log(f"Generated {len(chunks)} chunks")

    new_speeds = [options.silent_speed, options.sounded_speed]
    output_audio_data, updated_chunks = audio_utils.process_audio_chunks(
        audio_data,
        chunks,
        samples_per_frame,
        new_speeds,
        options.audio_fade_envelope_size,
        max_audio_volume,
    )

    audio_new_path = temp_path / "audioNew.wav"
    # Use the sample rate that was actually used for processing
    output_sample_rate = extraction_sample_rate
    wavfile.write(
        os.fspath(audio_new_path),
        output_sample_rate,
        _prepare_output_audio(output_audio_data),
    )

    expression = chunk_utils.get_tree_expression(updated_chunks)
    filter_graph_path = temp_path / "filterGraph.txt"
    with open(filter_graph_path, "w", encoding="utf-8") as filter_graph_file:
        filter_parts = []
        if options.small:
            filter_parts.append("scale=-2:720")
        filter_parts.append(f"fps=fps={frame_rate}")
        escaped_expression = expression.replace(",", "\\,")
        filter_parts.append(f"setpts={escaped_expression}")
        filter_graph_file.write(",".join(filter_parts))

    command_str, fallback_command_str, use_cuda_encoder = build_video_commands(
        os.fspath(input_path),
        os.fspath(audio_new_path),
        os.fspath(filter_graph_path),
        os.fspath(output_path),
        ffmpeg_path=ffmpeg_path,
        cuda_available=cuda_available,
        small=options.small,
    )

    output_dir = output_path.parent.resolve()
    if output_dir and not output_dir.exists():
        reporter.log(f"Creating output directory: {output_dir}")
        output_dir.mkdir(parents=True, exist_ok=True)

    reporter.log("\nExecuting FFmpeg command:")
    reporter.log(command_str)

    if not audio_new_path.exists():
        _delete_path(temp_path)
        raise FileNotFoundError("Audio intermediate file was not generated")

    if not filter_graph_path.exists():
        _delete_path(temp_path)
        raise FileNotFoundError("Filter graph file was not generated")

    try:
        run_timed_ffmpeg_command(
            command_str,
            reporter=reporter,
            total=updated_chunks[-1][3],
            unit="frames",
            desc="Generating final:",
            process_callback=process_callback,
        )
    except subprocess.CalledProcessError as exc:
        if fallback_command_str and use_cuda_encoder:
            reporter.log("CUDA encoding failed, retrying with CPU encoder...")
            run_timed_ffmpeg_command(
                fallback_command_str,
                reporter=reporter,
                total=updated_chunks[-1][3],
                unit="frames",
                desc="Generating final (fallback):",
                process_callback=process_callback,
            )
        else:
            raise
    finally:
        _delete_path(temp_path)

    output_metadata = _extract_video_metadata(output_path, frame_rate)
    output_duration = output_metadata.get("duration", 0.0)
    time_ratio = output_duration / original_duration if original_duration > 0 else None

    input_size = input_path.stat().st_size if input_path.exists() else 0
    output_size = output_path.stat().st_size if output_path.exists() else 0
    size_ratio = (output_size / input_size) if input_size > 0 else None

    return ProcessingResult(
        input_file=input_path,
        output_file=output_path,
        frame_rate=frame_rate,
        original_duration=original_duration,
        output_duration=output_duration,
        chunk_count=len(chunks),
        used_cuda=use_cuda_encoder,
        max_audio_volume=max_audio_volume,
        time_ratio=time_ratio,
        size_ratio=size_ratio,
    )
