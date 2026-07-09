"""Layout helpers for the Talks Reducer GUI."""

from __future__ import annotations

import math
import re
import sys
import time
from typing import TYPE_CHECKING, Callable, Optional

from .. import presets
from ..icons import find_icon_path
from ..models import default_temp_folder
from .tooltips import add_tooltip

if TYPE_CHECKING:  # pragma: no cover - imported for type checking only
    import tkinter as tk

    from .app import TalksReducerGUI


def format_local_server_url(url: str | None) -> str:
    """Return the display text for the local server URL shown in server mode.

    A trailing slash is removed and an empty/whitespace URL yields an empty
    string so the label can stay hidden when no managed server URL is known.
    """

    if not url:
        return ""
    trimmed = str(url).strip()
    if not trimmed:
        return ""
    return f"Server: {trimmed.rstrip('/')}"


def format_activity_line(entry: dict) -> str:
    """Return a single rendered ``HH:MM:SS  <ip>  <action>`` activity line.

    The ``timestamp`` is interpreted as seconds since the epoch and rendered in
    local time. A missing or invalid timestamp degrades to ``--:--:--`` so the
    activity log never raises while polling the server.
    """

    timestamp = entry.get("timestamp")
    try:
        clock = time.strftime("%H:%M:%S", time.localtime(float(timestamp)))
    except (TypeError, ValueError):
        clock = "--:--:--"
    client_ip = str(entry.get("client_ip") or "unknown")
    action = str(entry.get("action") or "")
    return f"{clock}  {client_ip}  {action}".rstrip()


BASIC_PRESETS: dict[str, dict[str, float]] = {
    "compress_only": {
        "silent_speed": 1.0,
        "sounded_speed": 1.0,
        "silent_threshold": 0.01,
    },
    "defaults": {
        "silent_speed": 5.0,
        "sounded_speed": 1.0,
        "silent_threshold": 0.01,
    },
    "silence_x10": {
        "silent_speed": 10.0,
        "sounded_speed": 1.0,
        "silent_threshold": 0.01,
    },
}

BASIC_PRESET_TOLERANCE = 1e-9


def apply_preset_to_gui(gui: "TalksReducerGUI", preset: "presets.Preset") -> None:
    """Fan a stored :class:`~talks_reducer.presets.Preset` onto the GUI vars.

    The resolution tri-state maps onto ``small_var``/``small_480_var`` explicitly
    (``1080p`` → both off, ``720p`` → small only, ``480p`` → small + 480p) so a
    preset always wins over a persisted ``--small`` default. Speeds and the
    threshold route through the basic-slider updaters when they exist so the
    slider labels and persisted preferences stay in sync; the codec updates the
    shared ``video_codec_var``.
    """

    if preset.resolution == "1080p":
        gui.small_var.set(False)
        gui.small_480_var.set(False)
    elif preset.resolution == "480p":
        gui.small_var.set(True)
        gui.small_480_var.set(True)
    else:  # "720p" and any unexpected value map to the 720p small preset.
        gui.small_var.set(True)
        gui.small_480_var.set(False)

    updaters = getattr(gui, "_slider_updaters", {})
    variables = getattr(gui, "_basic_variables", {})
    for key, value in (
        ("silent_speed", preset.silent_speed),
        ("sounded_speed", preset.sounded_speed),
        ("silent_threshold", preset.silent_threshold),
    ):
        updater: Callable[[str], None] | None = updaters.get(key)
        if updater is not None:
            updater(str(value))
        else:
            variable = variables.get(key)
            if variable is not None:
                variable.set(value)

    gui.video_codec_var.set(preset.video_codec)


def _apply_simple_preset(gui: "TalksReducerGUI") -> None:
    """Apply the user-named preset selected in the simple-mode dropdown.

    The chosen name is looked up in the cached preset list, fanned onto the GUI
    vars, and persisted via ``selected_preset`` so the choice survives relaunch.
    """

    name = gui.simple_preset_var.get()
    preset = presets.find_preset(name, getattr(gui, "_simple_presets", []))
    if preset is None:
        return
    apply_preset_to_gui(gui, preset)
    presets.set_selected_preset(name)


def advanced_preset_values(gui: "TalksReducerGUI") -> dict:
    """Snapshot the live Advanced knobs as a preset-comparable mapping.

    ``small_var``/``small_480_var`` collapse back into the resolution tri-state
    (``1080p``/``720p``/``480p``) and the speeds, threshold, and codec read from
    their shared GUI vars so the result can be fed straight to
    :func:`~talks_reducer.presets.match_preset` or
    :func:`~talks_reducer.presets.Preset`.
    """

    if gui.small_var.get():
        resolution = "480p" if gui.small_480_var.get() else "720p"
    else:
        resolution = "1080p"

    return {
        "resolution": resolution,
        "silent_speed": gui.silent_speed_var.get(),
        "sounded_speed": gui.sounded_speed_var.get(),
        "silent_threshold": gui.silent_threshold_var.get(),
        "video_codec": gui.video_codec_var.get(),
    }


def preset_from_gui(gui: "TalksReducerGUI", name: str) -> "presets.Preset":
    """Build a :class:`~talks_reducer.presets.Preset` named *name* from the knobs."""

    values = advanced_preset_values(gui)
    return presets.Preset(
        name=name,
        resolution=str(values["resolution"]),
        silent_speed=float(values["silent_speed"]),
        sounded_speed=float(values["sounded_speed"]),
        silent_threshold=float(values["silent_threshold"]),
        video_codec=str(values["video_codec"]),
    )


def refresh_advanced_preset_selection(gui: "TalksReducerGUI") -> None:
    """Flip the Advanced dropdown to the matching preset or ``"Custom"``.

    Reverse-matches the live knobs against the cached preset list and writes the
    result into ``advanced_preset_var`` so any manual edit that no longer matches
    a stored preset shows :data:`~talks_reducer.presets.CUSTOM_LABEL`.
    """

    if not hasattr(gui, "advanced_preset_var"):
        return
    values = advanced_preset_values(gui)
    name = presets.match_preset(values, getattr(gui, "_simple_presets", []))
    gui.advanced_preset_var.set(name or presets.CUSTOM_LABEL)


