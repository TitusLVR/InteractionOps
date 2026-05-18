import bpy
from bpy.props import (BoolProperty, EnumProperty, FloatProperty,
                       FloatVectorProperty, IntProperty)


def _color(default, name=""):
    return FloatVectorProperty(name=name, subtype="COLOR", size=4,
                               min=0.0, max=1.0, default=default)


_STATES = ("default", "closest", "active", "locked", "preview")


class IOPS_Theme(bpy.types.PropertyGroup):
    # --- Point ---
    color_point:           _color((1.000, 1.000, 1.000, 0.70), "Default")
    color_closest_point:   _color((0.302, 0.816, 1.000, 1.00), "Closest")
    color_active_point:    _color((0.302, 1.000, 0.620, 1.00), "Active")
    color_locked_point:    _color((1.000, 0.098, 0.328, 1.00), "Locked")
    color_preview_point:   _color((1.000, 0.872, 0.174, 1.00), "Preview")
    color_point_outline:   _color((0.100, 0.100, 0.100, 0.75), "Outline")
    point_size_default:    FloatProperty(name="Default", default=7.0,  min=2.0, max=48.0)
    point_size_closest:    FloatProperty(name="Closest", default=12.0, min=2.0, max=48.0)
    point_size_active:     FloatProperty(name="Active",  default=10.0, min=2.0, max=48.0)
    point_size_locked:     FloatProperty(name="Locked",  default=10.0, min=2.0, max=48.0)
    point_size_preview:    FloatProperty(name="Preview", default=6.0,  min=2.0, max=48.0)

    # --- Line ---
    color_line:            _color((1.000, 1.000, 1.000, 0.60), "Default")
    color_closest_line:    _color((0.302, 0.816, 1.000, 1.00), "Closest")
    color_active_line:     _color((0.302, 1.000, 0.620, 1.00), "Active")
    color_locked_line:     _color((1.000, 0.098, 0.328, 1.00), "Locked")
    color_preview_line:    _color((1.000, 0.872, 0.174, 1.00), "Preview")
    line_width_default:    FloatProperty(name="Default", default=1.5, min=0.5, max=12.0)
    line_width_closest:    FloatProperty(name="Closest", default=2.5, min=0.5, max=12.0)
    line_width_active:     FloatProperty(name="Active",  default=3.0, min=0.5, max=12.0)
    line_width_locked:     FloatProperty(name="Locked",  default=6.0, min=0.5, max=12.0)
    line_width_preview:    FloatProperty(name="Preview", default=2.0, min=0.5, max=12.0)

    # --- Text ---
    color_text:            _color((1.000, 1.000, 1.000, 0.60), "Default")
    color_closest_text:    _color((0.302, 0.816, 1.000, 1.00), "Closest")
    color_active_text:     _color((0.302, 1.000, 0.620, 1.00), "Active")
    color_locked_text:     _color((1.000, 0.098, 0.328, 1.00), "Locked")
    color_preview_text:    _color((1.000, 0.872, 0.174, 1.00), "Preview")
    text_size_default:     IntProperty(name="Default", default=11, min=8, max=64)
    text_size_closest:     IntProperty(name="Closest", default=12, min=8, max=64)
    text_size_active:      IntProperty(name="Active",  default=12, min=8, max=64)
    text_size_locked:      IntProperty(name="Locked",  default=12, min=8, max=64)
    text_size_preview:     IntProperty(name="Preview", default=12, min=8, max=64)

    # --- Surfaces / status ---
    color_fill:            _color((1.000, 1.000, 1.000, 0.15), "Fill")
    color_error:           _color((1.000, 0.353, 0.353, 1.00), "Error")
    color_success:         _color((0.344, 1.000, 0.653, 1.00), "Success")

    # --- Widgets ---
    color_handle:          _color((1.000, 1.000, 1.000, 0.85), "Handle")
    color_handle_hover:    _color((1.000, 0.850, 0.000, 1.00), "Handle (hover)")
    color_pivot:           _color((1.000, 1.000, 1.000, 0.80), "Pivot")
    color_bbox:            _color((0.650, 0.650, 0.650, 0.30), "Selection bbox")
    color_cursor:          _color((1.000, 0.200, 0.600, 1.00), "Cursor (2D)")

    # --- HUD ---
    color_hud_key:         _color((0.344, 1.000, 0.653, 1.00), "Key glyph")
    color_hud_label_on:    _color((0.844, 0.844, 0.844, 0.819), "Label (active)")
    color_hud_label_off:   _color((0.466, 0.473, 0.487, 0.85), "Label (inactive)")
    color_hud_label_disabled:_color((0.179, 0.179, 0.191, 0.85), "Label (disabled)")
    shadow_enabled:        BoolProperty(name="Shadow", default=True)
    shadow_color:          _color((0.0, 0.0, 0.0, 1.0), "Shadow color")
    shadow_blur:           IntProperty(name="Shadow blur", default=0, min=0, max=10)
    shadow_offset_x:       IntProperty(name="Shadow X", default=1, min=-8, max=8)
    shadow_offset_y:       IntProperty(name="Shadow Y", default=-1, min=-8, max=8)

    hud_mode: EnumProperty(
        name="HUD position",
        items=[
            ("cursor",       "Cursor",       "Follow mouse cursor"),
            ("top_left",     "Top left",     ""),
            ("top_right",    "Top right",    ""),
            ("bottom_left",  "Bottom left",  ""),
            ("bottom_right", "Bottom right", ""),
            ("free",         "Free",         "Fixed position"),
        ],
        default="cursor",
    )
    hud_offset_x: IntProperty(name="Cursor offset X", default=20)
    hud_offset_y: IntProperty(name="Cursor offset Y", default=-20)
    hud_free_x: IntProperty(name="Free X", default=40, min=0)
    hud_free_y: IntProperty(name="Free Y", default=40, min=0)
    hud_padding: IntProperty(name="Padding", default=12, min=0, max=64)
    hud_section_spacing: IntProperty(name="Section spacing", default=8, min=0, max=64)
    hud_row_spacing: IntProperty(name="Row spacing", default=3, min=0, max=16)
    hud_key_column_width: IntProperty(name="Key column width", default=45, min=20, max=240)
    hud_verbosity: EnumProperty(
        name="HUD verbosity",
        items=[
            ("compact", "Compact", "Only show items in non-default state, plus essential anchors"),
            ("full",    "Full",    "Show all items in two columns"),
        ],
        default="compact",
    )

    depth_test_default: EnumProperty(
        name="Depth test",
        items=[("LESS", "Less", ""), ("ALWAYS", "Always", "")],
        default="ALWAYS",
    )


