"""Tests for parsing ratios from GUI remote summaries."""

from talks_reducer.gui.app import _parse_ratios_from_summary


def test_parse_ratios_from_summary_with_percentages() -> None:
    summary = """
**Duration:** 30s -> 15s (50%)
**Size:** 4.0M -> 1.0M (25%)
**Input:** `video.mp4`
**Output:** `video_processed.mp4`
**Chunks merged:** 10
**Encoder:** CUDA
""".strip()

    time_ratio, size_ratio = _parse_ratios_from_summary(summary)

    assert time_ratio == 0.5
    assert size_ratio == 0.25


def test_parse_ratios_from_summary_missing_values() -> None:
    summary = """
**Input:** `video.mp4`
**Output:** `video_processed.mp4`
**Chunks merged:** 10
**Encoder:** CPU
""".strip()

    time_ratio, size_ratio = _parse_ratios_from_summary(summary)

    assert time_ratio is None
    assert size_ratio is None


def test_parse_ratios_from_summary_integer_percentages() -> None:
    summary = """
**Duration:** 60s -> 45s (75%)
**Size:** 5.0M -> 2.0M (40%)
**Input:** `video.mp4`
**Output:** `video_processed.mp4`
**Chunks merged:** 12
**Encoder:** CPU
""".strip()

    time_ratio, size_ratio = _parse_ratios_from_summary(summary)

    assert time_ratio == 0.75
    assert size_ratio == 0.4


def test_parse_ratios_from_new_server_summary(tmp_path) -> None:
    import os

    import talks_reducer.server as server
    from talks_reducer.gui.summaries import parse_ratios_from_summary
    from talks_reducer.models import ProcessingResult

    input_file = tmp_path / "in.mp4"
    output_file = tmp_path / "out.mp4"
    input_file.write_bytes(b"")
    output_file.write_bytes(b"")
    os.truncate(input_file, 500 * 1024 * 1024)
    os.truncate(output_file, 250 * 1024 * 1024)
    result = ProcessingResult(
        input_file=input_file,
        output_file=output_file,
        frame_rate=30.0,
        original_duration=4332.0,
        output_duration=3574.0,
        chunk_count=7,
        used_cuda=True,
        max_audio_volume=0.5,
        time_ratio=0.825,
        size_ratio=0.5,
    )
    summary = server._format_summary(result)
    time_ratio, size_ratio = parse_ratios_from_summary(summary)
    assert time_ratio == 0.83  # (83%)
    assert size_ratio == 0.50  # (50%)