def refresh_preset_dropdowns(gui: "TalksReducerGUI") -> None:
    """Reload the preset store and repopulate both surface dropdowns.

    Called after any Save as… / Update / Delete so the Simple and Advanced
    combos stay in sync. The Simple selector is hidden whenever the list is
    empty (or the GUI is not in Simple mode); the Advanced selection is
    re-derived from the current knobs.
    """

    loaded = presets.load_presets()
    gui._simple_presets = loaded
    names = [preset.name for preset in loaded]

    if hasattr(gui, "simple_preset_combo"):
        gui.simple_preset_combo.configure(values=names)
    if hasattr(gui, "advanced_preset_combo"):
        gui.advanced_preset_combo.configure(values=names)

    if hasattr(gui, "simple_preset_frame"):
        if loaded and gui.simple_mode_var.get():
            gui.simple_preset_frame.grid()
        else:
            gui.simple_preset_frame.grid_remove()

    refresh_advanced_preset_selection(gui)


def apply_advanced_preset(gui: "TalksReducerGUI") -> None:
    """Apply the preset chosen in the Advanced dropdown to the live knobs."""

    name = gui.advanced_preset_var.get()
    if not name or name == presets.CUSTOM_LABEL:
        return
    preset = presets.find_preset(name, getattr(gui, "_simple_presets", []))
    if preset is None:
        return
    apply_preset_to_gui(gui, preset)
    presets.set_selected_preset(name)
    refresh_advanced_preset_selection(gui)


def save_advanced_preset(gui: "TalksReducerGUI", name: str) -> None:
    """Capture the current knobs into a new preset named *name* and persist it."""

    name = str(name).strip()
    if not name:
        return
    preset = preset_from_gui(gui, name)
    updated = presets.add_preset(getattr(gui, "_simple_presets", []), preset)
    presets.save_presets(updated)
    presets.set_selected_preset(name)
    refresh_preset_dropdowns(gui)
    gui.advanced_preset_var.set(name)


def update_advanced_preset(gui: "TalksReducerGUI") -> None:
    """Overwrite the selected preset with the current knobs and persist it."""

    name = gui.advanced_preset_var.get()
    if not name or name == presets.CUSTOM_LABEL:
        return
    preset = preset_from_gui(gui, name)
    updated = presets.update_preset(getattr(gui, "_simple_presets", []), name, preset)
    presets.save_presets(updated)
    presets.set_selected_preset(name)
    refresh_preset_dropdowns(gui)
    gui.advanced_preset_var.set(name)


def delete_advanced_preset(gui: "TalksReducerGUI") -> None:
    """Remove the selected preset from the store and refresh the dropdowns."""

    name = gui.advanced_preset_var.get()
    if not name or name == presets.CUSTOM_LABEL:
        return
    updated = presets.delete_preset(getattr(gui, "_simple_presets", []), name)
    presets.save_presets(updated)
    presets.set_selected_preset(None)
    refresh_preset_dropdowns(gui)
    gui.advanced_preset_var.set(presets.CUSTOM_LABEL)


def build_cut_panel(gui: "TalksReducerGUI", parent: "tk.Misc", *, row: int) -> None:
    """Build the collapsible **Cut video** panel with range sliders + inputs.

    The panel hosts two linked sliders (start ≤ end, range ``0..duration``) and,
    next to each, a text entry for typing the in/out timecode by hand (supporting
    millisecond precision via ``HH:MM:SS.mmm``). A tall **Convert** button spans
    both slider rows so that, when Simple mode is off, the user can review the
    trim before processing starts instead of converting immediately. The panel is
    shown only when ``cut_enabled_var`` is set and is available in both Simple and
    Advanced layouts. Slider movement is forwarded to
    ``gui._on_cut_slider_change`` so the application can clamp the handles.
    """

    panel = gui.ttk.Frame(parent)
    panel.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(8, 0))
    panel.columnconfigure(1, weight=1)
    gui.cut_panel = panel

    gui.ttk.Label(panel, text="Start").grid(row=0, column=0, sticky="w")
    gui.cut_start_slider = gui.tk.Scale(
        panel,
        variable=gui.cut_start_var,
        from_=0.0,
        to=0.0,
        orient=gui.tk.HORIZONTAL,
        resolution=0.001,
        showvalue=False,
        command=lambda _value: gui._on_cut_slider_change("start"),
        length=240,
        highlightthickness=0,
    )
    gui.cut_start_slider.grid(row=0, column=1, sticky="ew", padx=(8, 8))
    gui.cut_start_entry = gui.ttk.Entry(
        panel, textvariable=gui.cut_start_text_var, width=13, justify="center"
    )
    gui.cut_start_entry.grid(row=0, column=2, sticky="e")
    gui.cut_start_entry.bind("<Return>", lambda _e: gui._on_cut_entry_commit("start"))
    gui.cut_start_entry.bind("<FocusOut>", lambda _e: gui._on_cut_entry_commit("start"))

    gui.ttk.Label(panel, text="End").grid(row=1, column=0, sticky="w", pady=(4, 0))
    gui.cut_end_slider = gui.tk.Scale(
        panel,
        variable=gui.cut_end_var,
        from_=0.0,
        to=0.0,
        orient=gui.tk.HORIZONTAL,
        resolution=0.001,
        showvalue=False,
        command=lambda _value: gui._on_cut_slider_change("end"),
        length=240,
        highlightthickness=0,
    )
    gui.cut_end_slider.grid(row=1, column=1, sticky="ew", padx=(8, 8), pady=(4, 0))
    gui.cut_end_entry = gui.ttk.Entry(
        panel, textvariable=gui.cut_end_text_var, width=13, justify="center"
    )
    gui.cut_end_entry.grid(row=1, column=2, sticky="e", pady=(4, 0))
    gui.cut_end_entry.bind("<Return>", lambda _e: gui._on_cut_entry_commit("end"))
    gui.cut_end_entry.bind("<FocusOut>", lambda _e: gui._on_cut_entry_commit("end"))

    gui.cut_convert_button = gui.ttk.Button(
        panel,
        text="Convert",
        command=gui._start_run,
    )
    gui.cut_convert_button.grid(
        row=0, column=3, rowspan=2, sticky="nsew", padx=(8, 0), pady=(0, 0)
    )

    sliders = getattr(gui, "_sliders", None)
    if isinstance(sliders, list):
        sliders.append(gui.cut_start_slider)
        sliders.append(gui.cut_end_slider)

    if not gui.cut_enabled_var.get():
        panel.grid_remove()
    gui._update_cut_convert_button()


