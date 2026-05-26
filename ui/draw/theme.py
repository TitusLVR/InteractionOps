from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
import bpy


class Role(Enum):
    # Three primitives, each with 6 states.
    POINT = "point"
    CLOSEST_POINT = "closest_point"
    ACTIVE_POINT = "active_point"
    LOCKED_POINT = "locked_point"
    PREVIEW_POINT = "preview_point"
    ERROR_POINT = "error_point"

    LINE = "line"
    CLOSEST_LINE = "closest_line"
    ACTIVE_LINE = "active_line"
    LOCKED_LINE = "locked_line"
    PREVIEW_LINE = "preview_line"
    ERROR_LINE = "error_line"

    # Utility (no per-state variants).
    POINT_OUTLINE = "point_outline"

    # Widgets (no per-state variants).
    HANDLE = "handle"
    HANDLE_HOVER = "handle_hover"
    PIVOT = "pivot"
    BBOX = "bbox"
    CURSOR = "cursor"

    # Ghost / Surfaces — highlighted faces and ghost-preview wireframes.
    GHOST_EDGE = "ghost_edge"
    GHOST_DEFAULT = "ghost_default"

    # HUD text — the only text styles used anywhere in the addon.
    HUD_HEADER = "hud_header"
    HUD_KEY = "hud_key"
    HUD_LABEL = "hud_label"
    HUD_LABEL_ACTIVE = "hud_label_active"
    HUD_LABEL_INACTIVE = "hud_label_inactive"
    HUD_ACTIVE_VALUE = "hud_active_value"
    HUD_STATS_ERROR = "hud_stats_error"


STATES = ("default", "closest", "active", "locked", "preview", "error")


def state_from_role(role: Role) -> str:
    name = role.value
    for s in ("closest", "active", "locked", "preview", "error"):
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
    Role.ERROR_POINT:    (*_C_RED,   1.00),

    Role.LINE:           (0.650, 0.650, 0.650, 0.30),
    Role.CLOSEST_LINE:   (*_C_GREEN, 0.85),
    Role.ACTIVE_LINE:    (*_C_CYAN,  0.90),
    Role.LOCKED_LINE:    (*_C_AMBER, 0.95),
    Role.PREVIEW_LINE:   (*_C_CYAN,  0.50),
    Role.ERROR_LINE:     (*_C_RED,   1.00),

    Role.POINT_OUTLINE:  (0.000, 0.000, 0.000, 1.00),

    Role.HANDLE:        (1.000, 1.000, 1.000, 0.85),
    Role.HANDLE_HOVER:  (0.302, 0.816, 1.000, 0.90),
    Role.PIVOT:         (1.000, 0.872, 0.174, 0.90),
    Role.BBOX:          (0.650, 0.650, 0.650, 0.30),
    Role.CURSOR:        (1.000, 0.200, 0.600, 1.00),

    Role.GHOST_EDGE:    (0.000, 0.000, 0.000, 0.349),  # #00000059
    Role.GHOST_DEFAULT: (0.851, 0.851, 0.851, 0.149),  # #D9D9D926

    Role.HUD_HEADER:         (0.302, 1.000, 0.620, 0.75),
    Role.HUD_LABEL_ACTIVE:   (0.302, 1.000, 0.620, 0.75),
    Role.HUD_KEY:            (1.000, 0.872, 0.174, 0.75),
    Role.HUD_ACTIVE_VALUE:   (1.000, 0.872, 0.174, 0.75),
    Role.HUD_LABEL:          (0.844, 0.844, 0.844, 0.75),
    Role.HUD_LABEL_INACTIVE: (0.466, 0.473, 0.487, 0.85),
    Role.HUD_STATS_ERROR:    (1.000, 0.339, 0.382, 0.90),
}

