"""A button-based choice control for settings with a handful of values.

The module is deliberately split in two: the dataclasses and helpers below are
pure Python and carry the value semantics, while :class:`SegmentedChoice` is a
thin Tk shell over them. ``tk``/``ttk`` are injected rather than imported so the
control can be exercised with widget stubs in tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Union

TOLERANCE = 1e-9

Value = Union[float, str]


@dataclass(frozen=True)
class Option:
    """A single selectable value with its button label and optional tooltip."""

    value: Value
    label: str
    tooltip: Optional[str] = None


@dataclass(frozen=True)
class CustomSpec:
    """Bounds and formatting for values typed into the ``...`` slot."""

    minimum: float
    maximum: float
    display_format: str = "{:g}"


def resolve_selection(value: Value, options: Sequence[Option]) -> Optional[int]:
    """Return the index of the option matching *value*, or ``None``.

    Numeric options compare within :data:`TOLERANCE` so a float that survived a
    round-trip through ``settings.json`` still matches its button. ``None`` means
    the value belongs in the custom slot rather than on a preset button.
    """

    for index, option in enumerate(options):
        if isinstance(option.value, str):
            if str(value) == option.value:
                return index
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if abs(numeric - float(option.value)) <= TOLERANCE:
            return index
    return None


def parse_custom(text: str, spec: CustomSpec) -> float:
    """Parse *text* into a value clamped to *spec*'s bounds.

    Raises ``ValueError`` when the text is blank or not a number, letting the
    caller cancel the edit rather than write nonsense into the bound variable.
    """

    stripped = str(text).strip()
    if not stripped:
        raise ValueError("empty custom value")
    numeric = float(stripped)
    return max(spec.minimum, min(spec.maximum, numeric))


def format_custom_label(value: float, spec: CustomSpec) -> str:
    """Return the button label for a committed custom *value*."""

    return spec.display_format.format(value)