def build_layout(gui: "TalksReducerGUI") -> None:
    """Construct the main layout for the GUI."""

    main = gui.ttk.Frame(gui.root, padding=gui.PADDING)
    main.grid(row=0, column=0, sticky="nsew")
    gui.root.columnconfigure(0, weight=1)
    gui.root.rowconfigure(0, weight=1)

    # Input selection frame
    input_frame = gui.ttk.Frame(main, padding=gui.PADDING)
    input_frame.grid(row=0, column=0, sticky="nsew")
    main.rowconfigure(0, weight=1)
    main.columnconfigure(0, weight=1)
    input_frame.columnconfigure(0, weight=1)
    input_frame.rowconfigure(0, weight=1)

    gui.drop_zone = gui.tk.Label(
        input_frame,
        text="Drop video here",
        relief=gui.tk.FLAT,
        borderwidth=0,
        padx=gui.PADDING,
        pady=gui.PADDING,
        highlightthickness=0,
    )
    gui.drop_zone.grid(row=0, column=0, sticky="nsew")
    gui._configure_drop_targets(gui.drop_zone)
    gui.drop_zone.configure(cursor="hand2", takefocus=1)
    gui.drop_zone.bind("<Button-1>", gui._on_drop_zone_click)
    gui.drop_zone.bind("<Return>", gui._on_drop_zone_click)
    gui.drop_zone.bind("<space>", gui._on_drop_zone_click)

    # Options frame (compact padding for simple mode at 470px width)
    gui.options_frame = gui.ttk.Frame(main, padding=6)
    gui.options_frame.grid(row=2, column=0, pady=(0, 0), sticky="ew")
    gui.options_frame.columnconfigure(0, weight=1)

    checkbox_frame = gui.ttk.Frame(gui.options_frame)
    checkbox_frame.grid(row=0, column=0, columnspan=2, sticky="w")

    # User-named preset dropdown (visible in simple mode only). It is populated
    # from the shared preset store and hidden entirely when no presets exist.
    gui._simple_presets = presets.load_presets()
    preset_frame = gui.ttk.Frame(checkbox_frame)
    preset_label = gui.ttk.Label(preset_frame, text="Preset:")
    preset_label.pack(side=gui.tk.LEFT, padx=(0, 2))
    preset_combo = gui.ttk.Combobox(
        preset_frame,
        textvariable=gui.simple_preset_var,
        values=[preset.name for preset in gui._simple_presets],
        state="readonly",
        width=28,
    )
    preset_combo.pack(side=gui.tk.LEFT)
    preset_combo.bind("<<ComboboxSelected>>", lambda e: _apply_simple_preset(gui))
    preset_frame.grid(row=0, column=0, sticky="w")
    if not gui._simple_presets:
        preset_frame.grid_remove()

    checkbox_row1 = gui.ttk.Frame(checkbox_frame)
    checkbox_row1.grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))
    gui.ttk.Checkbutton(
        checkbox_row1,
        text="Small video",
        variable=gui.small_var,
    ).pack(side=gui.tk.LEFT)
    gui.small_480_check = gui.ttk.Checkbutton(
        checkbox_row1,
        text="480p",
        variable=gui.small_480_var,
    )
    gui.small_480_check.pack(side=gui.tk.LEFT, padx=(65, 0))
    gui.ttk.Checkbutton(
        checkbox_row1,
        text="Open output",
        variable=gui.open_after_convert_var,
    ).pack(side=gui.tk.LEFT, padx=(65, 0))

    gui.cut_check = gui.ttk.Checkbutton(
        checkbox_row1,
        text="Cut video",
        variable=gui.cut_enabled_var,
        command=gui._toggle_cut_panel,
    )
    gui.cut_check.pack(side=gui.tk.LEFT, padx=(65, 0))

    build_cut_panel(gui, checkbox_frame, row=2)

    gui.simple_mode_check = gui.ttk.Checkbutton(
        checkbox_frame,
        text="Simple mode",
        variable=gui.simple_mode_var,
        command=gui._toggle_simple_mode,
    )
    gui.simple_mode_check.grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))

    gui.simple_preset_frame = preset_frame
    gui.simple_preset_label = preset_label
    gui.simple_preset_combo = preset_combo

    gui.advanced_visible = gui.tk.BooleanVar(value=False)

    # Advanced-mode preset management strip: a Preset dropdown plus
    # Save as… / Update / Delete. It authors the shared preset store and is
    # hidden in Simple mode (where the read-only Simple dropdown applies instead).
    advanced_preset_frame = gui.ttk.Frame(gui.options_frame)
    advanced_preset_frame.grid(row=1, column=0, columnspan=2, sticky="w", pady=(12, 0))
    gui.ttk.Label(advanced_preset_frame, text="Preset:").pack(
        side=gui.tk.LEFT, padx=(0, 2)
    )
    gui.advanced_preset_combo = gui.ttk.Combobox(
        advanced_preset_frame,
        textvariable=gui.advanced_preset_var,
        values=[preset.name for preset in gui._simple_presets],
        state="readonly",
        width=28,
    )
    gui.advanced_preset_combo.pack(side=gui.tk.LEFT)
    gui.advanced_preset_combo.bind(
        "<<ComboboxSelected>>", lambda e: apply_advanced_preset(gui)
    )
    gui.advanced_preset_save_button = gui.ttk.Button(
        advanced_preset_frame,
        text="Save as…",
        command=gui._open_save_preset_dialog,
    )
    gui.advanced_preset_save_button.pack(side=gui.tk.LEFT, padx=(8, 0))
    gui.advanced_preset_update_button = gui.ttk.Button(
        advanced_preset_frame,
        text="Update",
        command=gui._update_selected_preset,
    )
    gui.advanced_preset_update_button.pack(side=gui.tk.LEFT, padx=(4, 0))
    gui.advanced_preset_delete_button = gui.ttk.Button(
        advanced_preset_frame,
        text="Delete",
        command=gui._delete_selected_preset,
    )
    gui.advanced_preset_delete_button.pack(side=gui.tk.LEFT, padx=(4, 0))
    gui.advanced_preset_frame = advanced_preset_frame

    # Editing any knob flips the Advanced dropdown to "Custom"; slider vars route
    # through ``update_basic_reset_state`` while the small/codec vars trace here.
    for _preset_var in (gui.small_var, gui.small_480_var, gui.video_codec_var):
        _preset_var.trace_add(
            "write", lambda *_: refresh_advanced_preset_selection(gui)
        )

    basic_label_container = gui.ttk.Frame(gui.options_frame)
    basic_label = gui.ttk.Label(basic_label_container, text="Basic options")
    basic_label.pack(side=gui.tk.LEFT)

    gui.basic_presets_frame = gui.ttk.Frame(basic_label_container)
    gui.basic_presets_frame.pack(side=gui.tk.LEFT, padx=(12, 0))

    gui.basic_preset_buttons: dict[str, "tk.Misc"] = {}

    gui.no_speedup_button = gui.ttk.Button(
        gui.basic_presets_frame,
        text="No speedup, only compress",
        command=lambda: gui._apply_basic_preset("compress_only"),
        style="Link.TButton",
    )
    gui.no_speedup_button.pack(side=gui.tk.LEFT, padx=(0, 8))
    gui.basic_preset_buttons["compress_only"] = gui.no_speedup_button

    gui.reset_basic_button = gui.ttk.Button(
        gui.basic_presets_frame,
        text="Speedup silence ×5 (default speed and threshold)",
        command=lambda: gui._apply_basic_preset("defaults"),
        state=gui.tk.DISABLED,
        style="Link.TButton",
    )
    gui.reset_basic_button.pack(side=gui.tk.LEFT, padx=(0, 8))
    gui.basic_preset_buttons["defaults"] = gui.reset_basic_button

    gui.silence_speed_x10_button = gui.ttk.Button(
        gui.basic_presets_frame,
        text="Speedup silence ×10",
        command=lambda: gui._apply_basic_preset("silence_x10"),
        style="Link.TButton",
    )
    gui.silence_speed_x10_button.pack(side=gui.tk.LEFT)
    gui.basic_preset_buttons["silence_x10"] = gui.silence_speed_x10_button

    gui.basic_options_frame = gui.ttk.Labelframe(
        gui.options_frame, padding=0, labelwidget=basic_label_container
    )
    gui.basic_options_frame.grid(
        row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0)
    )
    gui.basic_options_frame.columnconfigure(1, weight=1)

    gui.silent_speed_var = gui.tk.DoubleVar(
        value=min(max(gui.preferences.get_float("silent_speed", 5.0), 1.0), 10.0)
    )
    add_slider(
        gui,
        gui.basic_options_frame,
        "Silent speed",
        gui.silent_speed_var,
        row=0,
        setting_key="silent_speed",
        minimum=1.0,
        maximum=10.0,
        resolution=0.5,
        display_format="{:.1f}×",
        default_value=5.0,
    )

    gui.sounded_speed_var = gui.tk.DoubleVar(
        value=min(max(gui.preferences.get_float("sounded_speed", 1.0), 0.75), 2.0)
    )
    add_slider(
        gui,
        gui.basic_options_frame,
        "Sounded speed",
        gui.sounded_speed_var,
        row=1,
        setting_key="sounded_speed",
        minimum=0.75,
        maximum=2.0,
        resolution=0.25,
        display_format="{:.2f}×",
        default_value=1.0,
    )

    gui.silent_threshold_var = gui.tk.DoubleVar(
        value=min(max(gui.preferences.get_float("silent_threshold", 0.01), 0.0), 1.0)
    )
    add_slider(
        gui,
        gui.basic_options_frame,
        "Silent threshold",
        gui.silent_threshold_var,
        row=2,
        setting_key="silent_threshold",
        minimum=0.0,
        maximum=1.0,
        resolution=0.01,
        display_format="{:.2f}",
        default_value=0.01,
        pady=(4, 12),
    )

    gui.ttk.Label(gui.basic_options_frame, text="Video codec").grid(
        row=3, column=0, sticky="w", pady=(8, 0)
    )
    codec_choice = gui.ttk.Frame(gui.basic_options_frame)
    codec_choice.grid(row=3, column=1, columnspan=2, sticky="w", pady=(8, 0))
    gui.video_codec_buttons = {}
    for value, label in (
        ("h264", "h.264 (faster)"),
        ("hevc", "h.265 (25% smaller)"),
        ("av1", "av1 (no advantages)"),
        ("mp3", "mp3 (audio only)"),
    ):
        button = gui.ttk.Radiobutton(
            codec_choice,
            text=label,
            value=value,
            variable=gui.video_codec_var,
        )
        button.pack(side=gui.tk.LEFT, padx=(0, 8))
        gui.video_codec_buttons[value] = button

    gui.add_codec_suffix_check = gui.ttk.Checkbutton(
        codec_choice,
        text="Add codec suffix to filename",
        variable=gui.add_codec_suffix_var,
    )
    gui.add_codec_suffix_check.pack(side=gui.tk.LEFT, padx=(0, 8))

    gui.ttk.Label(gui.basic_options_frame, text="Processing mode").grid(
        row=4, column=0, sticky="w", pady=(8, 0)
    )
    mode_choice = gui.ttk.Frame(gui.basic_options_frame)
    mode_choice.grid(row=4, column=1, sticky="w", pady=(8, 0))

    gui.ttk.Radiobutton(
        mode_choice,
        text="Local",
        value="local",
        variable=gui.processing_mode_var,
    ).pack(side=gui.tk.LEFT, padx=(0, 8))

    gui.remote_mode_button = gui.ttk.Radiobutton(
        mode_choice,
        text="Remote",
        value="remote",
        variable=gui.processing_mode_var,
    )
    gui.remote_mode_button.pack(side=gui.tk.LEFT, padx=(0, 8))

    server_managed = bool(getattr(gui, "server_managed", False))
    local_server_url = getattr(gui, "local_server_url", None)
    gui.local_server_url_label = gui.ttk.Label(
        gui.basic_options_frame,
        text=format_local_server_url(local_server_url) if server_managed else "",
    )
    gui.local_server_url_label.grid(
        row=4, column=2, sticky="w", padx=(8, 0), pady=(8, 0)
    )
    if not (server_managed and local_server_url):
        gui.local_server_url_label.grid_remove()

    gui.ttk.Label(gui.basic_options_frame, text="Server URL").grid(
        row=5, column=0, sticky="w", pady=(8, 0)
    )
    gui.server_entry = gui.ttk.Entry(
        gui.basic_options_frame,
        textvariable=gui.server_url_var,
        width=40,
    )
    gui.server_entry.grid(row=5, column=1, sticky="ew", pady=(8, 0))

    gui.server_discover_button = gui.ttk.Button(
        gui.basic_options_frame, text="Discover", command=gui._start_discovery
    )
    gui.server_discover_button.grid(
        row=5, column=2, padx=(8, 0), pady=(8, 0), sticky="ew"
    )

    gui.ttk.Label(gui.basic_options_frame, text="Theme").grid(
        row=6, column=0, sticky="w", pady=(8, 0)
    )
    theme_choice = gui.ttk.Frame(gui.basic_options_frame)
    theme_choice.grid(row=6, column=1, columnspan=2, sticky="w", pady=(8, 0))
    for value, label in ("os", "OS"), ("light", "Light"), ("dark", "Dark"):
        gui.ttk.Radiobutton(
            theme_choice,
            text=label,
            value=value,
            variable=gui.theme_var,
            command=gui._refresh_theme,
        ).pack(side=gui.tk.LEFT, padx=(0, 8))

    # Button frame for Advanced, Check updates button, and status label
    gui.button_frame = gui.ttk.Frame(gui.options_frame)
    gui.button_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
    gui.button_frame.columnconfigure(2, weight=1)

    gui.advanced_button = gui.ttk.Button(
        gui.button_frame,
        text="Advanced",
        command=gui._toggle_advanced,
    )
    gui.advanced_button.grid(row=0, column=0, sticky="w")

    # Check updates button, Create lnk button, and status label (Windows only)
    if sys.platform == "win32":
        gui.check_updates_button = gui.ttk.Button(
            gui.button_frame,
            text="Check updates",
            command=gui._check_for_updates,
        )
        gui.check_updates_button.grid(row=0, column=1, sticky="w", padx=(8, 0))

        gui.lnk_button = gui.ttk.Button(
            gui.button_frame,
            text="Create lnk",
            command=gui._open_create_lnk_dialog,
        )
        gui.lnk_button.grid(row=0, column=2, sticky="w", padx=(8, 0))

        # Update status label (one-line)
        gui.button_frame.columnconfigure(2, weight=0)
        gui.button_frame.columnconfigure(3, weight=1)
        gui.update_status_label = gui.ttk.Label(
            gui.button_frame,
            text="",
            foreground="gray",
        )
        gui.update_status_label.grid(row=0, column=3, sticky="w", padx=(8, 0))

    gui.advanced_frame = gui.ttk.Frame(gui.options_frame, padding=0)
    gui.advanced_frame.grid(row=4, column=0, columnspan=2, sticky="nsew")
    gui.advanced_frame.columnconfigure(1, weight=1)

    # Watch-directory chooser on a single row (checkbox + path + Browse), placed
    # first so it sits above the Output file field. The button that acts on the
    # newest video lives in ``status_frame`` and is owned by ``WatchController``.
    gui.watch_check = gui.ttk.Checkbutton(
        gui.advanced_frame,
        text="Watch directory",
        variable=gui.watch_enabled_var,
    )
    gui.watch_check.grid(row=0, column=0, sticky="w", pady=4)

    gui.watch_directory_entry = gui.ttk.Entry(
        gui.advanced_frame,
        textvariable=gui.watch_directory_var,
    )
    gui.watch_directory_entry.grid(row=0, column=1, sticky="ew", pady=4)

    gui.watch_browse_button = gui.ttk.Button(
        gui.advanced_frame,
        text="Browse…",
        command=lambda: gui.inputs.browse_path(gui.watch_directory_var, "watch folder"),
    )
    gui.watch_browse_button.grid(row=0, column=2, sticky="e", padx=(8, 0), pady=4)

    gui.output_var = gui.tk.StringVar()
    add_entry(
        gui,
        gui.advanced_frame,
        "Output file",
        gui.output_var,
        row=1,
        browse=True,
    )

    gui.temp_var = gui.tk.StringVar(value=str(default_temp_folder()))
    add_entry(
        gui,
        gui.advanced_frame,
        "Temp folder",
        gui.temp_var,
        row=2,
        browse=True,
    )

    gui.optimize_check = gui.ttk.Checkbutton(
        gui.advanced_frame,
        text="Optimized encoding",
        variable=gui.optimize_var,
    )
    gui.optimize_check.grid(row=3, column=0, columnspan=3, sticky="w", pady=4)
    add_tooltip(
        gui.optimize_check,
        "Larger size, but supports seeking",
        tk_module=gui.tk,
    )

    global_ffmpeg_available = getattr(gui, "global_ffmpeg_available", True)
    gui.use_global_ffmpeg_check = gui.ttk.Checkbutton(
        gui.advanced_frame,
        text="Use global FFmpeg",
        variable=gui.use_global_ffmpeg_var,
        state=gui.tk.NORMAL if global_ffmpeg_available else gui.tk.DISABLED,
    )
    if not global_ffmpeg_available:
        gui.use_global_ffmpeg_var.set(False)
    gui.use_global_ffmpeg_check.grid(row=4, column=0, columnspan=3, sticky="w", pady=4)

    gui.sample_rate_var = gui.tk.StringVar(value="48000")
    add_entry(gui, gui.advanced_frame, "Sample rate", gui.sample_rate_var, row=5)

    frame_margin_setting = gui.preferences.get("frame_margin", 2)
    try:
        frame_margin_default = int(frame_margin_setting)
    except (TypeError, ValueError):
        frame_margin_default = 2
        gui.preferences.update("frame_margin", frame_margin_default)

    gui.frame_margin_var = gui.tk.StringVar(value=str(frame_margin_default))
    add_entry(gui, gui.advanced_frame, "Frame margin", gui.frame_margin_var, row=6)

    min_interval = 1.0
    max_interval = 60.0
    interval_resolution = 1.0
    default_keyframe_interval = 30.0
    keyframe_interval_setting = gui.preferences.get_float(
        "keyframe_interval_seconds", default_keyframe_interval
    )
    try:
        validated_interval = float(keyframe_interval_setting)
    except (TypeError, ValueError):
        validated_interval = default_keyframe_interval
    if not (min_interval <= validated_interval <= max_interval):
        validated_interval = max(min_interval, min(max_interval, validated_interval))
        gui.preferences.update(
            "keyframe_interval_seconds", float(f"{validated_interval:.6f}")
        )

    gui.ttk.Label(gui.advanced_frame, text="Keyframe interval").grid(
        row=7, column=0, sticky="w", pady=4
    )

    gui.keyframe_interval_var = gui.tk.DoubleVar(value=validated_interval)

    gui.keyframe_interval_value_label = gui.ttk.Label(gui.advanced_frame)
    gui.keyframe_interval_value_label.grid(row=7, column=2, sticky="e", pady=4)

    keyframe_percent_samples = [
        (60.0, 0.5),
        (30.0, 1.4),
        (10.0, 4.7),
        (5.0, 9.6),
        (1.0, 44.0),
    ]

    def estimate_keyframe_overhead(interval_seconds: float) -> float:
        """Estimate percent size increase vs. encoding with no extra keyframes."""

        bounded = max(min_interval, min(max_interval, interval_seconds))
        samples = keyframe_percent_samples
        if bounded >= samples[0][0]:
            return samples[0][1]
        if bounded <= samples[-1][0]:
            return samples[-1][1]

        for upper_idx in range(len(samples) - 1):
            upper_interval, upper_percent = samples[upper_idx]
            lower_interval, lower_percent = samples[upper_idx + 1]
            if lower_interval <= bounded <= upper_interval:
                ratio = (math.log(bounded) - math.log(upper_interval)) / (
                    math.log(lower_interval) - math.log(upper_interval)
                )
                interpolated = math.exp(
                    math.log(upper_percent)
                    + ratio * (math.log(lower_percent) - math.log(upper_percent))
                )
                return interpolated

        return samples[-1][1]

    def format_percent(delta_percent: float) -> str:
        if abs(delta_percent) >= 10.0:
            return f"{delta_percent:+.0f}%"
        return f"{delta_percent:+.1f}%"

    def update_keyframe_interval(value: str) -> None:
        numeric = float(value)
        clamped = max(min_interval, min(max_interval, numeric))
        steps = round((clamped - min_interval) / interval_resolution)
        quantized = min_interval + steps * interval_resolution
        if abs(gui.keyframe_interval_var.get() - quantized) > 1e-9:
            gui.keyframe_interval_var.set(quantized)
        delta_percent = estimate_keyframe_overhead(quantized)
        gui.keyframe_interval_value_label.configure(
            text=f"{quantized:.0f}s, {format_percent(delta_percent)}"
        )
        gui.preferences.update("keyframe_interval_seconds", float(f"{quantized:.6f}"))

    gui.keyframe_interval_slider = gui.tk.Scale(
        gui.advanced_frame,
        variable=gui.keyframe_interval_var,
        from_=min_interval,
        to=max_interval,
        orient=gui.tk.HORIZONTAL,
        resolution=interval_resolution,
        showvalue=False,
        command=update_keyframe_interval,
        length=240,
        highlightthickness=0,
    )
    gui.keyframe_interval_slider.grid(row=7, column=1, sticky="ew", pady=4, padx=(0, 8))

    update_keyframe_interval(str(validated_interval))
    sliders = getattr(gui, "_sliders", None)
    if isinstance(sliders, list):
        sliders.append(gui.keyframe_interval_slider)

    gui.start_in_server_tray_check = gui.ttk.Checkbutton(
        gui.advanced_frame,
        text="Run as server in tray",
        variable=gui.start_in_server_tray_var,
    )
    gui.start_in_server_tray_check.grid(
        row=8, column=0, columnspan=3, sticky="w", pady=4
    )

    # Check updates button + status label (macOS only) live under Advanced so
    # they mirror the Windows button while pointing macOS users at Homebrew.
    # The Windows branch keeps its button in the always-visible button_frame.
    if sys.platform == "darwin":
        gui.check_updates_button = gui.ttk.Button(
            gui.advanced_frame,
            text="Check updates",
            command=gui._check_for_updates,
        )
        gui.check_updates_button.grid(row=9, column=0, sticky="w", pady=(8, 0))

        gui.update_status_label = gui.ttk.Label(
            gui.advanced_frame,
            text="",
            foreground="gray",
        )
        gui.update_status_label.grid(
            row=9, column=1, columnspan=2, sticky="w", padx=(8, 0), pady=(8, 0)
        )

    gui._toggle_advanced(initial=True)
    gui._update_processing_mode_state()
    update_basic_reset_state(gui)

    # Action buttons and log output
    status_frame = gui.ttk.Frame(main, padding=gui.PADDING)
    status_frame.grid(row=1, column=0, sticky="ew")
    status_frame.columnconfigure(0, weight=0)
    status_frame.columnconfigure(1, weight=1)
    status_frame.columnconfigure(2, weight=0)
    gui.status_frame = status_frame

    gui.ttk.Label(status_frame, text="Status:").grid(row=0, column=0, sticky="w")
    gui.status_label = gui.tk.Label(
        status_frame, textvariable=gui.status_var, anchor="e"
    )
    gui.status_label.grid(row=0, column=1, sticky="e")

    # Progress bar
    gui.progress_bar = gui.ttk.Progressbar(
        status_frame,
        variable=gui.progress_var,
        maximum=100,
        mode="determinate",
        style="Idle.Horizontal.TProgressbar",
    )
    gui.progress_bar.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 0))

    gui.stop_button = gui.ttk.Button(
        status_frame, text="Stop", command=gui._stop_processing
    )
    gui.stop_button.grid(row=2, column=0, columnspan=3, sticky="ew", pady=gui.PADDING)
    gui.stop_button.grid_remove()  # Hidden by default

    gui.open_button = gui.ttk.Button(
        status_frame,
        text="Open last",
        command=gui._open_last_output,
        state=gui.tk.DISABLED,
    )
    gui.open_button.grid(row=2, column=0, columnspan=3, sticky="ew", pady=gui.PADDING)
    gui.open_button.grid_remove()

    # Button shown when no other action buttons are visible
    gui.drop_hint_button = gui.ttk.Button(
        status_frame,
        text="Drop video to convert",
        state=gui.tk.DISABLED,
    )
    gui.drop_hint_button.grid(
        row=2, column=0, columnspan=3, sticky="ew", pady=gui.PADDING
    )
    gui.drop_hint_button.grid_remove()  # Hidden by default
    gui._configure_drop_targets(gui.drop_hint_button)

    # Dynamic watch-directory action button. It shares the status_frame slot with
    # the Stop/Open/Drop buttons; WatchController owns its visibility and label.
    gui.watch_button = gui.ttk.Button(
        status_frame,
        text="Convert",
    )
    gui.watch_button.grid(row=2, column=0, columnspan=3, sticky="ew", pady=gui.PADDING)
    gui.watch_button.grid_remove()  # Hidden until a candidate appears

    gui.log_frame = gui.ttk.Frame(main, padding=gui.PADDING)
    gui.log_frame.grid(row=3, column=0, pady=(16, 0), sticky="nsew")
    main.rowconfigure(3, weight=1)
    gui.log_frame.columnconfigure(0, weight=1)
    gui.log_frame.rowconfigure(0, weight=1)

    gui.log_text = gui.tk.Text(
        gui.log_frame, wrap="word", height=10, state=gui.tk.DISABLED
    )
    gui.log_text.grid(row=0, column=0, sticky="nsew")
    log_scroll = gui.ttk.Scrollbar(
        gui.log_frame, orient=gui.tk.VERTICAL, command=gui.log_text.yview
    )
    log_scroll.grid(row=0, column=1, sticky="ns")
    gui.log_text.configure(yscrollcommand=log_scroll.set)

    # Connected-clients activity log (server mode only).
    gui.activity_frame = gui.ttk.Frame(main, padding=gui.PADDING)
    gui.activity_frame.grid(row=4, column=0, pady=(8, 0), sticky="nsew")
    gui.activity_frame.columnconfigure(0, weight=1)
    gui.activity_frame.rowconfigure(1, weight=1)

    gui.ttk.Label(gui.activity_frame, text="Connected clients").grid(
        row=0, column=0, sticky="w"
    )

    gui.activity_text = gui.tk.Text(
        gui.activity_frame, wrap="word", height=6, state=gui.tk.DISABLED
    )
    gui.activity_text.grid(row=1, column=0, sticky="nsew")
    activity_scroll = gui.ttk.Scrollbar(
        gui.activity_frame, orient=gui.tk.VERTICAL, command=gui.activity_text.yview
    )
    activity_scroll.grid(row=1, column=1, sticky="ns")
    gui.activity_text.configure(yscrollcommand=activity_scroll.set)

    if not bool(getattr(gui, "server_managed", False)):
        gui.activity_frame.grid_remove()

    # Resume watching a persisted directory as soon as the layout is ready.
    watch = getattr(gui, "watch", None)
    if watch is not None and gui.watch_enabled_var.get():
        watch.start()


