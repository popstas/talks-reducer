"""Tests for parsing ratios from GUI remote summaries."""

from talks_reducer.gui.app import _parse_ratios_from_summary


def test_parse_ratios_from_summary_with_percentages() -> None:
    summary = """
**Input:** `video.mp4`
**Output:** `video_processed.mp4`
**Duration:** 30s (60s original) — 50.0% of the original
**Size:** 25.0% of the original file
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
**Duration:** 30s (60s original)
**Chunks merged:** 10
**Encoder:** CPU
""".strip()

    time_ratio, size_ratio = _parse_ratios_from_summary(summary)

    assert time_ratio is None
    assert size_ratio is None


def test_parse_ratios_from_summary_integer_percentages() -> None:
    summary = """
**Input:** `video.mp4`
**Output:** `video_processed.mp4`
**Duration:** 45s (60s original) — 75% of the original
**Size:** 40% of the original file
**Chunks merged:** 12
**Encoder:** CPU
""".strip()

    time_ratio, size_ratio = _parse_ratios_from_summary(summary)

    assert time_ratio == 0.75
    assert size_ratio == 0.4
