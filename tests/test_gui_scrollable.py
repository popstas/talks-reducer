"""Tests for the scrollable Advanced block (``talks_reducer.gui.scrollable``)."""

from __future__ import annotations

from talks_reducer.gui.scrollable import fit_height


def test_content_that_fits_gets_its_own_height_and_no_scrollbar():
    assert fit_height(available=500, content=300, minimum=80) == (300, False)


def test_content_taller_than_the_space_left_scrolls():
    assert fit_height(available=200, content=600, minimum=80) == (200, True)


def test_a_cramped_window_still_shows_the_minimum():
    assert fit_height(available=20, content=600, minimum=80) == (80, True)


def test_short_content_below_the_minimum_does_not_scroll():
    assert fit_height(available=20, content=50, minimum=80) == (50, False)