def add_entry(
    gui: "TalksReducerGUI",
    parent: "tk.Misc",
    label: str,
    variable: "tk.StringVar",
    *,
    row: int,
    browse: bool = False,
) -> None:
    """Add a labeled entry widget to the given *parent* container."""

    gui.ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
    entry = gui.ttk.Entry(parent, textvariable=variable)
    entry.grid(row=row, column=1, sticky="ew", pady=4)
    if browse:
        button = gui.ttk.Button(
            parent,
            text="Browse",
            command=lambda var=variable: gui._browse_path(var, label),
        )
        button.grid(row=row, column=2, padx=(8, 0))


def add_slider(
    gui: "TalksReducerGUI",
    parent: "tk.Misc",
    label: str,
    variable: "tk.DoubleVar",
    *,
    row: int,
    setting_key: str,
    minimum: float,
    maximum: float,
    resolution: float,
    display_format: str,
    default_value: float,
    pady: int | tuple[int, int] = 4,
) -> None:
    """Add a labeled slider to the given *parent* container."""

    gui.ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=pady)

    value_label = gui.ttk.Label(parent)
    value_label.grid(row=row, column=2, sticky="e", pady=pady)

    def update(value: str) -> None:
        numeric = float(value)
        clamped = max(minimum, min(maximum, numeric))
        steps = round((clamped - minimum) / resolution)
        quantized = minimum + steps * resolution
        if abs(variable.get() - quantized) > 1e-9:
            variable.set(quantized)
        value_label.configure(text=display_format.format(quantized))
        gui.preferences.update(setting_key, float(f"{quantized:.6f}"))
        update_basic_reset_state(gui)

    slider = gui.tk.Scale(
        parent,
        variable=variable,
        from_=minimum,
        to=maximum,
        orient=gui.tk.HORIZONTAL,
        resolution=resolution,
        showvalue=False,
        command=update,
        length=240,
        highlightthickness=0,
    )
    slider.grid(row=row, column=1, sticky="ew", pady=pady, padx=(0, 8))

    update(str(variable.get()))

    gui._slider_updaters[setting_key] = update
    gui._basic_defaults[setting_key] = default_value
    gui._basic_variables[setting_key] = variable
    variable.trace_add("write", lambda *_: update_basic_reset_state(gui))
    gui._sliders.append(slider)


