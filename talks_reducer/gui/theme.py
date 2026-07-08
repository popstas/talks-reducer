"""Theme utilities shared by the Tkinter GUI."""

from __future__ import annotations

import subprocess
import sys
from typing import Any, Callable, Mapping, Optional, Sequence

# Desktop Window Manager attributes that toggle the native dark title bar.
# Windows 10 20H1+ uses attribute 20; earlier 10 builds used 19.
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1 = 19

STATUS_COLORS = {
    "idle": "#9ca3af",
    "waiting": "#9ca3af",
    "processing": "#af8e0e",
    "success": "#178941",
    "error": "#ad4f4f",
    "aborted": "#6d727a",
}

LIGHT_THEME = {
    "background": "#f5f5f5",
    "foreground": "#1f2933",
    "accent": "#2563eb",
    "surface": "#ffffff",
    "border": "#cbd5e1",
    "hover": "#efefef",
    "hover_text": "#000000",
    "selection_background": "#2563eb",
    "selection_foreground": "#ffffff",
}

DARK_THEME = {
    "background": "#1e1e28",
    "foreground": "#f3f4f6",
    "accent": "#60a5fa",
    "surface": "#2b2b3c",
    "border": "#4b5563",
    "hover": "#333333",
    "hover_text": "#ffffff",
    "selection_background": "#1e1e28",
    "selection_foreground": "#f3f4f6",
}


RegistryReader = Callable[[str, str], int]
DefaultsRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def read_windows_theme_registry(key_path: str, value_name: str) -> int:
    """Read *value_name* from the registry key at *key_path*."""

    import winreg  # type: ignore

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        value, _ = winreg.QueryValueEx(key, value_name)
    return int(value)


