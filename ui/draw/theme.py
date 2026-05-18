from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
import bpy


class Role(Enum):
    # Three primitives, each with 5 states.
    POINT = "point"
    CLOSEST_POINT = "closest_point"
    ACTIVE_POINT = "active_point"
    LOCKED_POINT = "locked_point"
    PREVIEW_POINT = "preview_point"

    LINE = "line"
    CLOSEST_LINE = "closest_line"
    ACTIVE_LINE = "active_line"
    LOCKED_LINE = "locked_line"
    PREVIEW_LINE = "preview_line"

    TEXT = "text"
    CLOSEST_TEXT = "closest_text"
    ACTIVE_TEXT = "active_text"
    LOCKED_TEXT = "locked_text"
    PREVIEW_TEXT = "preview_text"

    # Utility / surface (no per-state variants).
    FILL = "fill"
    POINT_OUTLINE = "point_outline"
    ERROR = "error"
    SUCCESS = "success"

    # Widgets (no per-state variants).
    HANDLE = "handle"
    HANDLE_HOVER = "handle_hover"
    PIVOT = "pivot"
    BBOX = "bbox"
    CURSOR = "cursor"

    # HUD-specific.
    HUD_KEY = "hud_key"
    HUD_LABEL_ON = "hud_label_on"
    HUD_LABEL_OFF = "hud_label_off"
    HUD_LABEL_DISABLED = "hud_label_disabled"


STATES = ("default", "closest", "active", "locked", "preview")


def state_from_role(role: Role) -> str:
    name = role.value
    for s in ("closest", "active", "locked", "preview"):
        if name.startswith(s + "_") or name == s:
            return s
    return "default"


_C_CYAN  = (0.302, 0.816, 1.000)
_C_GREEN = (0.302, 1.000, 0.620)
_C_AMBER = (1.000, 0.722, 0.302)
_C_RED   = (1.000, 0.353, 0.353)
_C_WHITE = (1.000, 1.000, 1.000)

_DEFAULT_COLORS: dict[Role, tuple[float, float, float, float]] = {
    Role.POINT:          (*_C_WHITE, 0.70),
    Role.CLOSEST_POINT:  (*_C_GREEN, 1.00),
    Role.ACTIVE_POINT:   (*_C_CYAN,  1.00),
    Role.LOCKED_POINT:   (*_C_AMBER, 1.00),
    Role.PREVIEW_POINT:  (*_C_CYAN,  0.50),

    Role.LINE:           (*_C_WHITE, 0.60),
    Role.CLOSEST_LINE:   (*_C_GREEN, 1.00),
    Role.ACTIVE_LINE:    (*_C_CYAN,  1.00),
    Role.LOCKED_LINE:    (*_C_AMBER, 1.00),
    Role.PREVIEW_LINE:   (*_C_CYAN,  0.50),

    Role.TEXT:           (*_C_WHITE, 1.00),
    Role.CLOSEST_TEXT:   (*_C_GREEN, 1.00),
    Role.ACTIVE_TEXT:    (*_C_CYAN,  1.00),
    Role.LOCKED_TEXT:    (*_C_AMBER, 1.00),
    Role.PREVIEW_TEXT:   (*_C_CYAN,  0.85),

    Role.FILL:           (*_C_CYAN,  0.10),
    Role.POINT_OUTLINE:  (0.000, 0.000, 0.000, 1.00),
    Role.ERROR:          (*_C_RED,   1.00),
    Role.SUCCESS:        (*_C_GREEN, 1.00),

    Role.HANDLE:        (1.000, 1.000, 1.000, 0.85),
    Role.HANDLE_HOVER:  (1.000, 0.850, 0.000, 1.00),
    Role.PIVOT:         (1.000, 1.000, 1.000, 0.80),
    Role.BBOX:          (0.650, 0.650, 0.650, 0.30),
    Role.CURSOR:        (1.000, 0.200, 0.600, 1.00),

    Role.HUD_KEY:        (*_C_AMBER, 1.00),
    Role.HUD_LABEL_ON:   (1.000, 1.000, 1.000, 1.00),
    Role.HUD_LABEL_OFF:  (0.533, 0.541, 0.557, 0.85),
    Role.HUD_LABEL_DISABLED: (0.220, 0.220, 0.235, 0.85),
}

_DEFAULT_POINT_SIZES = {
    "default": 7.0, "closest": 12.0, "active": 10.0,
    "locked": 10.0, "preview": 8.0,
}
_DEFAULT_LINE_WIDTHS = {
    "default": 1.5, "closest": 2.5, "active": 2.5,
    "locked": 3.0, "preview": 2.0,
}
_DEFAULT_TEXT_SIZES = {
    "default": 12, "closest": 13, "active": 14,
    "locked": 14, "preview": 12,
}