def update_basic_reset_state(gui: "TalksReducerGUI") -> None:
    """Enable or disable the reset control based on slider values."""

    if not hasattr(gui, "reset_basic_button"):
        return

    should_enable = False
    for key, default_value in gui._basic_defaults.items():
        variable = gui._basic_variables.get(key)
        if variable is None:
            continue
        try:
            current_value = float(variable.get())
        except (TypeError, ValueError):
            should_enable = True
            break
        if abs(current_value - default_value) > 1e-9:
            should_enable = True
            break

    state = gui.tk.NORMAL if should_enable else gui.tk.DISABLED
    gui.reset_basic_button.configure(state=state)
    update_basic_preset_highlight(gui)
    refresh_advanced_preset_selection(gui)


def update_basic_preset_highlight(gui: "TalksReducerGUI") -> None:
    """Highlight the preset button that matches current slider values."""

    buttons = getattr(gui, "basic_preset_buttons", None)
    if not buttons:
        gui._active_basic_preset = None
        return

    active: str | None = None
    variables = getattr(gui, "_basic_variables", {})
    for preset, values in BASIC_PRESETS.items():
        match = True
        for key, target in values.items():
            variable = variables.get(key)
            if variable is None:
                match = False
                break
            try:
                current_value = float(variable.get())
            except (TypeError, ValueError):
                match = False
                break
            if abs(current_value - target) > BASIC_PRESET_TOLERANCE:
                match = False
                break
        if match:
            active = preset
            break

    for preset, button in buttons.items():
        try:
            style = "SelectedLink.TButton" if preset == active else "Link.TButton"
            button.configure(style=style)
        except Exception:
            continue

    gui._active_basic_preset = active


