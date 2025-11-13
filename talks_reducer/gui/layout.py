"""Layout helpers for the Talks Reducer GUI."""

from __future__ import annotations

import math
import sys
from typing import TYPE_CHECKING, Callable

from ..icons import find_icon_path
from ..models import default_temp_folder

if TYPE_CHECKING:  # pragma: no cover - imported for type checking only
    import tkinter as tk

    from .app import TalksReducerGUI


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

    # Options frame
    gui.options_frame = gui.ttk.Frame(main, padding=gui.PADDING)
    gui.options_frame.grid(row=2, column=0, pady=(0, 0), sticky="ew")
    gui.options_frame.columnconfigure(0, weight=1)

    checkbox_frame = gui.ttk.Frame(gui.options_frame)
    checkbox_frame.grid(row=0, column=0, columnspan=2, sticky="w")

    gui.ttk.Checkbutton(
        checkbox_frame,
        text="Small video",
        variable=gui.small_var,
    ).grid(row=0, column=0, sticky="w")

    gui.small_480_check = gui.ttk.Checkbutton(
        checkbox_frame,
        text="480p",
        variable=gui.small_480_var,
    )
    gui.small_480_check.grid(row=0, column=1, sticky="w", padx=(12, 0))

    gui.ttk.Checkbutton(
        checkbox_frame,
        text="Open after convert",
        variable=gui.open_after_convert_var,
    ).grid(row=0, column=2, sticky="w", padx=(12, 0))

    gui.simple_mode_check = gui.ttk.Checkbutton(
        checkbox_frame,
        text="Simple mode",
        variable=gui.simple_mode_var,
        command=gui._toggle_simple_mode,
    )
    gui.simple_mode_check.grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))

    gui.advanced_visible = gui.tk.BooleanVar(value=False)

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
        row=1, column=0, columnspan=2, sticky="ew", pady=(12, 0)
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
    gui.server_discover_button.grid(row=5, column=2, padx=(8, 0))

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

    gui.advanced_button = gui.ttk.Button(
        gui.options_frame,
        text="Advanced",
        command=gui._toggle_advanced,
    )
    gui.advanced_button.grid(row=2, column=0, columnspan=2, sticky="w", pady=(12, 0))

    gui.advanced_frame = gui.ttk.Frame(gui.options_frame, padding=0)
    gui.advanced_frame.grid(row=3, column=0, columnspan=2, sticky="nsew")
    gui.advanced_frame.columnconfigure(1, weight=1)

    gui.output_var = gui.tk.StringVar()
    add_entry(
        gui,
        gui.advanced_frame,
        "Output file",
        gui.output_var,
        row=0,
        browse=True,
    )

    gui.temp_var = gui.tk.StringVar(value=str(default_temp_folder()))
    add_entry(
        gui,
        gui.advanced_frame,
        "Temp folder",
        gui.temp_var,
        row=1,
        browse=True,
    )

    gui.optimize_check = gui.ttk.Checkbutton(
        gui.advanced_frame,
        text="Optimized encoding",
        variable=gui.optimize_var,
    )
    gui.optimize_check.grid(row=2, column=0, columnspan=3, sticky="w", pady=4)

    global_ffmpeg_available = getattr(gui, "global_ffmpeg_available", True)
    gui.use_global_ffmpeg_check = gui.ttk.Checkbutton(
        gui.advanced_frame,
        text="Use global FFmpeg",
        variable=gui.use_global_ffmpeg_var,
        state=gui.tk.NORMAL if global_ffmpeg_available else gui.tk.DISABLED,
    )
    if not global_ffmpeg_available:
        gui.use_global_ffmpeg_var.set(False)
    gui.use_global_ffmpeg_check.grid(row=3, column=0, columnspan=3, sticky="w", pady=4)

    gui.sample_rate_var = gui.tk.StringVar(value="48000")
    add_entry(gui, gui.advanced_frame, "Sample rate", gui.sample_rate_var, row=4)

    frame_margin_setting = gui.preferences.get("frame_margin", 2)
    try:
        frame_margin_default = int(frame_margin_setting)
    except (TypeError, ValueError):
        frame_margin_default = 2
        gui.preferences.update("frame_margin", frame_margin_default)

    gui.frame_margin_var = gui.tk.StringVar(value=str(frame_margin_default))
    add_entry(gui, gui.advanced_frame, "Frame margin", gui.frame_margin_var, row=5)

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
        row=6, column=0, sticky="w", pady=4
    )

    gui.keyframe_interval_var = gui.tk.DoubleVar(value=validated_interval)

    gui.keyframe_interval_value_label = gui.ttk.Label(gui.advanced_frame)
    gui.keyframe_interval_value_label.grid(row=6, column=2, sticky="e", pady=4)

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
    gui.keyframe_interval_slider.grid(row=6, column=1, sticky="ew", pady=4, padx=(0, 8))

    update_keyframe_interval(str(validated_interval))
    sliders = getattr(gui, "_sliders", None)
    if isinstance(sliders, list):
        sliders.append(gui.keyframe_interval_slider)

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
        gui.log_frame.grid_remove()
        gui.advanced_button.grid_remove()
        gui.advanced_frame.grid_remove()
        gui.run_after_drop_var.set(True)
        apply_window_size(gui, simple=True)
    else:
        gui.basic_options_frame.grid()
        gui.log_frame.grid()
        gui.advanced_button.grid()
        if gui.advanced_visible.get():
            gui.advanced_frame.grid()
        apply_window_size(gui, simple=False)

    if initial and simple:
        # Ensure the hidden widgets do not retain focus outlines on start.
        gui.drop_zone.focus_set()