def run_defaults_command(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Execute the macOS ``defaults`` command used to detect theme."""

    return subprocess.run(args, capture_output=True, text=True, check=False)


def detect_system_theme(
    env: Mapping[str, str],
    platform: str,
    registry_reader: RegistryReader,
    defaults_runner: DefaultsRunner,
) -> str:
    """Detect the system theme for the provided *platform* and environment."""

    if platform.startswith("win"):
        try:
            value = registry_reader(
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                "AppsUseLightTheme",
            )
            return "light" if int(value) else "dark"
        except OSError:
            return "light"

    if platform == "darwin":
        try:
            result = defaults_runner(["defaults", "read", "-g", "AppleInterfaceStyle"])
        except Exception:
            return "light"
        if result.returncode == 0 and result.stdout.strip().lower() == "dark":
            return "dark"
        return "light"

    theme = env.get("GTK_THEME", "").lower()
    if "dark" in theme:
        return "dark"
    return "light"


TitleBarSetter = Callable[[int, bool], bool]


def _default_title_bar_setter(hwnd: int, dark: bool) -> bool:
    """Toggle the native Windows title bar via the DWM API using ``ctypes``.

    Returns ``True`` when the attribute is accepted. Safe to call only on
    Windows; any missing library or API error yields ``False``.
    """

    import ctypes  # imported lazily so non-Windows platforms never load it
    import ctypes.wintypes as wintypes

    try:
        dwmapi = ctypes.windll.dwmapi  # type: ignore[attr-defined]
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return False

    # Tk wraps its top-level in a frame; the titled window is usually the
    # parent, so prefer it and fall back to the reported handle.
    top_hwnd = user32.GetParent(hwnd) or hwnd
    value = ctypes.c_int(1 if dark else 0)
    for attribute in (
        DWMWA_USE_IMMERSIVE_DARK_MODE,
        DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1,
    ):
        result = dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(top_hwnd),
            ctypes.c_int(attribute),
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
        if result == 0:
            return True
    return False


def apply_windows_title_bar_theme(
    window: Any,
    *,
    dark: bool,
    platform: Optional[str] = None,
    dwm_setter: Optional[TitleBarSetter] = None,
) -> bool:
    """Match the native window title bar to the active theme on Windows.

    This is a no-op on non-Windows platforms and whenever the window handle or
    the DWM API is unavailable, returning ``False`` in those cases and ``True``
    when the title bar attribute was applied.
    """

    resolved_platform = sys.platform if platform is None else platform
    if not resolved_platform.startswith("win"):
        return False

    try:
        hwnd = window.winfo_id()
    except Exception:
        return False

    setter = dwm_setter or _default_title_bar_setter
    try:
        return bool(setter(hwnd, bool(dark)))
    except Exception:
        return False


def apply_theme(
    style: Any,
    palette: Mapping[str, str],
    widgets: Mapping[str, Any],
) -> Mapping[str, str]:
    """Apply *palette* to *style* and update GUI *widgets*."""

    root = widgets.get("root")
    if root is not None:
        root.configure(bg=palette["background"])
        root.option_add("*TCombobox*Listbox*Background", palette["background"])
        root.option_add("*TCombobox*Listbox*Foreground", palette["foreground"])
        root.option_add(
            "*TCombobox*Listbox*selectBackground",
            palette.get("accent", palette["foreground"]),
        )
        root.option_add(
            "*TCombobox*Listbox*selectForeground",
            palette.get("selection_foreground", "#ffffff"),
        )

    style.theme_use("clam")
    style.configure(
        ".", background=palette["background"], foreground=palette["foreground"]
    )
    style.configure("TFrame", background=palette["background"])
    style.configure(
        "TLabelframe",
        background=palette["background"],
        foreground=palette["foreground"],
        borderwidth=0,
        relief="flat",
    )
    style.configure(
        "TLabelframe.Label",
        background=palette["background"],
        foreground=palette["foreground"],
    )
    style.configure(
        "TLabel", background=palette["background"], foreground=palette["foreground"]
    )
    style.configure(
        "TCheckbutton",
        background=palette["background"],
        foreground=palette["foreground"],
    )
    style.map(
        "TCheckbutton",
        background=[("active", palette.get("hover", palette["background"]))],
    )
    style.configure(
        "TRadiobutton",
        background=palette["background"],
        foreground=palette["foreground"],
    )
    style.map(
        "TRadiobutton",
        background=[("active", palette.get("hover", palette["background"]))],
    )
    style.configure(
        "Link.TButton",
        background=palette["background"],
        foreground=palette["accent"],
        borderwidth=0,
        relief="flat",
        highlightthickness=0,
        padding=2,
        font=("TkDefaultFont", 8, "underline"),
    )
    style.map(
        "Link.TButton",
        background=[
            ("active", palette.get("hover", palette["background"])),
            ("disabled", palette["background"]),
        ],
        foreground=[
            ("active", palette.get("accent", palette["foreground"])),
            ("disabled", palette["foreground"]),
        ],
    )
    selected_background = palette.get("accent", palette["foreground"])
    selected_foreground = palette.get("selection_foreground", "#ffffff")
    style.configure(
        "SelectedLink.TButton",
        background=selected_background,
        foreground=selected_foreground,
        borderwidth=0,
        relief="flat",
        highlightthickness=0,
        padding=2,
        font=("TkDefaultFont", 8, "underline"),
        cursor="hand2",
    )
    style.map(
        "SelectedLink.TButton",
        background=[
            ("disabled", selected_background),
        ],
        foreground=[
            ("disabled", selected_foreground),
        ],
    )
    style.configure(
        "TButton",
        background=palette["surface"],
        foreground=palette["foreground"],
        padding=4,
        font=("TkDefaultFont", 8),
    )
    style.map(
        "TButton",
        background=[
            ("active", palette.get("hover", palette["accent"])),
            ("disabled", palette["surface"]),
        ],
        foreground=[
            ("active", palette.get("hover_text", "#000000")),
            ("disabled", palette["foreground"]),
        ],
    )
    style.configure(
        "TEntry",
        fieldbackground=palette["background"],
        foreground=palette["foreground"],
    )
    combobox_hover = palette.get("hover", palette["surface"])
    style.configure(
        "TCombobox",
        fieldbackground=palette["background"],
        background=palette["surface"],
        foreground=palette["foreground"],
        arrowcolor=palette["foreground"],
    )
    style.map(
        "TCombobox",
        fieldbackground=[
            ("readonly", palette["background"]),
            ("readonly", "focus", palette["background"]),
        ],
        # The readonly combobox draws its face (behind the text and the arrow)
        # with ``background`` rather than ``fieldbackground``. Without these
        # entries clam lightens that face on hover/press, so a dark theme would
        # flash a pale button while the dropdown expands.
        background=[
            ("readonly", "hover", combobox_hover),
            ("readonly", "active", combobox_hover),
            ("readonly", "pressed", combobox_hover),
            ("hover", combobox_hover),
            ("active", combobox_hover),
            ("pressed", combobox_hover),
            ("readonly", palette["surface"]),
            ("disabled", palette["surface"]),
        ],
        foreground=[
            ("readonly", palette["foreground"]),
            ("readonly", "focus", palette["foreground"]),
        ],
        arrowcolor=[
            ("active", palette["foreground"]),
            ("pressed", palette["foreground"]),
            ("disabled", palette["border"]),
        ],
    )

    style.configure(
        "Idle.Horizontal.TProgressbar",
        background=STATUS_COLORS["idle"],
        troughcolor=palette["surface"],
        borderwidth=0,
        thickness=20,
    )
    style.configure(
        "Processing.Horizontal.TProgressbar",
        background=STATUS_COLORS["processing"],
        troughcolor=palette["surface"],
        borderwidth=0,
        thickness=20,
    )
    style.configure(
        "Success.Horizontal.TProgressbar",
        background=STATUS_COLORS["success"],
        troughcolor=palette["surface"],
        borderwidth=0,
        thickness=20,
    )
    style.configure(
        "Error.Horizontal.TProgressbar",
        background=STATUS_COLORS["error"],
        troughcolor=palette["surface"],
        borderwidth=0,
        thickness=20,
    )
    style.configure(
        "Aborted.Horizontal.TProgressbar",
        background=STATUS_COLORS["aborted"],
        troughcolor=palette["surface"],
        borderwidth=0,
        thickness=20,
    )

    drop_zone = widgets.get("drop_zone")
    if drop_zone is not None:
        drop_zone.configure(
            bg=palette["surface"],
            fg=palette["foreground"],
            highlightthickness=0,
        )

    tk_module = widgets.get("tk")
    slider_relief = getattr(tk_module, "FLAT", "flat") if tk_module else "flat"
    sliders = widgets.get("sliders") or []
    for slider in sliders:
        slider.configure(
            background=palette["border"],
            troughcolor=palette["surface"],
            activebackground=palette["border"],
            sliderrelief=slider_relief,
            bd=0,
        )

    # The log and the Connected clients panels share the same read-only text box
    # styling so the server-managed activity log matches the main log area.
    for text_key in ("log_text", "activity_text"):
        text_widget = widgets.get(text_key)
        if text_widget is not None:
            text_widget.configure(
                bg=palette["surface"],
                fg=palette["foreground"],
                insertbackground=palette["foreground"],
                highlightbackground=palette["border"],
                highlightcolor=palette["border"],
            )

    status_label = widgets.get("status_label")
    if status_label is not None:
        status_label.configure(bg=palette["background"])

    apply_status_style = widgets.get("apply_status_style")
    status_state = widgets.get("status_state")
    if callable(apply_status_style) and status_state is not None:
        apply_status_style(status_state)

    return palette
