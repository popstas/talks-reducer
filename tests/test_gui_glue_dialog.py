"""Tests for the pure helpers behind the glue order dialog."""

from __future__ import annotations

from talks_reducer.gui import glue_dialog


def test_sort_glue_inputs_orders_by_file_name_not_folder() -> None:
    files = [
        "/z/2026-11-03 15-18-04.mp4",
        "/a/2026-11-03 14-51-09.mp4",
    ]

    assert glue_dialog.sort_glue_inputs(files) == [
        "/a/2026-11-03 14-51-09.mp4",
        "/z/2026-11-03 15-18-04.mp4",
    ]


def test_sort_glue_inputs_compares_numbers_naturally_and_ignores_case() -> None:
    files = ["/v/Part10.mp4", "/v/part2.mp4", "/v/part1.mp4"]

    assert glue_dialog.sort_glue_inputs(files) == [
        "/v/part1.mp4",
        "/v/part2.mp4",
        "/v/Part10.mp4",
    ]


def test_sort_glue_inputs_breaks_name_ties_by_path() -> None:
    files = ["/b/talk.mp4", "/a/talk.mp4"]

    assert glue_dialog.sort_glue_inputs(files) == ["/a/talk.mp4", "/b/talk.mp4"]


def test_move_item_moves_and_reports_new_index() -> None:
    items = ["a", "b", "c"]

    assert glue_dialog.move_item(items, 2, -1) == (["a", "c", "b"], 1)
    assert glue_dialog.move_item(items, 0, 2) == (["b", "c", "a"], 2)
    assert items == ["a", "b", "c"], "the input list must not be mutated"


def test_move_item_clamps_at_the_edges() -> None:
    assert glue_dialog.move_item(["a", "b"], 0, -1) == (["a", "b"], 0)
    assert glue_dialog.move_item(["a", "b"], 1, 5) == (["a", "b"], 1)


def test_move_item_ignores_an_out_of_range_index() -> None:
    assert glue_dialog.move_item(["a"], 3, 1) == (["a"], 3)


def test_display_names_show_paths_only_for_duplicate_names() -> None:
    files = ["/a/talk.mp4", "/b/talk.mp4", "/a/intro.mp4"]

    assert glue_dialog.display_names(files) == [
        "/a/talk.mp4",
        "/b/talk.mp4",
        "intro.mp4",
    ]
