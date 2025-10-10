"""Theme utilities shared by the Tkinter GUI."""

from __future__ import annotations

import subprocess
from typing import Any, Callable, Mapping, Sequence

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
    "selection_background": "#333333",
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


def apply_theme(
    style: Any,
    palette: Mapping[str, str],
    widgets: Mapping[str, Any],
) -> Mapping[str, str]:
    """Apply *palette* to *style* and update GUI *widgets*."""

    root = widgets.get("root")
    if root is not None:
        root.configure(bg=palette["background"])

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
        fieldbackground=palette["surface"],
        foreground=palette["foreground"],
    )
    style.configure(
        "TCombobox",
        fieldbackground=palette["surface"],
        foreground=palette["foreground"],
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

    log_text = widgets.get("log_text")
    if log_text is not None:
        log_text.configure(
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
