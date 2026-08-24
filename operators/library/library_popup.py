"""GPU-overlay popup operator for the ported library addon.

Draws a floating asset-picker panel (category rows + a preview grid) directly
into the 3D viewport with ``blf``/``gpu`` calls from a modal operator, rather
than a regular ``bpy.types.Panel``. Mirrors the source addon's popup pixel-for
-pixel: metrics arithmetic, colors, scissor clipping, hover/hitbox handling,
and scroll clamping are all ported as-is.
"""

import blf
import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from gpu_extras.presets import draw_texture_2d

from .common import (
    catalog_needs_sync,
    get_catalog,
    get_prefs,
    overlay_texture,
    placement_from_mouse,
    sync_catalog,
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


def draw_overlay_text(text, x, y, size=12, color=(0.88, 0.88, 0.88, 1.0)):
    font_id = 0
    blf.color(font_id, *color)
    blf.position(font_id, x, y, 0)
    blf.size(font_id, size)
    blf.draw(font_id, text)


def point_in_bounds(x, y, bounds):
    left, bottom, right, top = bounds
    return left <= x <= right and bottom <= y <= top


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

    header_height = 32
    category_height = 26
    label_height = 24
    padding = 10
    gap = 7

    def invoke(self, context, event):
        global active_popup_operator

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
            synced, message = sync_catalog(context, report_status=False)
            if not synced:
                self.report({"ERROR"}, message)
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
        panel_x = max(8, min(panel_x, self._region.width - panel_width - 8))
        below = self._anchor_y - panel_height - 12
        if below >= 8:
            panel_y = below
        else:
            panel_y = min(
                self._region.height - panel_height - 8,
                self._anchor_y + 12,
            )
        panel_y = max(8, panel_y)
        return panel_x, panel_y, panel_width, panel_height, tile_size

    def add_hitbox(self, kind, value, bounds):
        self._hitboxes.append((kind, value, bounds))

    def draw_header_button(self, label, kind, value, bounds):
        hovered = self._hover_key == (kind, value)
        color = (0.24, 0.24, 0.24, 1.0) if hovered else (0.15, 0.15, 0.15, 1.0)
        left, bottom, right, top = bounds
        draw_overlay_rectangle(left, bottom, right - left, top - bottom, color)
        blf.size(0, 11)
        text_width = blf.dimensions(0, label)[0]
        draw_overlay_text(
            label,
            left + max(5, (right - left - text_width) * 0.5),
            bottom + 6,
            11,
        )
        self.add_hitbox(kind, value, bounds)

    def draw_overlay(self):
        context = bpy.context
        preferences = get_prefs(context)
        if preferences is None or self._region is None:
            return

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
            (0.24, 0.24, 0.24, 1.0),
        )
        draw_overlay_rectangle(
            panel_x,
            panel_y,
            panel_width,
            panel_height,
            (0.055, 0.055, 0.055, 0.98),
        )
        draw_overlay_rectangle(
            panel_x,
            panel_top - self.header_height,
            panel_width,
            self.header_height,
            (0.09, 0.09, 0.09, 1.0),
        )
        draw_overlay_text(
            "IOPS Library",
            panel_x + 11,
            panel_top - 22,
            13,
            (0.95, 0.95, 0.95, 1.0),
        )

        control_top = panel_top - 5
        control_bottom = control_top - 22
        right = panel_x + panel_width - 7
        refresh_bounds = (right - 62, control_bottom, right, control_top)
        self.draw_header_button("Refresh", "REFRESH", 0, refresh_bounds)
        right = refresh_bounds[0] - 5
        plus_bounds = (right - 22, control_bottom, right, control_top)
        self.draw_header_button("+", "SIZE", 1, plus_bounds)
        right = plus_bounds[0]
        size_bounds = (right - 50, control_bottom, right, control_top)
        self.draw_header_button(
            "Size %d" % preferences.library_preview_size,
            "NONE",
            0,
            size_bounds,
        )
        right = size_bounds[0]
        minus_bounds = (right - 22, control_bottom, right, control_top)
        self.draw_header_button("-", "SIZE", -1, minus_bounds)

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
                        (0.18, 0.18, 0.18, 1.0)
                        if hovered
                        else (0.115, 0.115, 0.115, 1.0)
                    )
                    draw_overlay_rectangle(
                        category_bounds[0],
                        category_bounds[1],
                        category_bounds[2] - category_bounds[0],
                        self.category_height - 1,
                        color,
                    )
                    draw_overlay_text(
                        "v" if expanded else ">",
                        category_bounds[0] + 7,
                        category_bottom + 7,
                        11,
                    )
                    draw_overlay_text(
                        "%s (%d)" % (label, len(entries)),
                        category_bounds[0] + 23,
                        category_bottom + 7,
                        11,
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
                            (0.20, 0.20, 0.20, 1.0)
                            if hovered
                            else (0.095, 0.095, 0.095, 1.0)
                        )
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
                            blf.size(0, 11)
                            text_width = blf.dimensions(0, fallback)[0]
                            draw_overlay_text(
                                fallback,
                                x + max(5, (tile_size - text_width) * 0.5),
                                image_bottom + tile_size * 0.5 - 5,
                                11,
                                (0.65, 0.65, 0.65, 1.0),
                            )
                        self.add_hitbox("ASSET", index, image_bounds)

                        draw_overlay_rectangle(
                            label_bounds[0],
                            label_bounds[1],
                            tile_size,
                            self.label_height - 1,
                            (0.12, 0.12, 0.12, 1.0),
                        )
                        maximum_characters = max(5, int((tile_size - 28) / 7))
                        asset_label = entry.asset_name
                        if len(asset_label) > maximum_characters:
                            asset_label = asset_label[: maximum_characters - 3] + "..."
                        draw_overlay_text(
                            asset_label,
                            x + 6,
                            label_bottom + 6,
                            10,
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
                                (0.32, 0.12, 0.10, 1.0),
                            )
                        draw_overlay_text(
                            "X",
                            remove_bounds[0] + 7,
                            remove_bounds[1] + 6,
                            10,
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
        if event.type in {"ESC", "RIGHTMOUSE"}:
            self.finish()
            return {"CANCELLED"}

        x = event.mouse_region_x
        y = event.mouse_region_y
        hit = self.hitbox_at(x, y)
        hover_key = hit
        if hover_key != self._hover_key:
            self._hover_key = hover_key
            self._area.tag_redraw()

        if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            if point_in_bounds(x, y, self._panel_bounds):
                direction = -1 if event.type == "WHEELUPMOUSE" else 1
                self._scroll = max(
                    0,
                    min(self._max_scroll, self._scroll + direction * 60),
                )
                self._area.tag_redraw()
            return {"RUNNING_MODAL"}

        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            if hit is None:
                if not point_in_bounds(x, y, self._panel_bounds):
                    self.finish()
                    return {"CANCELLED"}
                return {"RUNNING_MODAL"}

            kind, value = hit
            if kind == "ASSET":
                self.finish()
                return bpy.ops.iops.library_insert_asset(
                    "EXEC_DEFAULT",
                    index=value,
                )
            if kind == "REMOVE":
                self.finish()
                bpy.ops.iops.library_remove_asset(
                    "INVOKE_DEFAULT",
                    mode="DELETE_ONE",
                    index=value,
                )
                return {"FINISHED"}
            if kind == "REFRESH":
                self.finish()
                bpy.ops.iops.library_refresh("EXEC_DEFAULT")
                return {"FINISHED"}
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
                preferences.library_preview_size = max(
                    3,
                    min(8, preferences.library_preview_size + value),
                )
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