_DEFAULT_POINT_SIZES = {
    "default": 8.0, "closest": 11.0, "active": 12.0,
    "locked": 13.0, "preview": 10.0, "error": 13.0,
}
_DEFAULT_LINE_WIDTHS = {
    "default": 1.5, "closest": 2.5, "active": 2.5,
    "locked": 3.0, "preview": 2.0, "error": 2.5,
}
_DEFAULT_TEXT_SIZES = {
    "hud_header": 13,
    "hud_key":    11,
    "hud_label":  11,
    "stats":      11,
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
    anchor_offset_x: int = 0
    anchor_offset_y: int = 0
    free_x: int = 40
    free_y: int = 40
    padding: int = 12
    section_spacing: int = 8
    row_spacing: int = 2
    key_label_spacing: int = 16
    smoothing: float = 0.70
    bg_enabled: bool = True
    bg_color: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.25)
    bg_padding: int = 10


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
    # Custom font file path (TTF/OTF). Empty string = Blender's default font.
    font_path: str = ""
    # Statistics overlay anchor (top-left of the 3D view, in pixels).
    stats_offset_x: int = 8
    stats_offset_y: int = 220
    stats_row_spacing: float = 1.5
    stats_column_spacing: float = 5.0
    # Per-widget sizes (don't follow the 5-state default/closest/... split).
    point_size_handle: float = 8.0
    point_size_handle_hover: float = 10.0
    point_size_pivot: float = 12.0
    point_size_cursor: float = 8.0
    line_width_bbox: float = 1.5

    def color_for(self, role: Role) -> tuple[float, float, float, float]:
        return self.colors[role]

    def point_size_for(self, role: Role) -> float:
        # Widget roles bypass the state map — each widget has its own size.
        if role is Role.HANDLE:
            return self.point_size_handle
        if role is Role.HANDLE_HOVER:
            return self.point_size_handle_hover
        if role is Role.PIVOT:
            return self.point_size_pivot
        if role is Role.CURSOR:
            return self.point_size_cursor
        return self.point_sizes[state_from_role(role)]

    def line_width_for(self, role: Role) -> float:
        if role is Role.BBOX:
            return self.line_width_bbox
        return self.line_widths[state_from_role(role)]

    def text_size_for(self, role: Role) -> int:
        # All HUD text styles map to one of three size sliders:
        # Header for HUD_HEADER, Glyph for HUD_KEY, Label for everything
        # else. Stats has its own dedicated size.
        if role is Role.HUD_HEADER:
            return self.text_sizes["hud_header"]
        if role is Role.HUD_KEY:
            return self.text_sizes["hud_key"]
        return self.text_sizes["hud_label"]

    def point_size(self, token: str) -> float:
        return self.point_sizes[token]

    def width(self, token: str) -> float:
        return self.line_widths[token]

    def text_size(self, token: str) -> int:
        # Three HUD text-size sliders: Header, Glyph, Label. Stats has
        # its own dedicated size. Any legacy/generic token collapses to
        # the Label size so old call sites keep rendering.
        if token == "hud_header" or token == "title":
            return self.text_sizes["hud_header"]
        if token == "hud_key":
            return self.text_sizes["hud_key"]
        if token == "stats":
            return self.text_sizes["stats"]
        # "hud_label", "normal", "small", "default", and any other
        # legacy token fall back to the Label slider.
        return self.text_sizes["hud_label"]


