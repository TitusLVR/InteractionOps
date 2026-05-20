import bpy
from bpy.props import (BoolProperty, EnumProperty, FloatProperty,
                       FloatVectorProperty, IntProperty)


def _color(default, name=""):
    return FloatVectorProperty(name=name, subtype="COLOR", size=4,
                               min=0.0, max=1.0, default=default)


_STATES = ("default", "closest", "active", "locked", "preview", "error")


class IOPS_Theme(bpy.types.PropertyGroup):
    # --- Point ---
    color_point:           _color((1.000, 1.000, 1.000, 0.70), "Default")
    color_closest_point:   _color((0.302, 0.816, 1.000, 1.00), "Closest")
    color_active_point:    _color((0.302, 1.000, 0.620, 1.00), "Active")
    color_locked_point:    _color((1.000, 0.098, 0.328, 1.00), "Locked")
    color_preview_point:   _color((1.000, 0.872, 0.174, 1.00), "Result Preview")
    color_error_point:     _color((1.000, 0.353, 0.353, 1.00), "Error")
    color_point_outline:   _color((0.100, 0.100, 0.100, 0.75), "Outline")
    point_size_default:    FloatProperty(name="Default",        default=8.0,  min=2.0, max=48.0)
    point_size_closest:    FloatProperty(name="Closest",        default=11.0, min=2.0, max=48.0)
    point_size_active:     FloatProperty(name="Active",         default=12.0, min=2.0, max=48.0)
    point_size_locked:     FloatProperty(name="Locked",         default=13.0, min=2.0, max=48.0)
    point_size_preview:    FloatProperty(name="Result Preview", default=10.0, min=2.0, max=48.0)
    point_size_error:      FloatProperty(name="Error",          default=13.0, min=2.0, max=48.0)

    # --- Line ---
    color_line:            _color((0.650, 0.650, 0.650, 0.30), "Default")
    color_closest_line:    _color((0.302, 0.816, 1.000, 0.85), "Closest")
    color_active_line:     _color((0.302, 1.000, 0.620, 0.90), "Active")
    color_locked_line:     _color((1.000, 0.098, 0.328, 0.95), "Locked")
    color_preview_line:    _color((1.000, 0.872, 0.174, 1.00), "Result Preview")
    color_error_line:      _color((1.000, 0.353, 0.353, 1.00), "Error")
    line_width_default:    FloatProperty(name="Default",        default=1.5, min=0.5, max=12.0)
    line_width_closest:    FloatProperty(name="Closest",        default=2.5, min=0.5, max=12.0)
    line_width_active:     FloatProperty(name="Active",         default=3.0, min=0.5, max=12.0)
    line_width_locked:     FloatProperty(name="Locked",         default=6.0, min=0.5, max=12.0)
    line_width_preview:    FloatProperty(name="Result Preview", default=2.0, min=0.5, max=12.0)
    line_width_error:      FloatProperty(name="Error",          default=2.5, min=0.5, max=12.0)

    # --- Text ---
    color_text:            _color((1.000, 1.000, 1.000, 0.60), "Default")
    color_closest_text:    _color((0.302, 0.816, 1.000, 0.90), "Closest")
    color_active_text:     _color((0.302, 1.000, 0.620, 0.90), "Active")
    color_locked_text:     _color((1.000, 0.098, 0.328, 0.90), "Locked")
    color_preview_text:    _color((1.000, 0.872, 0.174, 0.90), "Result Preview")
    color_error_text:      _color((1.000, 0.353, 0.353, 0.90), "Error")
    text_size_default:     IntProperty(name="Default",        default=11, min=8, max=64)
    text_size_closest:     IntProperty(name="Closest",        default=12, min=8, max=64)
    text_size_active:      IntProperty(name="Active",         default=12, min=8, max=64)
    text_size_locked:      IntProperty(name="Locked",         default=12, min=8, max=64)
    text_size_preview:     IntProperty(name="Result Preview", default=12, min=8, max=64)
    text_size_error:       IntProperty(name="Error",          default=12, min=8, max=64)

    # --- Widgets ---
    color_handle:          _color((1.000, 1.000, 1.000, 0.85), "Handle")
    color_handle_hover:    _color((0.302, 0.816, 1.000, 0.90), "Handle (hover)")
    color_pivot:           _color((1.000, 0.872, 0.174, 0.90), "Pivot")
    color_bbox:            _color((0.650, 0.650, 0.650, 0.30), "Selection bbox")
    color_cursor:          _color((1.000, 0.200, 0.600, 1.00), "Cursor (2D)")
    point_size_handle:       FloatProperty(name="Handle size",        default=8.0,  min=1.0, max=64.0)
    point_size_handle_hover: FloatProperty(name="Handle (hover) size", default=10.0, min=1.0, max=64.0)
    point_size_pivot:        FloatProperty(name="Pivot size",         default=12.0, min=1.0, max=64.0)
    point_size_cursor:       FloatProperty(name="Cursor size",        default=8.0,  min=1.0, max=64.0)
    line_width_bbox:         FloatProperty(name="Bbox width",         default=1.5,  min=0.5, max=12.0)

    # --- Island palette (per-island identification, indexed by island_id % 8) ---
    island_palette_0:      _color((0.40, 0.65, 1.00, 0.10), "Island 1")
    island_palette_1:      _color((1.00, 0.50, 0.30, 0.10), "Island 2")
    island_palette_2:      _color((0.35, 0.85, 0.45, 0.10), "Island 3")
    island_palette_3:      _color((0.95, 0.80, 0.25, 0.10), "Island 4")
    island_palette_4:      _color((0.70, 0.40, 0.90, 0.10), "Island 5")
    island_palette_5:      _color((0.20, 0.80, 0.75, 0.10), "Island 6")
    island_palette_6:      _color((0.90, 0.35, 0.60, 0.10), "Island 7")
    island_palette_7:      _color((0.60, 0.80, 0.20, 0.10), "Island 8")

    # --- HUD text (key glyph + label colors and sizes; UI lives under
    # the "Text & Font" section since these are text style props).
    color_hud_key:         _color((0.344, 1.000, 0.653, 1.00), "Key glyph")
    color_hud_label_on:    _color((0.844, 0.844, 0.844, 0.819), "Label (active)")
    color_hud_label_off:   _color((0.466, 0.473, 0.487, 0.85), "Label (inactive)")
    color_hud_label_disabled:_color((0.179, 0.179, 0.191, 0.85), "Label (disabled)")
    text_size_hud_key:     IntProperty(name="Key glyph size", default=11, min=8, max=64)
    text_size_hud_label:   IntProperty(name="Label size",     default=11, min=8, max=64)
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
    hud_key_label_spacing: IntProperty(
        name="Key→label spacing",
        description="Gap between the widest key glyph and the label column",
        default=16, min=0, max=240,
    )
    hud_smoothing: FloatProperty(
        name="Cursor smoothing",
        description="How smoothly the HUD glides toward its target "
                    "position. 0 = snap instantly to the cursor. "
                    "Higher = the HUD lags and slides in (most visible "
                    "after a viewport rotate/zoom, when the cursor has "
                    "drifted while the HUD was held still)",
        default=0.70, min=0.0, max=0.98, step=5, precision=2,
    )
    # --- Help overlay ---
    # NOTE: toggle keys (Help expand/collapse, HUD params show/hide) are
    # registered as proper keymap items (`iops.ui_help_toggle`,
    # `iops.ui_hud_params_toggle`) and edited in the Keymaps tab — not as
    # StringProperty fields here.
    help_corner: EnumProperty(
        name="Help position",
        items=[
            ("top_left",      "Top left",      ""),
            ("top_center",    "Top center",    ""),
            ("top_right",     "Top right",     ""),
            ("left_center",   "Left center",   ""),
            ("right_center",  "Right center",  ""),
            ("bottom_left",   "Bottom left",   ""),
            ("bottom_center", "Bottom center", ""),
            ("bottom_right",  "Bottom right",  ""),
        ],
        default="left_center",
    )
    help_offset_x: IntProperty(name="Help X offset", default=8, min=-4000, max=4000)
    help_offset_y: IntProperty(name="Help Y offset", default=0, min=-4000, max=4000)
    help_anim_preset: EnumProperty(
        name="Help animation",
        items=[
            ("none",       "None",         "Instant toggle"),
            ("fade",       "Fade",         "Smooth cross-fade between states"),
            ("slide-fade", "Slide + fade", "Slide in from the anchored edge"),
            ("wave",       "Wave",         "Per-letter staggered reveal from the anchored edge"),
            ("shockwave",  "Shockwave",    "Outgoing letters explode radially outward; new content fades in beneath"),
        ],
        default="fade",
    )
    help_anim_duration: FloatProperty(
        name="Help animation duration",
        default=0.5, min=0.0, max=2.0,
        description="Seconds for the help overlay transition",
    )
    help_anim_slide_amount: IntProperty(
        name="Slide distance",
        description="Pixels of horizontal slide used by the 'slide+fade' preset",
        default=28, min=0, max=400,
    )
    help_anim_wave_duration: FloatProperty(
        name="Wave duration",
        description="Seconds the 'wave' preset takes to fully reveal — "
                    "overrides the shared help animation duration when "
                    "the wave preset is active",
        default=2.0, min=0.05, max=5.0, step=10, precision=2,
    )
    help_anim_wave_spread: IntProperty(
        name="Wave spread",
        description="How far (in pixels) each letter starts from its final "
                    "position during the 'wave' preset — bigger = letters "
                    "fly in from further away",
        default=128, min=0, max=400,
    )
    help_anim_wave_stagger_scale: FloatProperty(
        name="Wave stagger",
        description="Multiplier on the per-letter delay during 'wave'. "
                    "1.0 fits the whole reveal into the animation duration; "
                    ">1 makes neighbouring letters more clearly staggered",
        default=1.0, min=0.1, max=10.0, step=10, precision=2,
    )
    help_anim_wave_fade_window: FloatProperty(
        name="Wave letter fade",
        description="Fraction of the animation each letter takes to fade in",
        default=0.5, min=0.05, max=1.0, step=5, precision=2,
    )
    help_anim_shockwave_radius: IntProperty(
        name="Shockwave radius",
        description="Peak distance (px) each outgoing letter travels "
                    "outward from the box centre",
        default=160, min=20, max=800,
    )
    help_hint_text: bpy.props.StringProperty(
        name="Help hint text",
        description="Text shown when Help is collapsed. {key} is replaced "
                    "with the configured toggle key.",
        default="Press {key} for help",
    )

    depth_test_default: EnumProperty(
        name="Depth test",
        items=[("LESS", "Less", ""), ("ALWAYS", "Always", "")],
        default="ALWAYS",
    )

    font_path: bpy.props.StringProperty(
        name="Font file",
        description=("Path to a TTF/OTF font used by HUD and overlay text. "
                     "Empty = Blender's default font"),
        subtype="FILE_PATH",
        default="",
    )

    # Statistics overlay position (general UI, top-left of 3D view).
    stats_offset_x: IntProperty(
        name="Stats X",
        description="Horizontal offset of the statistics overlay from the "
                    "left edge of the 3D view (after the toolbar)",
        default=8, min=0, max=4000,
    )
    stats_offset_y: IntProperty(
        name="Stats Y",
        description="Vertical offset of the statistics overlay from the "
                    "top edge of the 3D view",
        default=220, min=0, max=4000,
    )
    stats_row_spacing: FloatProperty(
        name="Stats row spacing",
        description="Vertical spacing between rows of the statistics "
                    "overlay, in multiples of the text line height",
        default=1.5, min=0.5, max=4.0, step=10, precision=2,
    )
    stats_column_spacing: FloatProperty(
        name="Stats column spacing",
        description="Horizontal offset of the value column from the "
                    "label column in the statistics overlay, in multiples "
                    "of the text line height",
        default=5.0, min=2.0, max=40.0, step=10, precision=2,
    )

    # --- Theme tab fold state (UI only) ---
    show_point: BoolProperty(default=True)
    show_line: BoolProperty(default=False)
    show_text: BoolProperty(default=False)
    show_surfaces: BoolProperty(default=False)
    show_widgets: BoolProperty(default=False)
    show_islands: BoolProperty(default=False)
    show_font: BoolProperty(default=False)
    show_hud: BoolProperty(default=False)
    show_help: BoolProperty(default=False)
    show_stats: BoolProperty(default=False)
    show_behaviour: BoolProperty(default=False)


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