def reset_basic_defaults(gui: "TalksReducerGUI") -> None:
    """Restore the basic numeric controls to their default values."""

    for key, default_value in gui._basic_defaults.items():
        variable = gui._basic_variables.get(key)
        if variable is None:
            continue

        try:
            current_value = float(variable.get())
        except (TypeError, ValueError):
            current_value = default_value

        if abs(current_value - default_value) <= 1e-9:
            continue

        variable.set(default_value)
        updater: Callable[[str], None] | None = gui._slider_updaters.get(key)
        if updater is not None:
            updater(str(default_value))
        else:
            gui.preferences.update(key, float(f"{default_value:.6f}"))

    update_basic_reset_state(gui)


def apply_basic_preset(gui: "TalksReducerGUI", preset: str) -> None:
    """Apply one of the predefined basic option presets."""

    values = BASIC_PRESETS.get(preset)
    if values is None:
        return

    for key, target in values.items():
        variable = gui._basic_variables.get(key)
        if variable is None:
            continue

        updater: Callable[[str], None] | None = gui._slider_updaters.get(key)
        if updater is not None:
            updater(str(target))
        else:
            variable.set(target)
            gui.preferences.update(key, float(f"{target:.6f}"))

    update_basic_reset_state(gui)


def apply_window_icon(gui: "TalksReducerGUI") -> None:
    """Configure the application icon when the asset is available."""

    icon_filenames = (
        ("app.ico", "app.png")
        if sys.platform.startswith("win")
        else ("app.png", "app.ico")
    )
    icon_path = find_icon_path(filenames=icon_filenames)
    if icon_path is None:
        return

    try:
        if icon_path.suffix.lower() == ".ico" and sys.platform.startswith("win"):
            # On Windows, iconbitmap works better without the 'default' parameter.
            gui.root.iconbitmap(str(icon_path))
        else:
            gui.root.iconphoto(False, gui.tk.PhotoImage(file=str(icon_path)))
    except (gui.tk.TclError, Exception):
        # Missing Tk image support or invalid icon format - fail silently.
        return


