"""Tests for the chunk detection and expression utilities."""

from __future__ import annotations

import numpy as np
import pytest

from talks_reducer.chunks import build_chunks, detect_loud_frames, get_tree_expression


def test_detect_loud_frames_respects_thresholds():
    """`detect_loud_frames` should honour the configured silence threshold."""

    samples_per_frame = 2
    audio_frame_count = 6
    audio_data = np.array(
        [
            0.95,
            0.9,
            0.1,
            0.2,
            0.6,
            0.55,
            0.05,
            0.1,
            -0.7,
            -0.8,
            0.0,
            0.02,
        ],
        dtype=np.float32,
    )
    max_volume = float(np.max(np.abs(audio_data)))

    loud_mask = detect_loud_frames(
        audio_data,
        audio_frame_count,
        samples_per_frame,
        max_audio_volume=max_volume,
        silent_threshold=0.5,
    )
    high_threshold_mask = detect_loud_frames(
        audio_data,
        audio_frame_count,
        samples_per_frame,
        max_audio_volume=max_volume,
        silent_threshold=0.75,
    )

    np.testing.assert_array_equal(
        loud_mask,
        np.array([True, False, True, False, True, False], dtype=bool),
    )
    np.testing.assert_array_equal(
        high_threshold_mask,
        np.array([True, False, False, False, True, False], dtype=bool),
    )


@pytest.mark.parametrize(
    "has_loud_audio, frame_spreadage, expected_chunks, expected_inclusion",
    [
        (
            np.array([False, False, True, True, False, False], dtype=bool),
            0,
            [[0, 2, 0], [2, 4, 1], [4, 6, 0]],
            np.array([False, False, True, True, False, False], dtype=bool),
        ),
        (
            np.array([False, False, True, True, False, False], dtype=bool),
            1,
            [[0, 1, 0], [1, 5, 1], [5, 6, 0]],
            np.array([False, True, True, True, True, False], dtype=bool),
        ),
        (
            np.array([False, True, False, True, False], dtype=bool),
            0,
            [[0, 1, 0], [1, 2, 1], [2, 3, 0], [3, 4, 1], [4, 5, 0]],
            np.array([False, True, False, True, False], dtype=bool),
        ),
    ],
)
def test_build_chunks_spread_and_transitions(
    has_loud_audio: np.ndarray,
    frame_spreadage: int,
    expected_chunks: list[list[int]],
    expected_inclusion: np.ndarray,
) -> None:
    """`build_chunks` should widen loud regions and split transitions correctly."""

    chunks, inclusion = build_chunks(has_loud_audio, frame_spreadage)

    assert chunks == expected_chunks
    np.testing.assert_array_equal(inclusion, expected_inclusion)


def test_get_tree_expression_single_chunk() -> None:
    """A single chunk should render a direct linear mapping expression."""

    chunks = [[0, 4, 0, 4]]

    expression = get_tree_expression(chunks)

    assert expression == "N*1.0+0.0/TB/FR"


def test_get_tree_expression_balances_multiple_chunks() -> None:
    """A multi-chunk tree should encode local speedups in each branch."""

    chunks = [
        [0, 3, 0, 3],
        [3, 5, 3, 4],
        [5, 6, 4, 5],
    ]

    expression = get_tree_expression(chunks)

    assert expression == "if(lt(N,3),N*1.0+0.0,if(lt(N,5),N*0.5+1.5,N*1.0-1.0))/TB/FR"
    speeds = [(chunk[3] - chunk[2]) / (chunk[1] - chunk[0]) for chunk in chunks]
    assert speeds == pytest.approx([1.0, 0.5, 1.0])