_STATE_LABELS = ("Default", "Closest", "Active", "Locked", "Result Preview", "Error")


def _state_color_row(parent, theme, prefix):
    row = parent.row(align=True)
    for s in _STATES:
        row.prop(theme, f"color_{s}_{prefix}" if s != "default" else f"color_{prefix}", text="")


def _state_float_row(parent, theme, prefix):
    row = parent.row(align=True)
    for s in _STATES:
        row.prop(theme, f"{prefix}_{s}", text=s.capitalize()[:3])


def _state_table(parent, theme, color_prefix, size_prefix=None):
    """Render a vertical state-table: one row per state, columns
    [Name | Size | Color]. Pass `size_prefix=None` to render a single
    em-dash placeholder in the size column (used for primitives that
    don't have per-state sizes)."""
    header = parent.row(align=True)
    header.label(text="State")
    header.label(text="Size" if size_prefix else "")
    header.label(text="Color")
    body = parent.column(align=True)
    for state, label in zip(_STATES, _STATE_LABELS):
        row = body.row(align=True)
        row.label(text=label)
        if size_prefix:
            row.prop(theme, f"{size_prefix}_{state}", text="")
        else:
            row.label(text="—")
        color_attr = (f"color_{color_prefix}" if state == "default"
                      else f"color_{state}_{color_prefix}")
        row.prop(theme, color_attr, text="")