_DEFAULT_ISLAND_PALETTE = (
    (0.40, 0.65, 1.00, 0.50),
    (1.00, 0.50, 0.30, 0.50),
    (0.35, 0.85, 0.45, 0.50),
    (0.95, 0.80, 0.25, 0.50),
    (0.70, 0.40, 0.90, 0.50),
    (0.20, 0.80, 0.75, 0.50),
    (0.90, 0.35, 0.60, 0.50),
    (0.60, 0.80, 0.20, 0.50),
)


@dataclass(frozen=True)
class HUDSettings:
    mode: str = "cursor"
    offset_x: int = 20
    offset_y: int = -20
    free_x: int = 40
    free_y: int = 40
    padding: int = 12
    section_spacing: int = 8
    row_spacing: int = 2
    key_column_width: int = 60
    verbosity: str = "compact"


@dataclass(frozen=True)
class ShadowSettings:
    enabled: bool = True
    color: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.7)
    blur: int = 3
    offset_x: int = 1
    offset_y: int = -1


@dataclass(frozen=True)
class Theme:
    colors: dict[Role, tuple[float, float, float, float]] = field(
        default_factory=lambda: dict(_DEFAULT_COLORS))
    point_sizes: dict[str, float] = field(
        default_factory=lambda: dict(_DEFAULT_POINT_SIZES))
    line_widths: dict[str, float] = field(
        default_factory=lambda: dict(_DEFAULT_LINE_WIDTHS))
    text_sizes: dict[str, int] = field(
        default_factory=lambda: dict(_DEFAULT_TEXT_SIZES))
    shadow: ShadowSettings = field(default_factory=ShadowSettings)
    hud: HUDSettings = field(default_factory=HUDSettings)
    depth_test_default: str = "LESS"
    island_palette: tuple[tuple[float, float, float, float], ...] = field(
        default_factory=lambda: _DEFAULT_ISLAND_PALETTE)

    def color_for(self, role: Role) -> tuple[float, float, float, float]:
        return self.colors[role]

    def point_size_for(self, role: Role) -> float:
        return self.point_sizes[state_from_role(role)]

    def line_width_for(self, role: Role) -> float:
        return self.line_widths[state_from_role(role)]

    def text_size_for(self, role: Role) -> int:
        return self.text_sizes[state_from_role(role)]

    def point_size(self, token: str) -> float:
        return self.point_sizes[token]

    def width(self, token: str) -> float:
        return self.line_widths[token]

    def text_size(self, token: str) -> int:
        # Back-compat aliases used by HUD/text helpers.
        token = {"small": "default", "normal": "default",
                 "title": "active"}.get(token, token)
        return self.text_sizes[token]


