import bpy
from bpy.props import (BoolProperty, EnumProperty, FloatProperty,
                       FloatVectorProperty, IntProperty)


def _color(default, name=""):
    return FloatVectorProperty(name=name, subtype="COLOR", size=4,
                               min=0.0, max=1.0, default=default)


class IOPS_Theme(bpy.types.PropertyGroup):
    color_primary:      _color((0.302, 0.816, 1.000, 1.00), "Primary")
    color_secondary:    _color((0.533, 0.541, 0.557, 0.70), "Secondary")
    color_locked:       _color((1.000, 0.722, 0.302, 1.00), "Locked")
    color_snap:         _color((1.000, 1.000, 1.000, 0.60), "Snap")
    color_snap_closest: _color((0.302, 1.000, 0.620, 1.00), "Snap closest")
    color_preview:      _color((0.302, 0.816, 1.000, 0.40), "Preview")
    color_fill:         _color((0.302, 0.816, 1.000, 0.10), "Fill")
    color_outline:      _color((0.302, 0.816, 1.000, 0.80), "Outline")
    color_hint:         _color((1.000, 1.000, 1.000, 0.25), "Hint")
    color_error:        _color((1.000, 0.353, 0.353, 1.00), "Error")
    color_success:      _color((0.302, 1.000, 0.620, 1.00), "Success")
    color_point_outline:_color((0.000, 0.000, 0.000, 1.00), "Point outline")
    color_hud_key:      _color((1.000, 0.722, 0.302, 1.00), "HUD key glyph")
    color_hud_label_on: _color((1.000, 1.000, 1.000, 1.00), "HUD label (active)")
    color_hud_label_off:_color((0.533, 0.541, 0.557, 0.85), "HUD label (inactive)")

    line_width_normal:  FloatProperty(name="Line normal",  default=1.5, min=0.5, max=8.0)
    line_width_thick:   FloatProperty(name="Line thick",   default=3.0, min=0.5, max=12.0)
    line_width_preview: FloatProperty(name="Line preview", default=2.0, min=0.5, max=8.0)
    point_size_small:   FloatProperty(name="Point small",  default=6.0, min=2.0, max=32.0)
    point_size_normal:  FloatProperty(name="Point normal", default=9.0, min=2.0, max=32.0)
    point_size_large:   FloatProperty(name="Point large",  default=12.0, min=2.0, max=48.0)
    text_size_small:    IntProperty(name="Text small",  default=11, min=8, max=64)
    text_size_normal:   IntProperty(name="Text normal", default=12, min=8, max=64)
    text_size_title:    IntProperty(name="Text title",  default=14, min=8, max=72)

    shadow_enabled:  BoolProperty(name="Shadow", default=True)
    shadow_color:    _color((0.0, 0.0, 0.0, 0.7), "Shadow color")
    shadow_blur:     IntProperty(name="Blur", default=3, min=0, max=10)
    shadow_offset_x: IntProperty(name="Offset X", default=1, min=-8, max=8)
    shadow_offset_y: IntProperty(name="Offset Y", default=-1, min=-8, max=8)

    hud_mode: EnumProperty(
        name="HUD position",
        items=[
            ("cursor",       "Cursor",       "Follow mouse cursor"),
            ("top_left",     "Top left",     ""),
            ("top_right",    "Top right",    ""),
            ("bottom_left",  "Bottom left",  ""),
            ("bottom_right", "Bottom right", ""),
            ("free",         "Free",         "Fixed position (draggable in op)"),
        ],
        default="cursor",
    )
    hud_offset_x: IntProperty(name="Cursor offset X", default=20)
    hud_offset_y: IntProperty(name="Cursor offset Y", default=-20)
    hud_free_x: IntProperty(name="Free X", default=40, min=0)
    hud_free_y: IntProperty(name="Free Y", default=40, min=0)
    hud_padding: IntProperty(name="Padding", default=12, min=0, max=64)
    hud_section_spacing: IntProperty(name="Section spacing", default=8, min=0, max=64)
    hud_row_spacing: IntProperty(name="Row spacing", default=2, min=0, max=16)
    hud_key_column_width: IntProperty(name="Key column width", default=60, min=20, max=240)
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
        default="LESS",
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


def draw_theme_tab(layout, theme):
    box = layout.box()
    box.label(text="Colors")
    grid = box.grid_flow(columns=2, even_columns=True, align=True)
    for prop in ("color_primary", "color_secondary", "color_locked",
                 "color_snap", "color_snap_closest", "color_preview",
                 "color_fill", "color_outline", "color_hint",
                 "color_error", "color_success", "color_point_outline",
                 "color_hud_key", "color_hud_label_on", "color_hud_label_off"):
        grid.prop(theme, prop)

    box = layout.box()
    box.label(text="Lines, points, text")
    col = box.column(align=True)
    col.prop(theme, "line_width_normal")
    col.prop(theme, "line_width_thick")
    col.prop(theme, "line_width_preview")
    col.separator()
    col.prop(theme, "point_size_small")
    col.prop(theme, "point_size_normal")
    col.prop(theme, "point_size_large")
    col.separator()
    col.prop(theme, "text_size_small")
    col.prop(theme, "text_size_normal")
    col.prop(theme, "text_size_title")

    box = layout.box()
    box.label(text="Shadow")
    col = box.column(align=True)
    col.prop(theme, "shadow_enabled")
    sub = col.column(align=True)
    sub.active = theme.shadow_enabled
    sub.prop(theme, "shadow_color")
    sub.prop(theme, "shadow_blur")
    sub.prop(theme, "shadow_offset_x")
    sub.prop(theme, "shadow_offset_y")

    box = layout.box()
    box.label(text="HUD")
    col = box.column(align=True)
    col.prop(theme, "hud_mode")
    col.prop(theme, "hud_offset_x")
    col.prop(theme, "hud_offset_y")
    col.prop(theme, "hud_padding")
    col.prop(theme, "hud_section_spacing")
    col.prop(theme, "hud_row_spacing")
    col.prop(theme, "hud_key_column_width")
    col.prop(theme, "hud_verbosity")

    box = layout.box()
    box.label(text="Behaviour")
    box.prop(theme, "depth_test_default")

    layout.separator()
    row = layout.row()
    row.operator("iops.theme_reset_defaults", icon="LOOP_BACK")
    row.operator("iops.draw_theme_preview",  icon="HIDE_OFF")  # registered in Task 12


classes = (IOPS_Theme, IOPS_OT_ThemeResetDefaults)