def _name_color_row(parent, theme, attr, label):
    row = parent.row(align=True)
    row.label(text=label)
    row.label(text="—")
    row.prop(theme, attr, text="")


def _theme_section(layout, theme, prop_name, title, *, icon="NONE"):
    """Collapsible section header for the Theme tab. Returns the body
    column to draw into, or None when collapsed."""
    box = layout.box()
    row = box.row(align=True)
    is_open = getattr(theme, prop_name)
    row.prop(theme, prop_name, text="",
             icon="TRIA_DOWN" if is_open else "TRIA_RIGHT",
             emboss=False)
    row.label(text=title, icon=icon)
    if not is_open:
        return None
    return box.column(align=True)


def draw_theme_tab(layout, theme):
    # POINT
    sub = _theme_section(layout, theme, "show_point", "Point", icon="VERTEXSEL")
    if sub is not None:
        _state_table(sub, theme, "point", size_prefix="point_size")
        sub.separator()
        row = sub.row(align=True)
        row.label(text="Outline")
        row.label(text="—")
        row.prop(theme, "color_point_outline", text="")

    # LINE
    sub = _theme_section(layout, theme, "show_line", "Line", icon="EDGESEL")
    if sub is not None:
        _state_table(sub, theme, "line", size_prefix="line_width")

    # TEXT & FONT
    sub = _theme_section(layout, theme, "show_text", "Text & Font",
                         icon="FONT_DATA")
    if sub is not None:
        _state_table(sub, theme, "text", size_prefix="text_size")
        sub.separator()
        sub.label(text="HUD text:")
        for attr, size_attr, label in (
                ("color_hud_key",            "text_size_hud_key",
                 "Key glyph"),
                ("color_hud_label_on",       "text_size_hud_label",
                 "Label (active)"),
                ("color_hud_label_off",      "text_size_hud_label",
                 "Label (inactive)"),
                ("color_hud_label_disabled", "text_size_hud_label",
                 "Label (disabled)"),
        ):
            row = sub.row(align=True)
            row.label(text=label)
            row.prop(theme, size_attr, text="")
            row.prop(theme, attr, text="")
        sub.separator()
        sub.label(text="Font file:")
        sub.prop(theme, "font_path", text="")
        sub.label(
            text="Empty = Blender default. Used by HUD and overlay text.",
            icon="INFO",
        )

    # Widgets — each row: name | size | color. Handle has two color
    # swatches (idle + hover) sharing one size — it's the same widget in
    # two interaction states. Bbox uses line width, the rest use point
    # size.
    sub = _theme_section(layout, theme, "show_widgets",
                         "Widgets", icon="MOD_HUE_SATURATION")
    if sub is not None:
        for color_attr, size_attr, label in (
                ("color_handle",       "point_size_handle",       "Handle"),
                ("color_handle_hover", "point_size_handle_hover", "Handle (hover)"),
                ("color_pivot",        "point_size_pivot",        "Pivot"),
                ("color_bbox",         "line_width_bbox",         "Selection bbox"),
                ("color_cursor",       "point_size_cursor",       "2D cursor"),
        ):
            row = sub.row(align=True)
            row.label(text=label)
            row.prop(theme, size_attr,  text="")
            row.prop(theme, color_attr, text="")

    # Island palette
    sub = _theme_section(layout, theme, "show_islands",
                         "Island palette (UV)", icon="COLOR")
    if sub is not None:
        row = sub.row(align=True)
        for i in range(8):
            row.prop(theme, f"island_palette_{i}", text="")

    # HUD
    sub = _theme_section(layout, theme, "show_hud", "HUD", icon="WINDOW")
    if sub is not None:
        sub.label(text="Key glyph + label colors and sizes live in "
                       "Text & Font.", icon="INFO")
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
        sub.prop(theme, "hud_key_label_spacing")
        sub.prop(theme, "hud_smoothing", slider=True)
        sub.label(text="Toggle key: Keymaps tab → iops.ui_hud_params_toggle",
                  icon="INFO")

    # Help overlay
    sub = _theme_section(layout, theme, "show_help", "Help overlay", icon="QUESTION")
    if sub is not None:
        sub.label(text="Toggle key: Keymaps tab → iops.ui_help_toggle",
                  icon="INFO")
        sub.prop(theme, "help_corner")
        row = sub.row(align=True)
        row.prop(theme, "help_offset_x")
        row.prop(theme, "help_offset_y")
        sub.prop(theme, "help_hint_text")
        sub.separator()
        sub.prop(theme, "help_anim_preset")
        preset = theme.help_anim_preset
        if preset == "wave":
            sub.prop(theme, "help_anim_wave_duration")
        else:
            sub.prop(theme, "help_anim_duration")
        if preset == "slide-fade":
            sub.prop(theme, "help_anim_slide_amount")
        elif preset == "wave":
            sub.prop(theme, "help_anim_wave_spread")
            sub.prop(theme, "help_anim_wave_stagger_scale")
            sub.prop(theme, "help_anim_wave_fade_window")
        elif preset == "shockwave":
            sub.prop(theme, "help_anim_shockwave_radius")

    # Statistics overlay positioning
    sub = _theme_section(layout, theme, "show_stats",
                         "Statistics overlay", icon="INFO")
    if sub is not None:
        sub.prop(theme, "stats_offset_x")
        sub.prop(theme, "stats_offset_y")
        sub.prop(theme, "stats_row_spacing")
        sub.prop(theme, "stats_column_spacing")

    # Behaviour
    sub = _theme_section(layout, theme, "show_behaviour",
                         "Behaviour", icon="MODIFIER")
    if sub is not None:
        sub.prop(theme, "depth_test_default")

    layout.separator()
    row = layout.row()
    row.operator("iops.theme_reset_defaults", icon="LOOP_BACK")
    # Toggle: show "Stop" when preview is running, otherwise "Preview".
    from ..operators.draw_theme_preview import IOPS_OT_DrawThemePreview
    if IOPS_OT_DrawThemePreview.is_running:
        row.operator("iops.stop_theme_preview", icon="CANCEL")
    else:
        row.operator("iops.draw_theme_preview", icon="HIDE_OFF")


classes = (IOPS_Theme, IOPS_OT_ThemeResetDefaults)
