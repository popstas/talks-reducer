"""Progress parsing and log handling helpers for the Talks Reducer GUI."""

from __future__ import annotations

"""Progress parsing and log handling helpers for the Talks Reducer GUI."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import List, Optional, Tuple, TYPE_CHECKING

from ..pipeline import _input_to_output_filename

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from .app import TalksReducerGUI


def default_remote_destination(
    input_file: Path,
    *,
    small: bool,
    small_480: bool = False,
    add_codec_suffix: bool = False,
    video_codec: str = "h264",
    silent_speed: float | None = None,
    sounded_speed: float | None = None,
) -> Path:
    """Return the default remote output path for *input_file*."""

    normalized_codec = str(video_codec or "h264").strip().lower()
    target_height = 480 if small_480 else None

    return _input_to_output_filename(
        input_file,
        small,
        target_height,
        video_codec=normalized_codec,
        add_codec_suffix=add_codec_suffix,
        silent_speed=silent_speed,
        sounded_speed=sounded_speed,
    )


def parse_ratios_from_summary(summary: str) -> Tuple[Optional[float], Optional[float]]:
    """Extract time and size ratios from a Markdown *summary* string."""

    time_ratio: Optional[float] = None
    size_ratio: Optional[float] = None

    for line in summary.splitlines():
        if "**Duration:**" in line:
            match = re.search(r"—\s*([0-9]+(?:\.[0-9]+)?)% of the original", line)
            if match:
                try:
                    time_ratio = float(match.group(1)) / 100
                except ValueError:
                    time_ratio = None
        elif "**Size:**" in line:
            match = re.search(r"\*\*Size:\*\*\s*([0-9]+(?:\.[0-9]+)?)%", line)
            if match:
                try:
                    size_ratio = float(match.group(1)) / 100
                except ValueError:
                    size_ratio = None

    return time_ratio, size_ratio


def parse_source_duration_seconds(message: str) -> tuple[bool, Optional[float]]:
    """Return whether *message* includes source duration metadata."""

    metadata_match = re.search(
        r"source metadata: duration:\s*([\d.]+)s",
        message,
        re.IGNORECASE,
    )
    if not metadata_match:
        return False, None

    try:
        return True, float(metadata_match.group(1))
    except ValueError:
        return True, None


def parse_encode_total_frames(message: str) -> tuple[bool, Optional[int]]:
    """Extract final encode frame totals from *message* when present."""

    frame_total_match = re.search(
        r"Final encode target frames(?: \(fallback\))?:\s*(\d+)", message
    )
    if not frame_total_match:
        return False, None

    try:
        return True, int(frame_total_match.group(1))
    except ValueError:
        return True, None


def is_encode_total_frames_unknown(normalized_message: str) -> bool:
    """Return ``True`` if *normalized_message* marks encode frame totals unknown."""

    return (
        "final encode target frames" in normalized_message
        and "unknown" in normalized_message
    )


def parse_current_frame(message: str) -> tuple[bool, Optional[int]]:
    """Extract the current encode frame from *message* when available."""

    frame_match = re.search(r"frame=\s*(\d+)", message)
    if not frame_match:
        return False, None

    try:
        return True, int(frame_match.group(1))
    except ValueError:
        return True, None


def parse_encode_target_duration(message: str) -> tuple[bool, Optional[float]]:
    """Extract encode target duration from *message* if reported."""

    encode_duration_match = re.search(
        r"Final encode target duration(?: \(fallback\))?:\s*([\d.]+)s",
        message,
    )
    if not encode_duration_match:
        return False, None

    try:
        return True, float(encode_duration_match.group(1))
    except ValueError:
        return True, None


def is_encode_target_duration_unknown(normalized_message: str) -> bool:
    """Return ``True`` if encode target duration is reported as unknown."""

    return (
        "final encode target duration" in normalized_message
        and "unknown" in normalized_message
    )


def parse_video_duration_seconds(message: str) -> tuple[bool, Optional[float]]:
    """Parse the input video duration from *message* when FFmpeg prints it."""

    duration_match = re.search(r"Duration:\s*(\d{2}):(\d{2}):(\d{2}\.\d+)", message)
    if not duration_match:
        return False, None

    try:
        hours = int(duration_match.group(1))
        minutes = int(duration_match.group(2))
        seconds = float(duration_match.group(3))
    except ValueError:
        return True, None

    total_seconds = hours * 3600 + minutes * 60 + seconds
    return True, total_seconds


def parse_ffmpeg_progress(message: str) -> tuple[bool, Optional[tuple[int, str]]]:
    """Parse FFmpeg progress information from *message* if available."""

    time_match = re.search(r"time=(\d{2}):(\d{2}):(\d{2})\.\d+", message)
    speed_match = re.search(r"speed=\s*([\d.]+)x", message)

    if not (time_match and speed_match):
        return False, None

    try:
        hours = int(time_match.group(1))
        minutes = int(time_match.group(2))
        seconds = int(time_match.group(3))
    except ValueError:
        return True, None

    current_seconds = hours * 3600 + minutes * 60 + seconds
    speed_str = speed_match.group(1)
    return True, (current_seconds, speed_str)


class SummaryManager:
    """Parse log messages and keep the GUI status and log text updated."""

    def __init__(self, gui: "TalksReducerGUI") -> None:
        self.gui = gui

    def append_log(self, message: str) -> None:
        self.update_status_from_message(message)

        def updater() -> None:
            self.gui.log_text.configure(state=self.gui.tk.NORMAL)
            self.gui.log_text.insert(self.gui.tk.END, message + "\n")
            self.gui.log_text.see(self.gui.tk.END)
            self.gui.log_text.configure(state=self.gui.tk.DISABLED)

        self.gui.log_text.after(0, updater)

    def update_status_from_message(self, message: str) -> None:
        normalized = message.strip().lower()

        metadata_found, source_duration = parse_source_duration_seconds(message)
        if metadata_found:
            self.gui._source_duration_seconds = source_duration

        if self.handle_status_transitions(normalized):
            return

        frame_total_found, frame_total = parse_encode_total_frames(message)
        if frame_total_found:
            self.gui._encode_total_frames = frame_total
            return

        if is_encode_total_frames_unknown(normalized):
            self.gui._encode_total_frames = None
            return

        frame_found, current_frame = parse_current_frame(message)
        if frame_found:
            if current_frame is None:
                return

            if self.gui._encode_current_frame == current_frame:
                return

            self.gui._encode_current_frame = current_frame
            if self.gui._encode_total_frames and self.gui._encode_total_frames > 0:
                self.gui._complete_audio_phase()
                frame_ratio = min(current_frame / self.gui._encode_total_frames, 1.0)
                progress_target = self.gui.AUDIO_PROGRESS_WEIGHT + frame_ratio * (
                    100.0 - self.gui.AUDIO_PROGRESS_WEIGHT
                )
                current_value = float(self.gui.progress_var.get())
                percentage = min(100.0, max(current_value, progress_target))
                self.gui._set_progress(percentage)
            else:
                self.gui._complete_audio_phase()
                self.gui._set_status("processing", f"{current_frame} frames encoded")

        duration_found, encode_duration = parse_encode_target_duration(message)
        if duration_found:
            self.gui._encode_target_duration_seconds = encode_duration

        if is_encode_target_duration_unknown(normalized):
            self.gui._encode_target_duration_seconds = None

        video_duration_found, video_duration = parse_video_duration_seconds(message)
        if video_duration_found and video_duration is not None:
            self.gui._video_duration_seconds = video_duration

        progress_found, progress_info = parse_ffmpeg_progress(message)
        if progress_found and progress_info is not None:
            current_seconds, speed_str = progress_info
            time_str = self.format_progress_time(current_seconds)

            self.gui._last_progress_seconds = current_seconds

            total_seconds = (
                self.gui._encode_target_duration_seconds
                or self.gui._video_duration_seconds
            )
            if total_seconds:
                total_str = self.format_progress_time(total_seconds)
                time_display = f"{time_str} / {total_str}"
            else:
                time_display = time_str

            status_msg = f"{time_display}, {speed_str}x"

            if (
                (
                    not self.gui._encode_total_frames
                    or self.gui._encode_total_frames <= 0
                    or self.gui._encode_current_frame is None
                )
                and total_seconds
                and total_seconds > 0
            ):
                self.gui._complete_audio_phase()
                time_ratio = min(current_seconds / total_seconds, 1.0)
                progress_target = self.gui.AUDIO_PROGRESS_WEIGHT + time_ratio * (
                    100.0 - self.gui.AUDIO_PROGRESS_WEIGHT
                )
                current_value = float(self.gui.progress_var.get())
                percentage = min(100.0, max(current_value, progress_target))
                self.gui._set_progress(percentage)

            self.gui._set_status("processing", status_msg)

    def handle_status_transitions(self, normalized_message: str) -> bool:
        """Handle high-level status transitions for *normalized_message*."""

        if "all jobs finished successfully" in normalized_message:
            status_components: List[str] = []
            if self.gui._run_start_time is not None:
                finish_time = time.monotonic()
                runtime_seconds = max(0.0, finish_time - self.gui._run_start_time)
                duration_str = self.format_progress_time(runtime_seconds)
                status_components.append(f"{duration_str}")
            else:
                finished_seconds = next(
                    (
                        value
                        for value in (
                            self.gui._last_progress_seconds,
                            self.gui._encode_target_duration_seconds,
                            self.gui._video_duration_seconds,
                        )
                        if value is not None
                    ),
                    None,
                )

                if finished_seconds is not None:
                    duration_str = self.format_progress_time(finished_seconds)
                    status_components.append(f"{duration_str}")
                else:
                    status_components.append("Finished")

            if (
                self.gui._last_time_ratio is not None
                and self.gui._last_size_ratio is not None
            ):
                status_components.append(
                    f"time: {self.gui._last_time_ratio:.0%}, size: {self.gui._last_size_ratio:.0%}"
                )

            status_msg = ", ".join(status_components)

            self.gui._reset_audio_progress_state(clear_source=True)
            self.gui._set_status("success", status_msg)
            self.gui._set_progress(100)
            self.gui._run_start_time = None
            self.gui._video_duration_seconds = None
            self.gui._encode_target_duration_seconds = None
            self.gui._encode_total_frames = None
            self.gui._encode_current_frame = None
            self.gui._last_progress_seconds = None
            return True

        if normalized_message.startswith("extracting audio"):
            self.gui._reset_audio_progress_state(clear_source=False)
            self.gui._set_status("processing", "Extracting audio...")
            self.gui._set_progress(0)
            self.gui._video_duration_seconds = None
            self.gui._encode_target_duration_seconds = None
            self.gui._encode_total_frames = None
            self.gui._encode_current_frame = None
            self.gui._last_progress_seconds = None
            self.gui._start_audio_progress()
            return False

        if normalized_message.startswith("uploading"):
            self.gui._set_status("processing", "Uploading...")
            return False

        if normalized_message.startswith("starting processing"):
            self.gui._reset_audio_progress_state(clear_source=True)
            self.gui._set_status("processing", "Processing")
            self.gui._set_progress(0)
            self.gui._video_duration_seconds = None
            self.gui._encode_target_duration_seconds = None
            self.gui._encode_total_frames = None
            self.gui._encode_current_frame = None
            self.gui._last_progress_seconds = None
            return False

        if normalized_message.startswith("processing"):
            is_new_job = bool(re.match(r"processing \d+/\d+:", normalized_message))
            should_reset = self.gui._status_state.lower() != "processing" or is_new_job
            if should_reset:
                self.gui._set_progress(0)
                self.gui._video_duration_seconds = None
                self.gui._encode_target_duration_seconds = None
                self.gui._encode_total_frames = None
                self.gui._encode_current_frame = None
                self.gui._last_progress_seconds = None
            if is_new_job:
                self.gui._reset_audio_progress_state(clear_source=True)
            self.gui._set_status("processing", "Processing")
            return False

        return False

    def format_progress_time(self, total_seconds: float | int | None) -> str:
        try:
            rounded_seconds = max(0, int(round(total_seconds)))
        except (TypeError, ValueError):
            return "0:00"

        hours, remainder = divmod(rounded_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"

        total_minutes = rounded_seconds // 60
        return f"{total_minutes}:{seconds:02d}"