_GEOMETRY_RE = re.compile(r"^(?P<w>\d+)x(?P<h>\d+)\+(?P<x>-?\d+)\+(?P<y>-?\d+)$")


def parse_window_position(geometry: str) -> Optional[tuple[int, int]]:
    """Return the ``(x, y)`` screen offsets from a Tk ``geometry`` string.

    ``geometry`` is the ``"WxH+X+Y"`` value reported by ``root.geometry()``.
    Returns ``None`` when the string lacks position offsets (``"WxH"`` only) or
    cannot be parsed, so a window that has not been mapped yet is ignored.
    """

    match = _GEOMETRY_RE.match(geometry.strip())
    if match is None:
        return None
    return int(match.group("x")), int(match.group("y"))


def clamp_window_position(
    position: tuple[int, int],
    window_size: tuple[int, int],
    screen_size: tuple[int, int],
) -> Optional[tuple[int, int]]:
    """Clamp a persisted window *position* onto the visible screen.

    ``position`` is the saved ``(x, y)`` top-left offset, ``window_size`` the
    ``(width, height)`` the window will open at, and ``screen_size`` the
    ``(width, height)`` of the current screen. Returns the clamped ``(x, y)``
    keeping the window fully on-screen when it fits, or ``None`` when the saved
    position lands entirely off-screen (e.g. a disconnected monitor) so the
    caller can fall back to letting the OS place the window.
    """

    x, y = position
    width, height = window_size
    screen_width, screen_height = screen_size

    fully_offscreen = (
        x >= screen_width or y >= screen_height or x + width <= 0 or y + height <= 0
    )
    if fully_offscreen:
        return None

    clamped_x = max(0, min(x, max(0, screen_width - width)))
    clamped_y = max(0, min(y, max(0, screen_height - height)))
    return clamped_x, clamped_y