def get_theme(context) -> "Theme":
    try:
        prefs = context.preferences.addons["InteractionOps"].preferences
        t = prefs.iops_theme
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
            Role.ERROR_POINT:        c("color_error_point",    _DEFAULT_COLORS[Role.ERROR_POINT]),

            Role.LINE:               c("color_line",           _DEFAULT_COLORS[Role.LINE]),
            Role.CLOSEST_LINE:       c("color_closest_line",   _DEFAULT_COLORS[Role.CLOSEST_LINE]),
            Role.ACTIVE_LINE:        c("color_active_line",    _DEFAULT_COLORS[Role.ACTIVE_LINE]),
            Role.LOCKED_LINE:        c("color_locked_line",    _DEFAULT_COLORS[Role.LOCKED_LINE]),
            Role.PREVIEW_LINE:       c("color_preview_line",   _DEFAULT_COLORS[Role.PREVIEW_LINE]),
            Role.ERROR_LINE:         c("color_error_line",     _DEFAULT_COLORS[Role.ERROR_LINE]),

            Role.POINT_OUTLINE:      c("color_point_outline",  _DEFAULT_COLORS[Role.POINT_OUTLINE]),

            Role.HANDLE:             c("color_handle",         _DEFAULT_COLORS[Role.HANDLE]),
            Role.HANDLE_HOVER:       c("color_handle_hover",   _DEFAULT_COLORS[Role.HANDLE_HOVER]),
            Role.PIVOT:              c("color_pivot",          _DEFAULT_COLORS[Role.PIVOT]),
            Role.BBOX:               c("color_bbox",           _DEFAULT_COLORS[Role.BBOX]),
            Role.CURSOR:             c("color_cursor",         _DEFAULT_COLORS[Role.CURSOR]),

            Role.GHOST_EDGE:         c("color_ghost_edge",     _DEFAULT_COLORS[Role.GHOST_EDGE]),
            Role.GHOST_DEFAULT:      c("color_ghost_default",  _DEFAULT_COLORS[Role.GHOST_DEFAULT]),

            # HUD_HEADER + HUD_LABEL_ACTIVE share `color_hud_header`.
            # HUD_KEY    + HUD_ACTIVE_VALUE share `color_hud_key`.
            Role.HUD_HEADER:         c("color_hud_header",         _DEFAULT_COLORS[Role.HUD_HEADER]),
            Role.HUD_LABEL_ACTIVE:   c("color_hud_header",         _DEFAULT_COLORS[Role.HUD_HEADER]),
            Role.HUD_KEY:            c("color_hud_key",            _DEFAULT_COLORS[Role.HUD_KEY]),
            Role.HUD_ACTIVE_VALUE:   c("color_hud_key",            _DEFAULT_COLORS[Role.HUD_KEY]),
            Role.HUD_LABEL:          c("color_hud_label",          _DEFAULT_COLORS[Role.HUD_LABEL]),
            Role.HUD_LABEL_INACTIVE: c("color_hud_label_inactive", _DEFAULT_COLORS[Role.HUD_LABEL_INACTIVE]),
            Role.HUD_STATS_ERROR:    c("color_hud_stats_error",    _DEFAULT_COLORS[Role.HUD_STATS_ERROR]),
        },
        point_sizes={s: fl(f"point_size_{s}", _DEFAULT_POINT_SIZES[s]) for s in STATES},
        line_widths={s: fl(f"line_width_{s}", _DEFAULT_LINE_WIDTHS[s]) for s in STATES},
        text_sizes={
            "hud_header": i("text_size_hud_header", _DEFAULT_TEXT_SIZES["hud_header"]),
            "hud_key":    i("text_size_hud_key",    _DEFAULT_TEXT_SIZES["hud_key"]),
            "hud_label":  i("text_size_hud_label",  _DEFAULT_TEXT_SIZES["hud_label"]),
            "stats":      i("stats_text_size",      _DEFAULT_TEXT_SIZES["stats"]),
        },
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
            anchor_offset_x=int(t.hud_anchor_offset_x),
            anchor_offset_y=int(t.hud_anchor_offset_y),
            free_x=int(t.hud_free_x),
            free_y=int(t.hud_free_y),
            padding=int(t.hud_padding),
            # Auto row pitch: text never overlaps as Key/Label sizes
            # grow. Section gap stays larger so titles still read as
            # distinct blocks. Both scale off max(key, label).
            section_spacing=max(4, int(max(i("text_size_hud_key", 11),
                                           i("text_size_hud_label", 11)) * 0.6)),
            row_spacing=max(2, int(max(i("text_size_hud_key", 11),
                                       i("text_size_hud_label", 11)) * 0.25)),
            key_label_spacing=int(getattr(t, "hud_key_label_spacing", 16)),
            smoothing=float(getattr(t, "hud_smoothing", 0.70)),
            bg_enabled=bool(getattr(t, "panel_bg_enabled", True)),
            bg_color=tuple(getattr(t, "panel_bg_color",
                                   (0.0, 0.0, 0.0, 0.25))),
            bg_padding=int(getattr(t, "panel_bg_padding", 10)),
        ),
        depth_test_default=str(t.depth_test_default),
        # Island palette lives on AddonPreferences (Visual UV-specific),
        # not on iops_theme.
        island_palette=tuple(
            tuple(getattr(prefs, f"island_palette_{i}", _DEFAULT_ISLAND_PALETTE[i]))
            for i in range(8)
        ),
        font_path=str(getattr(t, "font_path", "")),
        stats_offset_x=int(getattr(t, "stats_offset_x", 12)),
        stats_offset_y=int(getattr(t, "stats_offset_y", 12)),
        stats_row_spacing=float(getattr(t, "stats_row_spacing", 1.5)),
        stats_column_spacing=float(getattr(t, "stats_column_spacing", 9.0)),
        point_size_handle=fl("point_size_handle", 8.0),
        point_size_handle_hover=fl("point_size_handle_hover", 10.0),
        point_size_pivot=fl("point_size_pivot", 8.0),
        point_size_cursor=fl("point_size_cursor", 8.0),
        line_width_bbox=fl("line_width_bbox", 1.5),
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