def get_theme(context) -> "Theme":
    try:
        t = context.preferences.addons["InteractionOps"].preferences.iops_theme
    except (KeyError, AttributeError):
        return DEFAULT_THEME

    def c(name, fallback):
        return tuple(getattr(t, name, fallback))

    def fl(name, fallback):
        return float(getattr(t, name, fallback))

    def i(name, fallback):
        return int(getattr(t, name, fallback))

    return Theme(
        colors={
            Role.POINT:              c("color_point",          _DEFAULT_COLORS[Role.POINT]),
            Role.CLOSEST_POINT:      c("color_closest_point",  _DEFAULT_COLORS[Role.CLOSEST_POINT]),
            Role.ACTIVE_POINT:       c("color_active_point",   _DEFAULT_COLORS[Role.ACTIVE_POINT]),
            Role.LOCKED_POINT:       c("color_locked_point",   _DEFAULT_COLORS[Role.LOCKED_POINT]),
            Role.PREVIEW_POINT:      c("color_preview_point",  _DEFAULT_COLORS[Role.PREVIEW_POINT]),

            Role.LINE:               c("color_line",           _DEFAULT_COLORS[Role.LINE]),
            Role.CLOSEST_LINE:       c("color_closest_line",   _DEFAULT_COLORS[Role.CLOSEST_LINE]),
            Role.ACTIVE_LINE:        c("color_active_line",    _DEFAULT_COLORS[Role.ACTIVE_LINE]),
            Role.LOCKED_LINE:        c("color_locked_line",    _DEFAULT_COLORS[Role.LOCKED_LINE]),
            Role.PREVIEW_LINE:       c("color_preview_line",   _DEFAULT_COLORS[Role.PREVIEW_LINE]),

            Role.TEXT:               c("color_text",           _DEFAULT_COLORS[Role.TEXT]),
            Role.CLOSEST_TEXT:       c("color_closest_text",   _DEFAULT_COLORS[Role.CLOSEST_TEXT]),
            Role.ACTIVE_TEXT:        c("color_active_text",    _DEFAULT_COLORS[Role.ACTIVE_TEXT]),
            Role.LOCKED_TEXT:        c("color_locked_text",    _DEFAULT_COLORS[Role.LOCKED_TEXT]),
            Role.PREVIEW_TEXT:       c("color_preview_text",   _DEFAULT_COLORS[Role.PREVIEW_TEXT]),

            Role.FILL:               c("color_fill",           _DEFAULT_COLORS[Role.FILL]),
            Role.POINT_OUTLINE:      c("color_point_outline",  _DEFAULT_COLORS[Role.POINT_OUTLINE]),
            Role.ERROR:              c("color_error",          _DEFAULT_COLORS[Role.ERROR]),
            Role.SUCCESS:            c("color_success",        _DEFAULT_COLORS[Role.SUCCESS]),

            Role.HANDLE:             c("color_handle",         _DEFAULT_COLORS[Role.HANDLE]),
            Role.HANDLE_HOVER:       c("color_handle_hover",   _DEFAULT_COLORS[Role.HANDLE_HOVER]),
            Role.PIVOT:              c("color_pivot",          _DEFAULT_COLORS[Role.PIVOT]),
            Role.BBOX:               c("color_bbox",           _DEFAULT_COLORS[Role.BBOX]),
            Role.CURSOR:             c("color_cursor",         _DEFAULT_COLORS[Role.CURSOR]),

            Role.HUD_KEY:            c("color_hud_key",         _DEFAULT_COLORS[Role.HUD_KEY]),
            Role.HUD_LABEL_ON:       c("color_hud_label_on",    _DEFAULT_COLORS[Role.HUD_LABEL_ON]),
            Role.HUD_LABEL_OFF:      c("color_hud_label_off",   _DEFAULT_COLORS[Role.HUD_LABEL_OFF]),
            Role.HUD_LABEL_DISABLED: c("color_hud_label_disabled", _DEFAULT_COLORS[Role.HUD_LABEL_DISABLED]),
        },
        point_sizes={s: fl(f"point_size_{s}", _DEFAULT_POINT_SIZES[s]) for s in STATES},
        line_widths={s: fl(f"line_width_{s}", _DEFAULT_LINE_WIDTHS[s]) for s in STATES},
        text_sizes={s: i(f"text_size_{s}", _DEFAULT_TEXT_SIZES[s]) for s in STATES},
        shadow=ShadowSettings(
            enabled=bool(t.shadow_enabled),
            color=tuple(t.shadow_color),
            blur=int(t.shadow_blur),
            offset_x=int(t.shadow_offset_x),
            offset_y=int(t.shadow_offset_y),
        ),
        hud=HUDSettings(
            mode=str(t.hud_mode),
            offset_x=int(t.hud_offset_x),
            offset_y=int(t.hud_offset_y),
            free_x=int(t.hud_free_x),
            free_y=int(t.hud_free_y),
            padding=int(t.hud_padding),
            section_spacing=int(t.hud_section_spacing),
            row_spacing=int(t.hud_row_spacing),
            key_column_width=int(t.hud_key_column_width),
            verbosity=str(getattr(t, "hud_verbosity", "compact")),
        ),
        depth_test_default=str(t.depth_test_default),
        island_palette=tuple(
            tuple(getattr(t, f"island_palette_{i}", _DEFAULT_ISLAND_PALETTE[i]))
            for i in range(8)
        ),
    )


DEFAULT_THEME = Theme()


_AXIS_FALLBACK = {
    "X": (1.0, 0.27, 0.27, 1.0),
    "Y": (0.27, 0.75, 0.27, 1.0),
    "Z": (0.27, 0.27, 1.00, 1.0),
}


def axis_color(axis: str) -> tuple[float, float, float, float]:
    """Return Blender's built-in axis_x/y/z color with alpha=1.0.

    Falls back to canonical red/green/blue if user_interface theme is
    unavailable (e.g. headless contexts where themes[0] is missing the
    axis attrs).
    """
    try:
        ui = bpy.context.preferences.themes[0].user_interface
        src = {"X": ui.axis_x, "Y": ui.axis_y, "Z": ui.axis_z}[axis]
        return (src[0], src[1], src[2], 1.0)
    except (KeyError, AttributeError, IndexError):
        return _AXIS_FALLBACK[axis]
