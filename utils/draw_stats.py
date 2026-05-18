import os
import bpy

from ..ui.draw.theme import get_theme, Role
from ..ui.hud.text import draw as hud_text_draw, measure as hud_text_measure


def draw_iops_statistics():
    context = bpy.context
    if not context.area or context.area.type != "VIEW_3D":
        return
    if not context.region or context.region.type != "WINDOW":
        return

    try:
        prefs = context.preferences.addons["InteractionOps"].preferences
    except KeyError:
        return
    if not prefs.iops_stat:
        return

    area_3d = context.area
    space_3d = context.space_data
    show_overlays = space_3d.overlay.show_overlays if space_3d else True

    theme = get_theme(context)

    # Stat overlay sits in the top-left of the 3D view, offset from the
    # toolbar (TOOLS region). Position uses the unified HUD padding.
    t_offset = 0
    for region in area_3d.regions:
        if region.type == "TOOLS":
            t_offset = region.width
            break

    pad = theme.hud.padding
    offset_x = t_offset + pad
    line_h = theme.text_size("default")
    offset_y = area_3d.height - pad - line_h

    base_column_x = offset_x + line_h * 9

    def _t(text, *, role=None, color=None, x=offset_x, y=None):
        if y is None:
            y = offset_y
        eff_color = color
        if eff_color is None and role is not None:
            r, g, b, a = theme.color_for(role)
            eff_color = (r, g, b, a * (1.0 if show_overlays else 0.0))
        hud_text_draw(text, int(x), int(y), theme=theme,
                      color=eff_color, role=role,
                      alpha_mul=(1.0 if show_overlays else 0.0))

    def _dim(text):
        return hud_text_measure(text, theme=theme)

    active_object = context.active_object

    try:
        if prefs.show_filename_stat:
            file_saved = bpy.data.is_saved
            file_dirty = bpy.data.is_dirty
            if file_saved and bpy.data.filepath:
                filename = os.path.basename(bpy.data.filepath)
                file_status = filename + "*" if file_dirty else filename
            else:
                file_status = "Unsaved"

            _t("File:", role=Role.TEXT)
            value_role = Role.CLOSEST_TEXT if (file_saved and not file_dirty) else Role.ERROR
            _t(file_status, role=value_role, x=base_column_x)
            offset_y -= int(line_h * 1.5)

        if active_object and active_object.type == "MESH":
            scale_stat = []
            scale = active_object.scale
            if scale[0] != 1 and scale[1] != 1 and scale[2] != 1:
                scale_stat.append("≠ 1")
            if scale[0] != scale[1] or scale[1] != scale[2] or scale[0] != scale[2]:
                scale_stat.append("Non-uniform")
            if scale[0] < 0 or scale[1] < 0 or scale[2] < 0:
                scale_stat.append("Negative")

            all_uvmap_names = []
            active_uvmaps = set()
            render_uvmaps = set()
            seen = set()
            selected_meshes = [
                obj for obj in context.selected_objects if obj.type == "MESH"
            ]
            if active_object not in selected_meshes:
                selected_meshes.insert(0, active_object)
            for obj in selected_meshes:
                obj_data = obj.data
                if not obj_data.uv_layers:
                    continue
                if obj_data.uv_layers.active:
                    active_uvmaps.add(obj_data.uv_layers.active.name)
                for uv in obj_data.uv_layers:
                    if uv.name not in seen:
                        seen.add(uv.name)
                        all_uvmap_names.append(uv.name)
                    if uv.active_render:
                        render_uvmaps.add(uv.name)

            _t("UVMaps:", role=Role.TEXT)
            col_x = base_column_x
            if all_uvmap_names:
                for uvmap in all_uvmap_names:
                    is_render = uvmap in render_uvmaps
                    display = "[ " + uvmap + " ]" if is_render else uvmap
                    role = Role.CLOSEST_TEXT if uvmap in active_uvmaps else Role.TEXT
                    _t(display, role=role, x=col_x)
                    w, _h = _dim(display)
                    col_x += w + 6
                offset_y -= int(line_h * 1.5)
            else:
                _t("No UVMaps", role=Role.ERROR, x=base_column_x)
                offset_y -= int(line_h * 1.5)

            if scale_stat:
                _t("Scale:", role=Role.TEXT)
                col_x = base_column_x
                for s in scale_stat:
                    _t(s, role=Role.ERROR, x=col_x)
                    w, _h = _dim(s)
                    col_x += w + 6
                offset_y -= int(line_h * 1.5)
        else:
            _t("- - -", role=Role.TEXT)

        if context.selected_objects:
            scaled_objects = []
            for obj in context.selected_objects:
                if obj.type != "MESH":
                    continue
                if obj is active_object:
                    continue
                s = obj.scale
                if s[0] != 1 or s[1] != 1 or s[2] != 1:
                    scaled_objects.append(obj)
            if scaled_objects:
                _t("Selection:", role=Role.TEXT)
                _t("There are scaled objects", role=Role.ERROR, x=base_column_x)
                offset_y -= int(line_h * 1.5)

    except Exception:
        pass
