from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class Role(Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    LOCKED = "locked"
    SNAP = "snap"
    SNAP_CLOSEST = "snap_closest"
    PREVIEW = "preview"
    FILL = "fill"
    OUTLINE = "outline"
    HINT = "hint"
    ERROR = "error"
    SUCCESS = "success"


_DEFAULT_COLORS: dict[Role, tuple[float, float, float, float]] = {
    Role.PRIMARY:      (0.302, 0.816, 1.000, 1.00),  # #4DD0FF
    Role.SECONDARY:    (0.533, 0.541, 0.557, 0.70),  # #888A8E
    Role.LOCKED:       (1.000, 0.722, 0.302, 1.00),  # #FFB84D
    Role.SNAP:         (1.000, 1.000, 1.000, 0.60),
    Role.SNAP_CLOSEST: (0.302, 1.000, 0.620, 1.00),  # #4DFF9E
    Role.PREVIEW:      (0.302, 0.816, 1.000, 0.40),
    Role.FILL:         (0.302, 0.816, 1.000, 0.10),
    Role.OUTLINE:      (0.302, 0.816, 1.000, 0.80),
    Role.HINT:         (1.000, 1.000, 1.000, 0.25),
    Role.ERROR:        (1.000, 0.353, 0.353, 1.00),  # #FF5A5A
    Role.SUCCESS:      (0.302, 1.000, 0.620, 1.00),
}

_DEFAULT_WIDTHS = {"normal": 1.5, "thick": 3.0, "preview": 2.0}
_DEFAULT_POINT_SIZES = {"small": 6.0, "normal": 9.0, "large": 12.0}
_DEFAULT_TEXT_SIZES = {"small": 11, "normal": 12, "title": 14}


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
    verbosity: str = "compact"  # "compact" | "full"


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
    widths: dict[str, float] = field(
        default_factory=lambda: dict(_DEFAULT_WIDTHS))
    point_sizes: dict[str, float] = field(
        default_factory=lambda: dict(_DEFAULT_POINT_SIZES))
    text_sizes: dict[str, int] = field(
        default_factory=lambda: dict(_DEFAULT_TEXT_SIZES))
    shadow: ShadowSettings = field(default_factory=ShadowSettings)
    hud: HUDSettings = field(default_factory=HUDSettings)
    depth_test_default: str = "LESS"

    def color_for(self, role: Role) -> tuple[float, float, float, float]:
        return self.colors[role]

    def width(self, token: str) -> float:
        return self.widths[token]

    def point_size(self, token: str) -> float:
        return self.point_sizes[token]

    def text_size(self, token: str) -> int:
        return self.text_sizes[token]


def get_theme(context) -> "Theme":
    try:
        t = context.preferences.addons["InteractionOps"].preferences.iops_theme
    except (KeyError, AttributeError):
        return DEFAULT_THEME

    return Theme(
        colors={
            Role.PRIMARY:      tuple(t.color_primary),
            Role.SECONDARY:    tuple(t.color_secondary),
            Role.LOCKED:       tuple(t.color_locked),
            Role.SNAP:         tuple(t.color_snap),
            Role.SNAP_CLOSEST: tuple(t.color_snap_closest),
            Role.PREVIEW:      tuple(t.color_preview),
            Role.FILL:         tuple(t.color_fill),
            Role.OUTLINE:      tuple(t.color_outline),
            Role.HINT:         tuple(t.color_hint),
            Role.ERROR:        tuple(t.color_error),
            Role.SUCCESS:      tuple(t.color_success),
        },
        widths={
            "normal":  t.line_width_normal,
            "thick":   t.line_width_thick,
            "preview": t.line_width_preview,
        },
        point_sizes={
            "small":  t.point_size_small,
            "normal": t.point_size_normal,
            "large":  t.point_size_large,
        },
        text_sizes={
            "small":  t.text_size_small,
            "normal": t.text_size_normal,
            "title":  t.text_size_title,
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
            free_x=int(t.hud_free_x),
            free_y=int(t.hud_free_y),
            padding=int(t.hud_padding),
            section_spacing=int(t.hud_section_spacing),
            row_spacing=int(t.hud_row_spacing),
            key_column_width=int(t.hud_key_column_width),
            verbosity=str(getattr(t, "hud_verbosity", "compact")),
        ),
        depth_test_default=str(t.depth_test_default),
    )


DEFAULT_THEME = Theme()