def apply_window_size(gui: "TalksReducerGUI", *, simple: bool) -> None:
    """Apply the appropriate window geometry for the current mode."""

    width, height = gui._simple_size if simple else gui._full_size
    gui.root.update_idletasks()
    gui.root.minsize(width, height)
    if simple:
        gui.root.geometry(f"{width}x{height}")
    else:
        current_width = gui.root.winfo_width()
        current_height = gui.root.winfo_height()
        if current_width < width or current_height < height:
            gui.root.geometry(f"{width}x{height}")


def apply_simple_mode(gui: "TalksReducerGUI", *, initial: bool = False) -> None:
    """Toggle between simple and full layouts."""

    simple = gui.simple_mode_var.get()
    if simple:
        gui.basic_options_frame.grid_remove()
        # The Advanced-only preset management strip has no place in Simple mode.
        if hasattr(gui, "advanced_preset_frame"):
            gui.advanced_preset_frame.grid_remove()
        gui.log_frame.grid_remove()
        # The Connected clients panel is a server-managed-only detail that has no
        # place in the minimal Simple layout.
        if hasattr(gui, "activity_frame"):
            gui.activity_frame.grid_remove()
        if hasattr(gui, "button_frame"):
            gui.button_frame.grid_remove()
        gui.advanced_frame.grid_remove()
        gui.run_after_drop_var.set(True)
        # Show the preset selector only when at least one preset exists.
        if hasattr(gui, "simple_preset_frame") and getattr(
            gui, "_simple_presets", None
        ):
            gui.simple_preset_frame.grid()
        # Cut video is an Advanced-only feature: hide its checkbox and panel.
        if hasattr(gui, "cut_check"):
            gui.cut_check.pack_forget()
        if hasattr(gui, "cut_panel"):
            gui.cut_panel.grid_remove()
        apply_window_size(gui, simple=True)
    else:
        gui.basic_options_frame.grid()
        # Restore the Advanced-only preset management strip in the full layout.
        if hasattr(gui, "advanced_preset_frame"):
            gui.advanced_preset_frame.grid()
        gui.log_frame.grid()
        # Restore the Connected clients panel only when the GUI is managed by the
        # server tray; standalone GUIs never show it.
        if hasattr(gui, "activity_frame"):
            if bool(getattr(gui, "server_managed", False)):
                gui.activity_frame.grid()
            else:
                gui.activity_frame.grid_remove()
        if hasattr(gui, "button_frame"):
            gui.button_frame.grid()
        if gui.advanced_visible.get():
            gui.advanced_frame.grid()
        if hasattr(gui, "simple_preset_frame"):
            gui.simple_preset_frame.grid_remove()
        # Restore the Advanced-only Cut video checkbox and (if enabled) its panel.
        if hasattr(gui, "cut_check"):
            gui.cut_check.pack(side=gui.tk.LEFT, padx=(65, 0))
        if hasattr(gui, "cut_panel"):
            if (
                getattr(gui, "cut_enabled_var", None) is not None
                and gui.cut_enabled_var.get()
            ):
                gui.cut_panel.grid()
            else:
                gui.cut_panel.grid_remove()
        apply_window_size(gui, simple=False)

    # The Convert button only belongs to the Advanced (non-Simple) cut workflow.
    if hasattr(gui, "_update_cut_convert_button"):
        gui._update_cut_convert_button()

    if initial and simple:
        # Ensure the hidden widgets do not retain focus outlines on start.
        gui.drop_zone.focus_set()
