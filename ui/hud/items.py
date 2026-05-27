from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class ItemState(Enum):
    ON = "on"
    OFF = "off"
    DISABLED = "disabled"


@dataclass
class HUDItem:
    label: str
    key: str
    state: ItemState = ItemState.OFF
    default_state: ItemState = ItemState.OFF
    always_show: bool = False

    def is_modified(self) -> bool:
        return self.state is not self.default_state


@dataclass
class HUDSection:
    title: str
    items: list[HUDItem] = field(default_factory=list)


# Parameter kinds for HUDParam — drive value formatting.
PARAM_KINDS = ("bool", "int", "float", "str", "enum")


@dataclass
class HUDParam:
    """One live parameter row in the HUD dashboard.

    `value_getter` is called every draw. Cheap accessors only — read an
    attribute, return it. Do not compute anything heavy in here.

    `active_getter` (optional) lets a parameter dim itself when it doesn't
    matter right now (e.g. snap distance when snap is off). Return False to
    render the row in the `disabled` style.

    `visible_getter` (optional) hides the row entirely when it returns False —
    use for parameters that should only appear once touched/active (the row is
    skipped in both measurement and drawing).
    """
    name: str
    value_getter: Callable[[], Any]
    kind: str = "str"   # one of PARAM_KINDS
    fmt: str | None = None              # float format: "{:.3f}" etc.
    active_getter: Callable[[], bool] | None = None
    visible_getter: Callable[[], bool] | None = None

    def value_text(self) -> str:
        try:
            v = self.value_getter()
        except Exception:
            return "?"
        if self.kind == "bool":
            return "✓" if v else "✗"
        if self.kind == "float":
            return (self.fmt or "{:.3f}").format(float(v))
        if self.kind == "int":
            return f"{int(v)}"
        return str(v)

    def is_active(self) -> bool:
        if self.active_getter is None:
            return True
        try:
            return bool(self.active_getter())
        except Exception:
            return True

    def is_visible(self) -> bool:
        if self.visible_getter is None:
            return True
        try:
            return bool(self.visible_getter())
        except Exception:
            return True


@dataclass
class HUDParamSection:
    title: str
    params: list[HUDParam] = field(default_factory=list)
