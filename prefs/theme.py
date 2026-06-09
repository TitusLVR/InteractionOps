import bpy
from bpy.props import (BoolProperty, EnumProperty, FloatProperty,
                       FloatVectorProperty, IntProperty, StringProperty)


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

    # (Old per-state text colors/sizes were unused by drawing code and
    # have been removed. All HUD/stats text now flows through a small
    # set of HUD-specific roles defined below.)

    # --- Widgets ---
    color_handle:          _color((1.000, 1.000, 1.000, 0.85), "Handle")
    color_handle_hover:    _color((0.302, 0.816, 1.000, 0.90), "Handle (hover)")
    color_pivot:           _color((1.000, 0.872, 0.174, 0.90), "Pivot")
    color_bbox:            _color((0.650, 0.650, 0.650, 0.30), "Selection bbox")
    color_cursor:          _color((1.000, 0.200, 0.600, 1.00), "Cursor (2D)")

    # --- Ghost / Surfaces --- (per-state table like Point/Line; +edge row)
    color_ghost_edge:      _color((0.000, 0.000, 0.000, 0.349), "Ghost Edge")
    color_ghost:           _color((0.851, 0.851, 0.851, 0.149), "Default")
    color_closest_ghost:   _color((0.584, 0.914, 1.000, 0.149), "Closest")
    color_active_ghost:    _color((0.584, 1.000, 0.808, 0.149), "Active")
    color_locked_ghost:    _color((1.000, 0.345, 0.608, 0.149), "Locked")
    color_preview_ghost:   _color((1.000, 0.941, 0.455, 0.149), "Result Preview")
    color_error_ghost:     _color((1.000, 0.627, 0.627, 0.502), "Error")
    point_size_handle:       FloatProperty(name="Handle size",        default=8.0,  min=1.0, max=64.0)
    point_size_handle_hover: FloatProperty(name="Handle (hover) size", default=10.0, min=1.0, max=64.0)
    point_size_pivot:        FloatProperty(name="Pivot size",         default=12.0, min=1.0, max=64.0)
    point_size_cursor:       FloatProperty(name="Cursor size",        default=8.0,  min=1.0, max=64.0)
    line_width_bbox:         FloatProperty(name="Bbox width",         default=1.5,  min=0.5, max=12.0)

    # --- HUD text roles (live under the "Dynamic Overlay" rollout in
    # the Theme tab). These are the only text styles used anywhere in
    # the addon. Sizes:
    #   Header / Glyph / Label — three independent sliders.
    # Each role now has its own color pref; defaults match
    # presets/themes/Default.itheme.
    color_hud_header:        _color((0.302, 1.000, 0.620, 0.75), "HUD Header")
    color_hud_key:           _color((1.000, 0.872, 0.174, 0.75), "HUD Glyph")
    # HUD Active Value also drives HUD_LABEL_ACTIVE — both convey the
    # "currently active item" highlight.
    color_hud_active_value:  _color((1.000, 0.872, 0.174, 0.75), "HUD Active Value / Label Active")
    color_hud_label:         _color((0.844, 0.844, 0.844, 0.75), "HUD Label")
    color_hud_label_inactive:_color((0.466, 0.473, 0.487, 0.85), "HUD Label Inactive")
    color_hud_stats_error:   _color((1.000, 0.339, 0.382, 0.90), "HUD Stats Error/Warning")
    text_size_hud_header:    IntProperty(name="Header Size", default=14, min=8, max=64)
    text_size_hud_key:       IntProperty(name="Glyph Size",  default=12, min=8, max=64)
    text_size_hud_label:     IntProperty(name="Label Size",  default=11, min=8, max=64)
    shadow_enabled:        BoolProperty(name="Shadow", default=True)
    shadow_color:          _color((0.0, 0.0, 0.0, 1.0), "Shadow color")
    shadow_blur:           IntProperty(name="Shadow blur", default=0, min=0, max=5)
    shadow_offset_x:       IntProperty(name="Shadow X", default=1, min=-8, max=8)
    shadow_offset_y:       IntProperty(name="Shadow Y", default=-1, min=-8, max=8)

    hud_mode: EnumProperty(
        name="HUD Placement",
        items=[
            ("cursor",        "Mouse Cursor",  "Follow mouse cursor"),
            ("top_left",      "Top Left",      ""),
            ("top_center",    "Top Center",    ""),
            ("top_right",     "Top Right",     ""),
            ("left_center",   "Center Left",   ""),
            ("center",        "Center",        ""),
            ("right_center",  "Center Right",  ""),
            ("bottom_left",   "Bottom Left",   ""),
            ("bottom_center", "Bottom Center", ""),
            ("bottom_right",  "Bottom Right",  ""),
            ("free",          "Free",          "Fixed position (drag to move)"),
        ],
        default="cursor",
    )
    hud_offset_x: IntProperty(name="Mouse Cursor offset X", default=20)
    hud_offset_y: IntProperty(name="Mouse Cursor offset Y", default=-20)
    hud_anchor_offset_x: IntProperty(name="Offset X", default=0, min=-4000, max=4000)
    hud_anchor_offset_y: IntProperty(name="Offset Y", default=0, min=-4000, max=4000)
    hud_free_x: IntProperty(name="Position X", default=40, min=0)
    hud_free_y: IntProperty(name="Position Y", default=40, min=0)
    hud_padding: IntProperty(name="Padding", default=12, min=0, max=64)
    hud_section_spacing: IntProperty(name="Section spacing", default=8, min=0, max=64)
    hud_row_spacing: IntProperty(name="Row spacing", default=3, min=0, max=16)
    hud_key_label_spacing: IntProperty(
        name="Key→label spacing",
        description="Gap between the widest key glyph and the label column",
        default=16, min=0, max=240,
    )
    hud_anim_fps: IntProperty(
        name="Animation FPS",
        description="Internal redraw rate (Hz) for HUD animations and "
                    "cursor-follow smoothing. Match your monitor's refresh "
                    "rate for smoothest motion. Animation duration is "
                    "time-based, so this only affects how many in-between "
                    "frames are drawn",
        default=240, min=30, max=1000,
    )
    # --- Background panel (HUD + Help) ---
    panel_bg_enabled: BoolProperty(name="Background panel", default=True)
    panel_bg_color: FloatVectorProperty(
        name="Panel color", subtype="COLOR", size=4,
        default=(0.0, 0.0, 0.0, 0.25),
        soft_min=0.0, soft_max=1.0, min=0.0, max=1.0,
    )
    panel_bg_padding: IntProperty(
        name="Panel padding",
        description="Pixels added around the content rectangle for the "
                    "background panel",
        default=10, min=0, max=64,
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
        name="Help Placement",
        items=[
            ("top_left",      "Top Left",      ""),
            ("top_center",    "Top Center",    ""),
            ("top_right",     "Top Right",     ""),
            ("left_center",   "Center Left",   ""),
            ("right_center",  "Center Right",  ""),
            ("bottom_left",   "Bottom Left",   ""),
            ("bottom_center", "Bottom Center", ""),
            ("bottom_right",  "Bottom Right",  ""),
            ("free",          "Free",          "Fixed position"),
        ],
        default="left_center",
    )
    help_offset_x: IntProperty(name="Offset X", default=8, min=-4000, max=4000)
    help_offset_y: IntProperty(name="Offset Y", default=0, min=-4000, max=4000)
    help_free_x: IntProperty(name="Position X", default=40, min=0)
    help_free_y: IntProperty(name="Position Y", default=40, min=0)
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
    stats_text_size: IntProperty(
        name="Text size",
        description="Text size for the statistics overlay. Row spacing "
                    "scales automatically with this value",
        default=11, min=8, max=64,
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

    # --- Theme presets (file-backed list in scripts/presets/IOPS/themes/) ---
    # `theme_preset` is a dynamic EnumProperty (items from a callback), which
    # Blender does NOT persist to userpref.blend — it resets to the first item
    # on every reload. We back it with `theme_preset_name` (a real, persisted
    # StringProperty) via get/set so the last selection survives reload. The
    # get/set only translate index<->name; getter returns 0 if the stored name
    # no longer exists, so a deleted preset degrades gracefully.
    theme_preset_name: StringProperty(default="", options={"HIDDEN"})
    theme_preset: EnumProperty(
        name="Preset",
        description="Apply a saved theme preset",
        items=lambda self, ctx: _theme_preset_items_proxy(self, ctx),
        update=lambda self, ctx: _theme_preset_update_proxy(self, ctx),
        get=lambda self: _theme_preset_get_proxy(self),
        set=lambda self, value: _theme_preset_set_proxy(self, value),
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
    show_hud_text: BoolProperty(default=False)
    show_hud_panel: BoolProperty(default=False)
    show_hud_font: BoolProperty(default=False)
    show_hud_placement: BoolProperty(default=True)
    show_help: BoolProperty(default=False)
    show_stats: BoolProperty(default=False)
    show_behaviour: BoolProperty(default=False)


# Lazy bridge to io_theme module — keeps EnumProperty lambdas from
# importing operators at module-load time (would cause a circular
# dependency between prefs/ and operators/).
def _theme_preset_items_proxy(self, context):
    from ..operators.preferences import io_theme
    return io_theme.theme_preset_items(self, context)


def _theme_preset_update_proxy(self, context):
    from ..operators.preferences import io_theme
    io_theme.theme_preset_update(self, context)


def _theme_preset_get_proxy(self):
    from ..operators.preferences import io_theme
    return io_theme.theme_preset_get(self)


def _theme_preset_set_proxy(self, value):
    from ..operators.preferences import io_theme
    io_theme.theme_preset_set(self, value)


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


class IOPS_OT_ThemeUseBlenderHUDColors(bpy.types.Operator):
    bl_idname = "iops.theme_use_blender_hud_colors"
    bl_label = "Use Blender Theme HUD Colors"
    bl_description = ("Copy HUD-relevant colors from Blender's current "
                      "theme into the addon's HUD palette")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from mathutils import Color

        def to_linear_rgba(src, *, alpha_override=None):
            """Convert a sRGB theme color (3 or 4 components) to a
            scene-linear RGBA tuple ready to write into a COLOR prop."""
            r, g, b = src[0], src[1], src[2]
            c = Color((r, g, b)).from_srgb_to_scene_linear()
            if alpha_override is not None:
                a = float(alpha_override)
            elif len(src) > 3:
                a = float(src[3])
            else:
                a = 1.0
            return (c.r, c.g, c.b, a)

        try:
            bth = context.preferences.themes[0]
            ui = bth.user_interface
            v3d = bth.view_3d
        except (IndexError, AttributeError):
            self.report({"ERROR"}, "Blender theme is unavailable")
            return {"CANCELLED"}

        prefs = context.preferences.addons["InteractionOps"].preferences
        t = prefs.iops_theme

        # Header → panel_title (Blender's section-title text color).
        t.color_hud_header = to_linear_rgba(ui.panel_title,
                                            alpha_override=1.0)
        # Glyph → object_active accent.
        t.color_hud_key = to_linear_rgba(v3d.object_active,
                                          alpha_override=1.0)
        # Active Value → editmesh_active accent (drives HUD_LABEL_ACTIVE
        # too — both convey the "active item" highlight).
        t.color_hud_active_value = to_linear_rgba(v3d.editmesh_active,
                                                   alpha_override=1.0)
        # Label / Label Inactive → widget text settings; inactive is
        # the same color at half opacity.
        text = ui.wcol_text.text
        t.color_hud_label          = to_linear_rgba(text, alpha_override=1.0)
        t.color_hud_label_inactive = to_linear_rgba(text, alpha_override=0.5)
        # Stats error → widget state error.
        t.color_hud_stats_error = to_linear_rgba(ui.wcol_state.error)
        # Panel background → ThemeUserInterface.panel_back (keeps its
        # native alpha for the see-through look).
        t.panel_bg_color = to_linear_rgba(ui.panel_back)

        self.report({"INFO"}, "HUD colors synced from Blender theme")
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
    # Preset bar: dropdown + Save As + Delete + open folder.
    bar = layout.row(align=True)
    bar.prop(theme, "theme_preset", text="")
    bar.operator("iops.theme_save_as", text="", icon="FILE_NEW")
    bar.operator("iops.theme_save", text="", icon="FILE_TICK")
    bar.operator("iops.theme_delete", text="", icon="TRASH")
    bar.operator("iops.theme_open_folder", text="", icon="FILE_FOLDER")
    layout.separator()

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

    # Ghost / Surfaces — highlight color for ghost-preview wires and the
    # translucent fill behind them.
    sub = _theme_section(layout, theme, "show_surfaces",
                         "Ghost / Surfaces", icon="MOD_MASK")
    if sub is not None:
        _name_color_row(sub, theme, "color_ghost_edge", "Edges")
        sub.separator()
        _state_table(sub, theme, "ghost")

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

    # HUD — parent rollout. Contains three shared-style sub-sections
    # (text, panel+shadow, font) used by every HUD overlay, followed by
    # three per-overlay sub-sections (Dynamic, Help, Statistics).
    sub = _theme_section(layout, theme, "show_hud", "HUD", icon="WINDOW")
    if sub is not None:
        sub.operator("iops.theme_use_blender_hud_colors", icon="COLOR")
        sub.separator()
        # --- Text Styles ----------------------------------------------
        body = _theme_section(sub, theme, "show_hud_text",
                              "Text Styles", icon="FONT_DATA")
        if body is not None:
            for attr, size_attr, label in (
                    ("color_hud_header",         "text_size_hud_header",
                     "HUD Header"),
                    ("color_hud_key",            "text_size_hud_key",
                     "HUD Glyph"),
                    ("color_hud_active_value",   None,
                     "HUD Active Value / Label Active"),
                    ("color_hud_label",          "text_size_hud_label",
                     "HUD Label"),
                    ("color_hud_label_inactive", None,
                     "HUD Label Inactive"),
                    ("color_hud_stats_error",    None,
                     "HUD Stats Error/Warning"),
            ):
                row = body.row(align=True)
                row.label(text=label)
                if size_attr is not None:
                    row.prop(theme, size_attr, text="")
                else:
                    row.label(text="")
                row.prop(theme, attr, text="")

        # --- Panel & Shadow -------------------------------------------
        body = _theme_section(sub, theme, "show_hud_panel",
                              "Panel & Shadow", icon="MESH_PLANE")
        if body is not None:
            body.prop(theme, "panel_bg_enabled")
            bg = body.column(align=True)
            bg.active = theme.panel_bg_enabled
            bg.prop(theme, "panel_bg_color")
            bg.prop(theme, "panel_bg_padding")
            body.separator()
            body.prop(theme, "shadow_enabled")
            sh = body.column(align=True)
            sh.active = theme.shadow_enabled
            sh.prop(theme, "shadow_color")
            sh.prop(theme, "shadow_blur")
            sh.prop(theme, "shadow_offset_x")
            sh.prop(theme, "shadow_offset_y")

        # --- Font -----------------------------------------------------
        body = _theme_section(sub, theme, "show_hud_font",
                              "Font", icon="FILE_FONT")
        if body is not None:
            body.prop(theme, "font_path", text="")

        sub.separator()

        # --- Dynamic Overlay (per-operator HUD) -------------------------
        body = _theme_section(sub, theme, "show_hud_placement",
                              "Dynamic Overlay", icon="WINDOW")
        if body is not None:
            body.prop(theme, "hud_mode")
            mode = theme.hud_mode
            row = body.row(align=True)
            if mode == "cursor":
                row.prop(theme, "hud_offset_x")
                row.prop(theme, "hud_offset_y")
            elif mode == "free":
                row.prop(theme, "hud_free_x")
                row.prop(theme, "hud_free_y")
            else:
                row.prop(theme, "hud_anchor_offset_x")
                row.prop(theme, "hud_anchor_offset_y")
            body.prop(theme, "hud_padding")
            body.prop(theme, "hud_key_label_spacing")
            body.prop(theme, "hud_smoothing", slider=True)

        # --- Help Overlay -----------------------------------------------
        body = _theme_section(sub, theme, "show_help",
                              "Help Overlay", icon="QUESTION")
        if body is not None:
            body.prop(theme, "help_corner")
            body.prop(theme, "hud_anim_fps")
            row = body.row(align=True)
            if theme.help_corner == "free":
                row.prop(theme, "help_free_x")
                row.prop(theme, "help_free_y")
            else:
                row.prop(theme, "help_offset_x")
                row.prop(theme, "help_offset_y")
            body.prop(theme, "help_hint_text")
            body.separator()
            body.prop(theme, "help_anim_preset")
            preset = theme.help_anim_preset
            if preset == "wave":
                body.prop(theme, "help_anim_wave_duration")
            else:
                body.prop(theme, "help_anim_duration")
            if preset == "slide-fade":
                body.prop(theme, "help_anim_slide_amount")
            elif preset == "wave":
                body.prop(theme, "help_anim_wave_spread")
                body.prop(theme, "help_anim_wave_stagger_scale")
                body.prop(theme, "help_anim_wave_fade_window")
            elif preset == "shockwave":
                body.prop(theme, "help_anim_shockwave_radius")

        # --- Statistics Overlay -----------------------------------------
        body = _theme_section(sub, theme, "show_stats",
                              "Statistics Overlay", icon="INFO")
        if body is not None:
            body.prop(theme, "stats_text_size")
            body.prop(theme, "stats_offset_x")
            body.prop(theme, "stats_offset_y")
            body.prop(theme, "stats_row_spacing")
            body.prop(theme, "stats_column_spacing")

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


classes = (IOPS_Theme, IOPS_OT_ThemeResetDefaults,
           IOPS_OT_ThemeUseBlenderHUDColors)