class IOPS_OT_ThemeResetDefaults(bpy.types.Operator):
    bl_idname = "iops.theme_reset_defaults"
    bl_label = "Reset Theme to Defaults"
    bl_description = "Restore all theme values to defaults"
    bl_options = {"REGISTER"}

    def execute(self, context):
        prefs = context.preferences.addons["InteractionOps"].preferences
        t = prefs.iops_theme
        for prop_name in t.bl_rna.properties.keys():
            if prop_name in {"name", "rna_type"}:
                continue
            t.property_unset(prop_name)
        return {"FINISHED"}


def _state_color_row(parent, theme, prefix):
    row = parent.row(align=True)
    for s in _STATES:
        row.prop(theme, f"color_{s}_{prefix}" if s != "default" else f"color_{prefix}", text="")


def _state_float_row(parent, theme, prefix):
    row = parent.row(align=True)
    for s in _STATES:
        row.prop(theme, f"{prefix}_{s}", text=s.capitalize()[:3])


def draw_theme_tab(layout, theme):
    # POINT
    box = layout.box()
    box.label(text="Point", icon="VERTEXSEL")
    sub = box.column(align=True)
    sub.label(text="Colors  (Default · Closest · Active · Locked · Preview):")
    _state_color_row(sub, theme, "point")
    sub.prop(theme, "color_point_outline")
    sub.separator()
    sub.label(text="Sizes (px):")
    _state_float_row(sub, theme, "point_size")

    # LINE
    box = layout.box()
    box.label(text="Line", icon="EDGESEL")
    sub = box.column(align=True)
    sub.label(text="Colors  (Default · Closest · Active · Locked · Preview):")
    _state_color_row(sub, theme, "line")
    sub.separator()
    sub.label(text="Widths (px):")
    _state_float_row(sub, theme, "line_width")

    # TEXT
    box = layout.box()
    box.label(text="Text", icon="FONT_DATA")
    sub = box.column(align=True)
    sub.label(text="Colors  (Default · Closest · Active · Locked · Preview):")
    _state_color_row(sub, theme, "text")
    sub.separator()
    sub.label(text="Sizes (px):")
    _state_float_row(sub, theme, "text_size")

    # Surfaces / status
    box = layout.box()
    box.label(text="Surfaces & status")
    sub = box.column(align=True)
    sub.prop(theme, "color_fill")
    sub.prop(theme, "color_error")
    sub.prop(theme, "color_success")

    # HUD
    box = layout.box()
    box.label(text="HUD", icon="WINDOW")
    sub = box.column(align=True)
    sub.prop(theme, "color_hud_key")
    sub.prop(theme, "color_hud_label_on")
    sub.prop(theme, "color_hud_label_off")
    sub.prop(theme, "color_hud_label_disabled")
    sub.separator()
    sub.prop(theme, "shadow_enabled")
    sh = sub.column(align=True)
    sh.active = theme.shadow_enabled
    sh.prop(theme, "shadow_color")
    sh.prop(theme, "shadow_blur")
    sh.prop(theme, "shadow_offset_x")
    sh.prop(theme, "shadow_offset_y")
    sub.separator()
    sub.prop(theme, "hud_mode")
    sub.prop(theme, "hud_offset_x")
    sub.prop(theme, "hud_offset_y")
    sub.prop(theme, "hud_padding")
    sub.prop(theme, "hud_section_spacing")
    sub.prop(theme, "hud_row_spacing")
    sub.prop(theme, "hud_key_column_width")
    sub.prop(theme, "hud_verbosity")

    # Behaviour
    box = layout.box()
    box.label(text="Behaviour")
    box.prop(theme, "depth_test_default")

    layout.separator()
    row = layout.row()
    row.operator("iops.theme_reset_defaults", icon="LOOP_BACK")
    row.operator("iops.draw_theme_preview",  icon="HIDE_OFF")


classes = (IOPS_Theme, IOPS_OT_ThemeResetDefaults)
