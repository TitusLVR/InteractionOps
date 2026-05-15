"""One-shot migration of legacy per-operator color/size prefs into IOPS_Theme.

Runs exactly once per addon enable. Reads any of the legacy properties that
still exist on AddonPreferences and copies them into the closest theme role.
Sets a marker property `theme_migrated_v1 = True` so we don't run twice.

Mapping (legacy → role):
- cursor_bisect_edge_color        → color_primary (active edge)
- cursor_bisect_edge_locked_color → color_locked
- cursor_bisect_snap_color        → color_snap
- cursor_bisect_snap_closest_color→ color_snap_closest
- cursor_bisect_cut_preview_color → color_preview
- cursor_bisect_plane_color       → color_fill
- cursor_bisect_plane_outline_color → color_outline
- vo_cage_color                   → color_outline
- vo_cage_points_color            → color_secondary
- vo_cage_ap_color                → color_primary
- align_edge_color                → color_primary
- text_color                      → color_secondary
- text_color_key                  → color_primary
- text_shadow_color               → shadow_color
- visual_uv_point_size            → point_size_normal
"""
from __future__ import annotations
import bpy


_COLOR_MAP = {
    "cursor_bisect_edge_color":          "color_primary",
    "cursor_bisect_edge_locked_color":   "color_locked",
    "cursor_bisect_snap_color":          "color_snap",
    "cursor_bisect_snap_closest_color":  "color_snap_closest",
    "cursor_bisect_cut_preview_color":   "color_preview",
    "cursor_bisect_plane_color":         "color_fill",
    "cursor_bisect_plane_outline_color": "color_outline",
    "vo_cage_color":                     "color_outline",
    "vo_cage_points_color":              "color_secondary",
    "vo_cage_ap_color":                  "color_primary",
    "align_edge_color":                  "color_primary",
    "text_color":                        "color_secondary",
    "text_color_key":                    "color_primary",
    "text_shadow_color":                 "shadow_color",
}
_SCALAR_MAP = {
    "visual_uv_point_size": "point_size_normal",
}
_MARKER = "theme_migrated_v1"


def run_if_needed():
    try:
        prefs = bpy.context.preferences.addons["InteractionOps"].preferences
    except KeyError:
        return
    if getattr(prefs, _MARKER, False):
        return
    theme = prefs.iops_theme
    for legacy, role in _COLOR_MAP.items():
        if hasattr(prefs, legacy):
            try:
                setattr(theme, role, tuple(getattr(prefs, legacy)))
            except (TypeError, ValueError):
                pass
    for legacy, role in _SCALAR_MAP.items():
        if hasattr(prefs, legacy):
            try:
                setattr(theme, role, float(getattr(prefs, legacy)))
            except (TypeError, ValueError):
                pass
    try:
        setattr(prefs, _MARKER, True)
    except AttributeError:
        pass
