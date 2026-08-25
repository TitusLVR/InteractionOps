"""GPU-overlay popup operator for the ported library addon.

Draws a floating asset-picker panel (category rows + a preview grid) directly
into the 3D viewport with ``gpu`` calls from a modal operator, rather than a
regular ``bpy.types.Panel``. Text is rendered through the addon's themed blf
stack (``ui.hud.text``); rectangle and text colors are derived live from the
active Blender theme (``_blender_theme_colors``) so the popup reads as
native UI in whatever theme (dark or light) the user has active. Mirrors the
source addon's popup pixel-for-pixel on layout: metrics arithmetic, scissor
clipping, hover/hitbox handling, and scroll clamping are all ported as-is.
"""

import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from gpu_extras.presets import draw_texture_2d

from ...ui.draw.theme import get_theme
from ...ui.hud import text as hud_text
from .common import (
    catalog_needs_sync,
    get_catalog,
    get_prefs,
    overlay_texture,
    placement_from_mouse,
)
from .props import CATEGORY_DEFINITIONS

active_popup_operator = None

PREVIEW_GRID_WIDTH = 840


def preview_column_count(preview_size, entry_count):
    tile_width = preview_size * 20 + 42
    available_columns = max(1, min(5, PREVIEW_GRID_WIDTH // tile_width))
    return min(max(1, entry_count), available_columns)


def draw_overlay_rectangle(x, y, width, height, color):
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    batch = batch_for_shader(
        shader,
        "TRI_FAN",
        {
            "pos": (
                (x, y),
                (x + width, y),
                (x + width, y + height),
                (x, y + height),
            )
        },
    )
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def _blender_theme_colors():
    """Popup palette derived from the active Blender theme so the popup
    reads as native UI in any theme (dark or light). Falls back to the
    original fixed palette if theme access fails."""
    try:
        theme = bpy.context.preferences.themes[0]
        ui = theme.user_interface
        v3d = theme.view_3d
        menu = ui.wcol_menu_back
        tool = ui.wcol_tool
        box = ui.wcol_box
        item = ui.wcol_menu_item

        def rgba(color, alpha=1.0):
            values = tuple(color)
            if len(values) >= 4:
                return values[:4]
            return values[:3] + (alpha,)

        def opaque(color):
            values = tuple(color)
            return values[:3] + (1.0,)

        def lift(color, amount):
            r, g, b, a = rgba(color)
            return (
                min(1.0, r + amount),
                min(1.0, g + amount),
                min(1.0, b + amount),
                a,
            )

        bg = rgba(menu.inner)
        # Keep the panel near-opaque: it draws over the viewport.
        bg = bg[:3] + (max(bg[3], 0.96),)
        section = opaque(box.inner) if rgba(box.inner)[3] > 0.05 else lift(bg, 0.06)[:3] + (1.0,)
        return {
            "bg": bg,
            "border": opaque(menu.outline),
            "header_bg": opaque(v3d.space.header),
            "button_bg": opaque(tool.inner),
            "button_hover": opaque(tool.inner_sel),
            "section_bg": section,
            "section_hover": opaque(item.inner_sel),
            "tile_bg": lift(bg, 0.04)[:3] + (1.0,),
            "tile_hover": opaque(item.inner_sel),
            "label_bg": lift(bg, 0.07)[:3] + (1.0,),
            "remove_hover": (0.55, 0.16, 0.14, 1.0),
            "text": rgba(item.text, 1.0),
            "text_title": rgba(item.text_sel, 1.0),
            "text_dim": rgba(item.text, 1.0)[:3] + (0.55,),
        }
    except Exception:
        return {
            "bg": (0.055, 0.055, 0.055, 0.98),
            "border": (0.240, 0.240, 0.240, 1.0),
            "header_bg": (0.090, 0.090, 0.090, 1.0),
            "button_bg": (0.150, 0.150, 0.150, 1.0),
            "button_hover": (0.240, 0.240, 0.240, 1.0),
            "section_bg": (0.115, 0.115, 0.115, 1.0),
            "section_hover": (0.180, 0.180, 0.180, 1.0),
            "tile_bg": (0.095, 0.095, 0.095, 1.0),
            "tile_hover": (0.200, 0.200, 0.200, 1.0),
            "label_bg": (0.120, 0.120, 0.120, 1.0),
            "remove_hover": (0.55, 0.16, 0.14, 1.0),
            "text": (0.844, 0.844, 0.844, 1.0),
            "text_title": (0.950, 0.950, 0.950, 1.0),
            "text_dim": (0.650, 0.650, 0.650, 0.55),
        }


def point_in_bounds(x, y, bounds):
    left, bottom, right, top = bounds
    return left <= x <= right and bottom <= y <= top


def _fit_label(name, max_width, theme):
    """Fit *name* into *max_width* px at the themed label size. When it
    doesn't fit, middle-ellipsis ("abc..xyz") — asset-name suffixes
    (variant/number endings) carry meaning, so keep both ends. Uses
    measured widths (hud_text.measure is cached), not per-char guesses."""
    if max_width <= 0:
        return ""
    width, _height = hud_text.measure(name, theme=theme, size_token="hud_label")
    if width <= max_width:
        return name

    best = ".."
    low, high = 1, len(name) - 1
    while low <= high:
        keep = (low + high) // 2
        head = (keep + 1) // 2
        tail = keep - head
        candidate = name[:head] + ".." + (name[len(name) - tail:] if tail else "")
        width, _height = hud_text.measure(
            candidate, theme=theme, size_token="hud_label"
        )
        if width <= max_width:
            best = candidate
            low = keep + 1
        else:
            high = keep - 1
    return best


class IOPS_OT_LibraryPopup(bpy.types.Operator):
    bl_idname = "iops.library_popup"
    is_bindable = True
    bl_label = "IOPS Library"
    bl_description = "Open the grouped master asset library under the mouse"
    bl_options = {"REGISTER"}

    _draw_handle = None
    _area = None
    _region = None
    _anchor_x = 0
    _anchor_y = 0
    _scroll = 0
    _max_scroll = 0
    _hitboxes = None
    _hover_key = None
    _panel_bounds = (0, 0, 0, 0)
    _drag_active = False
    _drag_start = (0, 0)
    _drag_origin = (0, 0)
    _offset_x = 0
    _offset_y = 0

    header_height = 32
    category_height = 26
    label_height = 24
    padding = 10
    gap = 7

    def invoke(self, context, event):
        global active_popup_operator

        if active_popup_operator is not None:
            # Key-repeat of the open hotkey reaches the keymap again because
            # the palette passes outside events through -- only a deliberate
            # second tap toggles it closed, never an auto-repeat.
            if getattr(event, "is_repeat", False):
                return {"CANCELLED"}
            active_popup_operator.finish()
            active_popup_operator = None
            self.report({"INFO"}, "Library palette closed.")
            return {"CANCELLED"}

        if context.area is None or context.area.type != "VIEW_3D":
            self.report({"ERROR"}, "Move the mouse over a 3D View first.")
            return {"CANCELLED"}

        context.window_manager.iops_library_placement = placement_from_mouse(
            context,
            event,
        )
        preferences = get_prefs(context)
        if preferences is None:
            self.report({"ERROR"}, "IOPS Library preferences are unavailable.")
            return {"CANCELLED"}
        if not get_catalog(context):
            if getattr(context.window_manager, "iops_library_busy", False):
                self.report({"INFO"}, "Library is syncing...")
                return {"CANCELLED"}
            bpy.ops.iops.library_refresh("INVOKE_DEFAULT")
            self.report(
                {"INFO"},
                "Syncing library — press the hotkey again in a moment.",
            )
            return {"CANCELLED"}
        elif catalog_needs_sync(context):
            context.window_manager.iops_library_status = (
                "Master changed; use Refresh to update the library."
            )
        if not get_catalog(context):
            self.report({"INFO"}, "No asset-marked datablocks found.")
            return {"CANCELLED"}

        self._area = context.area
        self._region = context.region
        self._anchor_x = event.mouse_region_x
        self._anchor_y = event.mouse_region_y
        self._scroll = 0
        self._hitboxes = []
        self._hover_key = None
        self._drag_active = False
        self._drag_start = (0, 0)
        self._offset_x = 0
        self._offset_y = 0
        self._drag_origin = (0, 0)
        self._draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_overlay,
            (),
            "WINDOW",
            "POST_PIXEL",
        )
        active_popup_operator = self
        context.window_manager.modal_handler_add(self)
        self._area.tag_redraw()
        return {"RUNNING_MODAL"}

    def popup_metrics(self, context):
        preferences = get_prefs(context)
        catalog = get_catalog(context)
        tile_size = preferences.library_preview_size * 22

        # Header controls are sized from the themed font: fixed widths from
        # the source addon overshoot as soon as the user's Label size grows.
        theme = get_theme(context)
        size_label = "Size %d" % preferences.library_preview_size

        def _button_width(label, minimum):
            width, _height = hud_text.measure(
                label, theme=theme, size_token="hud_label"
            )
            return max(minimum, int(width) + 14)

        _width, label_height = hud_text.measure(
            "Refresh", theme=theme, size_token="hud_label"
        )
        title_width, title_height = hud_text.measure(
            "IOPS Library", theme=theme, size_token="hud_header"
        )
        self._title_height = int(title_height)
        self._control_height = max(22, int(label_height) + 10)
        # Two header rows: title + window controls, then the publish chips.
        self.header_height = max(
            32,
            5 + self._control_height + 4 + self._control_height + 5,
            int(title_height) + 14,
        )
        publish_label_width, _publish_label_height = hud_text.measure(
            "Publish:", theme=theme, size_token="hud_label"
        )
        self._publish_label_width = int(publish_label_width)
        self._button_widths = {
            "close": _button_width("X", 22),
            "refresh": _button_width("Refresh", 40),
            "plus": _button_width("+", 22),
            "size": _button_width(size_label, 40),
            "minus": _button_width("-", 22),
            "pub_obj": _button_width("Obj", 30),
            "pub_col": _button_width("Col", 30),
            "pub_mat": _button_width("Mat", 30),
            "pub_grp": _button_width("Node", 30),
        }
        controls_width = (
            self._button_widths["close"]
            + 5
            + self._button_widths["refresh"]
            + 5
            + self._button_widths["plus"]
            + self._button_widths["size"]
            + self._button_widths["minus"]
        )
        publish_row_width = (
            self._publish_label_width
            + 8
            + self._button_widths["pub_obj"]
            + 3
            + self._button_widths["pub_col"]
            + 3
            + self._button_widths["pub_mat"]
            + 3
            + self._button_widths["pub_grp"]
        )
        header_min_width = max(
            int(title_width) + 11 + 12 + controls_width + 7,
            11 + publish_row_width + 7,
        )
        category_counts = []
        content_height = 0
        for category, _label, _icon, property_name in CATEGORY_DEFINITIONS:
            count = sum(
                entry.category == category for entry in catalog
            )
            if not count:
                continue
            columns = preview_column_count(preferences.library_preview_size, count)
            rows = (count + columns - 1) // columns
            expanded = getattr(context.window_manager, property_name)
            category_counts.append((count, columns, rows, expanded))
            content_height += self.category_height
            if expanded:
                content_height += rows * (
                    tile_size + self.label_height + self.gap
                )

        columns = max((item[1] for item in category_counts), default=1)
        panel_width = max(
            340,
            header_min_width,
            self.padding * 2
            + columns * tile_size
            + max(0, columns - 1) * self.gap,
        )
        panel_width = min(panel_width, max(260, self._region.width - 24))
        full_height = self.header_height + self.padding * 2 + content_height
        panel_height = min(full_height, max(180, self._region.height - 24))
        visible_content = panel_height - self.header_height - self.padding * 2
        self._max_scroll = max(0, content_height - visible_content)
        self._scroll = max(0, min(self._scroll, self._max_scroll))

        panel_x = self._anchor_x - panel_width * 0.5
        below = self._anchor_y - panel_height - 12
        if below >= 8:
            panel_y = below
        else:
            panel_y = self._anchor_y + 12

        # Drag offset is applied before the region-bounds clamp below, so a
        # dragged palette can never be pushed fully off-screen.
        panel_x += self._offset_x
        panel_y += self._offset_y

        panel_x = max(8, min(panel_x, self._region.width - panel_width - 8))
        panel_y = max(8, min(panel_y, self._region.height - panel_height - 8))
        return panel_x, panel_y, panel_width, panel_height, tile_size

    def add_hitbox(self, kind, value, bounds):
        self._hitboxes.append((kind, value, bounds))

    def _dispatch_op(self, context, call):
        """Run a bpy.ops call from the palette. bpy.ops RAISES RuntimeError
        into the caller when the operator reports an error -- uncaught, that
        kills this modal and leaks the draw handler (stuck overlay). Surface
        the error instead and keep the palette alive."""
        try:
            call()
        except RuntimeError as error:
            message = str(error).replace("Error: ", "").strip() or "Operation failed."
            message = message.splitlines()[0]
            try:
                context.window_manager.iops_library_status = message
            except Exception:
                pass
            self.report({"WARNING"}, message)

    def draw_header_button(self, label, kind, value, bounds, theme, colors):
        hovered = self._hover_key == (kind, value)
        # Same hover accent as the asset tiles, so all hot elements match.
        color = colors["tile_hover"] if hovered else colors["button_bg"]
        left, bottom, right, top = bounds
        draw_overlay_rectangle(left, bottom, right - left, top - bottom, color)
        text_width, text_height = hud_text.measure(
            label, theme=theme, size_token="hud_label",
        )
        hud_text.draw(
            label,
            left + max(5, (right - left - text_width) * 0.5),
            bottom + max(4, (top - bottom - text_height) * 0.5),
            theme=theme,
            color=colors["text"],
            size_token="hud_label",
        )
        self.add_hitbox(kind, value, bounds)

    def draw_overlay(self):
        context = bpy.context
        preferences = get_prefs(context)
        if preferences is None or self._region is None:
            return
        # SpaceView3D draw handlers run in EVERY 3D view's WINDOW region;
        # the palette belongs to exactly one. Compare RNA pointers -- bpy
        # hands out a fresh Python wrapper per access, so `is` never matches.
        region = context.region
        if region is None or region.as_pointer() != self._region.as_pointer():
            return
        theme = get_theme(context)
        colors = _blender_theme_colors()

        with hud_text.isolated(theme):
            panel_x, panel_y, panel_width, panel_height, tile_size = self.popup_metrics(
                context
            )
            panel_top = panel_y + panel_height
            self._panel_bounds = (
                panel_x,
                panel_y,
                panel_x + panel_width,
                panel_top,
            )
            self._hitboxes.clear()

            gpu.state.depth_test_set("NONE")
            gpu.state.face_culling_set("NONE")
            gpu.state.blend_set("ALPHA")
            draw_overlay_rectangle(
                panel_x - 1,
                panel_y - 1,
                panel_width + 2,
                panel_height + 2,
                colors["border"],
            )
            draw_overlay_rectangle(
                panel_x,
                panel_y,
                panel_width,
                panel_height,
                colors["bg"],
            )
            draw_overlay_rectangle(
                panel_x,
                panel_top - self.header_height,
                panel_width,
                self.header_height,
                colors["header_bg"],
            )
            control_height = getattr(self, "_control_height", 22)
            widths = getattr(
                self,
                "_button_widths",
                {"close": 22, "refresh": 62, "plus": 22, "size": 50, "minus": 22},
            )
            # Header row 1: title + window controls. Row 2: publish chips.
            control_top = panel_top - 5
            control_bottom = control_top - control_height

            title_height = getattr(self, "_title_height", 13)
            hud_text.draw(
                "IOPS Library",
                panel_x + 11,
                control_bottom + (control_height - title_height) * 0.5,
                theme=theme,
                color=colors["text_title"],
                size_token="hud_header",
            )
            right = panel_x + panel_width - 7
            close_bounds = (
                right - widths["close"], control_bottom, right, control_top,
            )
            self.draw_header_button("X", "CLOSE", 0, close_bounds, theme, colors)
            right = close_bounds[0] - 5
            refresh_bounds = (
                right - widths["refresh"], control_bottom, right, control_top,
            )
            self.draw_header_button(
                "Refresh", "REFRESH", 0, refresh_bounds, theme, colors
            )
            right = refresh_bounds[0] - 5
            plus_bounds = (right - widths["plus"], control_bottom, right, control_top)
            self.draw_header_button("+", "SIZE", 1, plus_bounds, theme, colors)
            right = plus_bounds[0]
            size_bounds = (right - widths["size"], control_bottom, right, control_top)
            self.draw_header_button(
                "Size %d" % preferences.library_preview_size,
                "NONE",
                0,
                size_bounds,
                theme,
                colors,
            )
            right = size_bounds[0]
            minus_bounds = (right - widths["minus"], control_bottom, right, control_top)
            self.draw_header_button("-", "SIZE", -1, minus_bounds, theme, colors)

            # Header row 2: publish chips (Obj / Col / Mat / Grp).
            row2_top = control_bottom - 4
            row2_bottom = row2_top - control_height
            publish_label_width = getattr(self, "_publish_label_width", 46)
            label_height = hud_text.measure(
                "Publish:", theme=theme, size_token="hud_label"
            )[1]
            hud_text.draw(
                "Publish:",
                panel_x + 11,
                row2_bottom + max(4, (control_height - label_height) * 0.5),
                theme=theme,
                color=colors["text"],
                size_token="hud_label",
            )
            left = panel_x + 11 + publish_label_width + 8
            for chip, kind, chip_label in (
                ("pub_obj", "OBJECT", "Obj"),
                ("pub_col", "COLLECTION", "Col"),
                ("pub_mat", "MATERIAL", "Mat"),
                ("pub_grp", "SHADER_GROUP", "Node"),
            ):
                chip_width = widths.get(chip, 30)
                chip_bounds = (left, row2_bottom, left + chip_width, row2_top)
                self.draw_header_button(
                    chip_label, "PUBLISH", kind, chip_bounds, theme, colors
                )
                left += chip_width + 3

            clip_bottom = panel_y + self.padding
            clip_top = panel_top - self.header_height - self.padding
            gpu.state.scissor_test_set(True)
            gpu.state.scissor_set(
                int(panel_x + 1),
                int(clip_bottom),
                max(1, int(panel_width - 2)),
                max(1, int(clip_top - clip_bottom)),
            )
            cursor_y = clip_top + self._scroll
            available_width = panel_width - self.padding * 2

            try:
                catalog = get_catalog(context)
                for category, label, _icon, property_name in CATEGORY_DEFINITIONS:
                    entries = [
                        (index, entry)
                        for index, entry in enumerate(catalog)
                        if entry.category == category
                    ]
                    if not entries:
                        continue

                    category_bottom = cursor_y - self.category_height
                    category_bounds = (
                        panel_x + self.padding,
                        category_bottom,
                        panel_x + panel_width - self.padding,
                        cursor_y,
                    )
                    expanded = getattr(context.window_manager, property_name)
                    if category_bottom <= clip_top and cursor_y >= clip_bottom:
                        hovered = self._hover_key == ("CATEGORY", property_name)
                        color = (
                            colors["section_hover"] if hovered else colors["section_bg"]
                        )
                        draw_overlay_rectangle(
                            category_bounds[0],
                            category_bounds[1],
                            category_bounds[2] - category_bounds[0],
                            self.category_height - 1,
                            color,
                        )
                        hud_text.draw(
                            "v" if expanded else ">",
                            category_bounds[0] + 7,
                            category_bottom + 7,
                            theme=theme,
                            color=colors["text"],
                            size_token="hud_label",
                        )
                        hud_text.draw(
                            "%s (%d)" % (label, len(entries)),
                            category_bounds[0] + 23,
                            category_bottom + 7,
                            theme=theme,
                            color=colors["text"],
                            size_token="hud_label",
                        )
                        self.add_hitbox("CATEGORY", property_name, category_bounds)
                    cursor_y = category_bottom
                    if not expanded:
                        continue

                    columns = preview_column_count(
                        preferences.library_preview_size,
                        len(entries),
                    )
                    rows = (len(entries) + columns - 1) // columns
                    for row_index in range(rows):
                        row_entries = entries[
                            row_index * columns : (row_index + 1) * columns
                        ]
                        row_height = tile_size + self.label_height + self.gap
                        row_top = cursor_y
                        image_bottom = row_top - tile_size
                        label_bottom = image_bottom - self.label_height
                        row_width = (
                            len(row_entries) * tile_size
                            + max(0, len(row_entries) - 1) * self.gap
                        )
                        row_x = panel_x + self.padding + max(
                            0,
                            (available_width - row_width) * 0.5,
                        )
                        for column_index, (index, entry) in enumerate(row_entries):
                            x = row_x + column_index * (tile_size + self.gap)
                            image_bounds = (x, image_bottom, x + tile_size, row_top)
                            label_bounds = (
                                x,
                                label_bottom,
                                x + tile_size,
                                image_bottom,
                            )
                            visible = image_bottom <= clip_top and row_top >= clip_bottom
                            if not visible:
                                continue
                            hovered = self._hover_key == ("ASSET", index)
                            tile_color = (
                                colors["tile_hover"] if hovered else colors["tile_bg"]
                            )
                            # blf text draws (category rows, labels) can leave
                            # the GPU blend state altered; re-assert ALPHA so
                            # tile fills and transparent thumbnails composite
                            # instead of rendering black / dropping out.
                            gpu.state.blend_set("ALPHA")
                            draw_overlay_rectangle(
                                x - 1,
                                image_bottom - 1,
                                tile_size + 2,
                                tile_size + 2,
                                tile_color,
                            )
                            texture = overlay_texture(entry)
                            if texture is not None:
                                draw_texture_2d(
                                    texture,
                                    (x, image_bottom),
                                    tile_size,
                                    tile_size,
                                )
                            else:
                                fallback = entry.id_type.title() or "Asset"
                                text_width, _text_height = hud_text.measure(
                                    fallback, theme=theme, size_token="hud_label",
                                )
                                hud_text.draw(
                                    fallback,
                                    x + max(5, (tile_size - text_width) * 0.5),
                                    image_bottom + tile_size * 0.5 - 5,
                                    theme=theme,
                                    color=colors["text_dim"],
                                    size_token="hud_label",
                                )
                            self.add_hitbox("ASSET", index, image_bounds)

                            draw_overlay_rectangle(
                                label_bounds[0],
                                label_bounds[1],
                                tile_size,
                                self.label_height - 1,
                                colors["label_bg"],
                            )
                            asset_label = _fit_label(
                                entry.asset_name,
                                tile_size - 28,
                                theme,
                            )
                            hud_text.draw(
                                asset_label,
                                x + 6,
                                label_bottom + 6,
                                theme=theme,
                                color=colors["text"],
                                size_token="hud_label",
                            )
                            remove_bounds = (
                                x + tile_size - 22,
                                label_bottom,
                                x + tile_size,
                                image_bottom,
                            )
                            remove_hovered = self._hover_key == ("REMOVE", index)
                            if remove_hovered:
                                draw_overlay_rectangle(
                                    remove_bounds[0],
                                    remove_bounds[1],
                                    22,
                                    self.label_height - 1,
                                    colors["remove_hover"],
                                )
                            hud_text.draw(
                                "X",
                                remove_bounds[0] + 7,
                                remove_bounds[1] + 6,
                                theme=theme,
                                color=colors["text"],
                                size_token="hud_label",
                            )
                            self.add_hitbox("REMOVE", index, remove_bounds)
                        cursor_y -= row_height
            finally:
                gpu.state.scissor_test_set(False)
                gpu.state.blend_set("NONE")

    def hitbox_at(self, x, y):
        for kind, value, bounds in reversed(self._hitboxes):
            if point_in_bounds(x, y, bounds):
                return kind, value
        return None

    def modal(self, context, event):
        if self._area is None or self._draw_handle is None:
            return {"CANCELLED"}

        # The palette now lives across arbitrary stretches of time; make
        # sure the area we're drawing into hasn't been torn down by a
        # layout/workspace change underneath us. Fail OPEN: a transient
        # context (window switch, event without a window) must not close
        # the palette -- only a successful scan that proves the area gone.
        try:
            areas = list(context.window.screen.areas)
        except Exception:
            areas = None
        if areas is not None and self._area not in areas:
            self.finish()
            return {"CANCELLED"}

        if event.type == "ESC":
            self.finish()
            return {"CANCELLED"}

        x = event.mouse_region_x
        y = event.mouse_region_y
        inside = point_in_bounds(x, y, self._panel_bounds)

        hit = self.hitbox_at(x, y) if inside else None
        hover_key = hit
        if hover_key != self._hover_key:
            self._hover_key = hover_key
            self._area.tag_redraw()

        if self._drag_active:
            if event.type == "MOUSEMOVE":
                self._offset_x = self._drag_origin[0] + (x - self._drag_start[0])
                self._offset_y = self._drag_origin[1] + (y - self._drag_start[1])
                self._area.tag_redraw()
                return {"RUNNING_MODAL"}
            if event.type == "LEFTMOUSE" and event.value == "RELEASE":
                self._drag_active = False
                return {"RUNNING_MODAL"}
            return {"RUNNING_MODAL"}

        if not inside:
            # Keep the viewport fully usable while the palette floats over
            # it: anything outside the panel bounds passes straight through.
            return {"PASS_THROUGH"}

        if event.type == "RIGHTMOUSE":
            self.finish()
            return {"CANCELLED"}

        if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            direction = -1 if event.type == "WHEELUPMOUSE" else 1
            self._scroll = max(
                0,
                min(self._max_scroll, self._scroll + direction * 60),
            )
            self._area.tag_redraw()
            return {"RUNNING_MODAL"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            header_top = self._panel_bounds[3] - self.header_height
            if hit is None and y >= header_top:
                self._drag_start = (x, y)
                self._drag_origin = (self._offset_x, self._offset_y)
                self._drag_active = True
            # Consume the press either way — it either starts a drag, or it
            # swallows a click on a hitbox (the action fires on RELEASE).
            return {"RUNNING_MODAL"}

        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            if hit is None:
                return {"RUNNING_MODAL"}

            kind, value = hit
            if kind == "CLOSE":
                self.finish()
                return {"FINISHED"}
            if kind == "PUBLISH":
                self._dispatch_op(
                    context,
                    lambda: bpy.ops.iops.library_publish(
                        "INVOKE_DEFAULT", publish_kind=value
                    ),
                )
                self._area.tag_redraw()
                return {"RUNNING_MODAL"}
            if kind == "ASSET":
                self._dispatch_op(
                    context,
                    lambda: bpy.ops.iops.library_insert_asset(
                        "EXEC_DEFAULT", index=value
                    ),
                )
                self._area.tag_redraw()
                return {"RUNNING_MODAL"}
            if kind == "REMOVE":
                if bpy.ops.iops.library_remove_asset.poll():
                    self._dispatch_op(
                        context,
                        lambda: bpy.ops.iops.library_remove_asset(
                            "INVOKE_DEFAULT", mode="DELETE_ONE", index=value
                        ),
                    )
                else:
                    message = "Library is busy — try again in a moment."
                    context.window_manager.iops_library_status = message
                    self.report({"WARNING"}, message)
                self._area.tag_redraw()
                return {"RUNNING_MODAL"}
            if kind == "REFRESH":
                if bpy.ops.iops.library_refresh.poll():
                    self._dispatch_op(
                        context, lambda: bpy.ops.iops.library_refresh("INVOKE_DEFAULT")
                    )
                else:
                    message = "Library is busy — try again in a moment."
                    context.window_manager.iops_library_status = message
                    self.report({"WARNING"}, message)
                self._area.tag_redraw()
                return {"RUNNING_MODAL"}
            if kind == "CATEGORY":
                setattr(
                    context.window_manager,
                    value,
                    not getattr(context.window_manager, value),
                )
                self._scroll = min(self._scroll, self._max_scroll)
                self._area.tag_redraw()
                return {"RUNNING_MODAL"}
            if kind == "SIZE":
                preferences = get_prefs(context)
                old_right = self._panel_bounds[2]
                old_top = self._panel_bounds[3]
                preferences.library_preview_size = max(
                    3,
                    min(32, preferences.library_preview_size + value),
                )
                # Re-anchor so the TOP-RIGHT corner (where these controls
                # live) stays fixed -- otherwise the center-anchored panel
                # resizes the +/- buttons out from under the cursor.
                panel_x, panel_y, panel_width, panel_height, _tile = (
                    self.popup_metrics(context)
                )
                self._offset_x += old_right - (panel_x + panel_width)
                self._offset_y += old_top - (panel_y + panel_height)
                self._scroll = 0
                self._area.tag_redraw()
                return {"RUNNING_MODAL"}

        return {"RUNNING_MODAL"}

    def finish(self):
        global active_popup_operator

        if self._draw_handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._draw_handle, "WINDOW")
            self._draw_handle = None
        if self._area is not None:
            self._area.tag_redraw()
        self._area = None
        self._region = None
        if active_popup_operator is self:
            active_popup_operator = None

    def cancel(self, _context):
        self.finish()


def shutdown():
    global active_popup_operator
    if active_popup_operator is not None:
        active_popup_operator.finish()
        active_popup_operator = None
