# Full-mode layout polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stable full-mode layout: fixed drop zone, one-row Cut video, centred long-pause entries, aligned voice checkbox, scrollable Advanced block.

**Architecture:** All changes live in `talks_reducer/gui/layout.py` (build + mode toggles), with small hooks in `preferences.py` (advanced toggle, theme widget map), `theme.py` (canvas background) and `app.py` (cut panel toggle → re-fit). The Advanced block moves into a `tk.Canvas` + `ttk.Scrollbar` wrapper whose height is refitted from a debounced `<Configure>` handler.

**Tech Stack:** Python, Tkinter/ttk, pytest (stub suite + `tests/test_gui_real_tk.py` for geometry).

**Spec:** `docs/superpowers/specs/2026-11-22-full-layout-polish-design.md`

## Global Constraints

- Simple mode layout is unchanged.
- Drop zone: 50px in full mode, multiplied by `tk scaling / (96/72)`.
- Shared trailing gap after a value row: `(12, 0)`.
- Never mix geometry managers on one widget.

## Review Focus

- Toggling Simple ↔ full repeatedly: drop zone returns to large in Simple and to 50px in full.
- Advanced open + Cut video toggled: Advanced height refits, no clipping.
- Window resized smaller/larger with Advanced open: scrollbar appears/disappears.
- Mouse wheel over the Advanced block scrolls it; over the log it scrolls the log.
- Theme switch: canvas background follows the palette.

---

### Task 1: Entry centring + voice checkbox gap

**Files:** Modify `talks_reducer/gui/layout.py` (`build_long_pause_controls`, `build_silence_speedup_row`, codec suffix pack); Test `tests/test_gui_layout.py`.

**Interfaces:** Produces `layout.VALUE_ROW_TRAILING_GAP = (12, 0)`.

- [ ] Tests: both long-pause entries have `kwargs["justify"] == "center"`; `vad_check` packs with `padx=layout.VALUE_ROW_TRAILING_GAP`; `add_codec_suffix_check` too.
- [ ] Run → fail; implement; run → pass; commit `feat:`.

### Task 2: Cut video single row

**Files:** Modify `layout.build_cut_panel`; Test `tests/test_gui_layout.py`.

Grid: row 0 = Start label c0, start slider c1 (weight 1), start entry c2, End label c3, end slider c4 (weight 1), end entry c5, Convert c6, Remove only c7 — no `rowspan`. Row 1 = Remove label c0, entry c1 colspan 5, Mark cuts c6. Slider `length=120`.

- [ ] Tests: no cut-panel widget uses `rowspan`; start/end sliders share `row=0`; Remove row is `row=1`.
- [ ] Run → fail; implement; run → pass; commit.

### Task 3: Fixed-height drop zone in full mode

**Files:** Modify `layout.build_layout` (store `gui.main_frame`, `gui.input_frame`), `layout.apply_simple_mode`; add `layout.scaled_pixels(gui, value: int) -> int` and `layout.apply_drop_zone_height(gui, *, simple: bool) -> None`; constant `DROP_ZONE_FULL_HEIGHT = 50`.

Full: `input_frame.configure(height=scaled)`, `grid_propagate(False)`, `main.rowconfigure(0, weight=0)`. Simple: `grid_propagate(True)`, weight 1.

- [ ] Tests: `scaled_pixels` returns 50 at scaling 96/72 and 75 at 2.0; `apply_simple_mode` full path sets weight 0 + propagate False, simple path weight 1 + propagate True.
- [ ] Run → fail; implement; run → pass; commit.

### Task 4: Scrollable Advanced block

**Files:** Modify `layout.build_layout` (wrapper), `preferences.toggle_advanced` and `layout.apply_simple_mode` (show/hide `gui.advanced_container` instead of `advanced_frame`), `app._toggle_cut_panel` (refit), `preferences.refresh_theme` + `theme.apply_theme` (`advanced_canvas` bg = `palette["background"]`); log `tk.Text` height 10 → 4.

**Interfaces:** Produces `gui.advanced_container`, `gui.advanced_canvas`, `gui.advanced_scrollbar`, `gui.advanced_frame` (inner frame, unchanged name for all children), `layout.advanced_canvas_height(available: int, content: int, minimum: int) -> tuple[int, bool]` (height, needs_scroll), `layout.refit_advanced(gui) -> None` (debounced via `after_idle`).

Available height = `main.winfo_height() - (main.winfo_reqheight() - canvas.winfo_reqheight())`; height = `max(minimum, min(content, available))`; scrollbar `grid()` only when `content > height`. Mouse wheel bound with `bind_all` on canvas `<Enter>`, released on `<Leave>`.

- [ ] Tests: `advanced_canvas_height` (fits → content, no scroll; overflow → available, scroll; tiny → minimum); toggle/apply_simple_mode use `advanced_container`; theme configures canvas bg; real-Tk test that a tall inner frame in a short wrapper yields scroll.
- [ ] Run → fail; implement; run → pass; commit.

### Task 5: Verify + docs

- [ ] Launch the GUI in full mode, screenshot with Advanced open/closed, Cut video on/off, resize.
- [ ] Update `CLAUDE.md` GUI section and `docs/gui.md`; check off TODO; `black`, `isort`, full `pytest`; commit.
