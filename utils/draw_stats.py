import os
import bpy
import blf

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
    # Single lookup for overlay (context.space_data is this View3D's space)
    space_3d = context.space_data
    show_overlays = space_3d.overlay.show_overlays if space_3d else True

    # Cache prefs in locals
    tColor = prefs.text_color_stat
    tKColor = prefs.text_color_key_stat
    tErrorColor = prefs.text_color_error_stat
    tCSize = prefs.text_size_stat
    tCPosX = prefs.text_pos_x_stat
    tCPosY = prefs.text_pos_y_stat
    tShadow = prefs.text_shadow_toggle_stat
    tSColor = prefs.text_shadow_color_stat
    tSBlur = prefs.text_shadow_blur_stat
    tSPosX = prefs.text_shadow_pos_x_stat
    tSPosY = prefs.text_shadow_pos_y_stat
    tColumnOffset = prefs.text_column_offset_stat
    tColumnWidth = prefs.text_column_width_stat

    tColor = (tColor[0], tColor[1], tColor[2], tColor[3] * show_overlays)
    tKColor = (tKColor[0], tKColor[1], tKColor[2], tKColor[3] * show_overlays)
    tErrorColor = (
        tErrorColor[0], tErrorColor[1], tErrorColor[2],
        tErrorColor[3] * show_overlays,
    )

    t_offset = 0
    for region in area_3d.regions:
        if region.type == "TOOLS":
            t_offset = region.width
            break

    offset_x = tCPosX + t_offset
    offset_y = area_3d.height - tCPosY
    uidpi = context.preferences.system.ui_scale
    size_multiplier = tCSize * uidpi
    base_column_x = offset_x + size_multiplier + tColumnOffset

    font = 0
    blf.size(font, tCSize)
    if tShadow:
        blf.enable(font, blf.SHADOW)
        blf.shadow(font, int(tSBlur), tSColor[0], tSColor[1], tSColor[2], tSColor[3])
        blf.shadow_offset(font, tSPosX, tSPosY)
    else:
        blf.disable(font, blf.SHADOW)

    textsize = tCSize
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

            blf.color(font, tColor[0], tColor[1], tColor[2], tColor[3])
            blf.position(font, offset_x, offset_y, 0)
            blf.draw(font, "File:")
            if file_saved and not file_dirty:
                blf.color(font, tKColor[0], tKColor[1], tKColor[2], tKColor[3])
            else:
                blf.color(font, tErrorColor[0], tErrorColor[1], tErrorColor[2], tErrorColor[3])
            dim = blf.dimensions(font, file_status)
            blf.position(font, base_column_x + dim[1], offset_y, 0)
            blf.draw(font, file_status)
            offset_y -= textsize * 1.5

        if active_object and active_object.type == "MESH":
            data = active_object.data
            uvmaps = []
            scale_stat = []
            active_uvmap = ""
            active_render = ""
            if data.uv_layers:
                active_uvmap = data.uv_layers.active.name
                for uv in data.uv_layers:
                    uvmaps.append(uv.name)
                    if uv.active_render:
                        active_render = uv.name
            scale = active_object.scale
            if scale[0] != 1 and scale[1] != 1 and scale[2] != 1:
                scale_stat.append("≠ 1")
            if scale[0] != scale[1] or scale[1] != scale[2] or scale[0] != scale[2]:
                scale_stat.append("Non-uniform")
            if scale[0] < 0 or scale[1] < 0 or scale[2] < 0:
                scale_stat.append("Negative")

            # UVMaps line
            blf.color(font, tColor[0], tColor[1], tColor[2], tColor[3])
            blf.position(font, offset_x, offset_y, 0)
            blf.draw(font, "UVMaps:")
            col_x = base_column_x
            if uvmaps:
                for uvmap in uvmaps:
                    is_render = uvmap == active_render
                    display = "[ " + uvmap + " ]" if is_render else uvmap
                    if uvmap == active_uvmap:
                        blf.color(font, tKColor[0], tKColor[1], tKColor[2], tKColor[3])
                    else:
                        blf.color(font, tColor[0], tColor[1], tColor[2], tColor[3])
                    dim = blf.dimensions(font, display)
                    blf.position(font, col_x + dim[1], offset_y, 0)
                    blf.draw(font, display)
                    col_x += dim[0] + tColumnWidth
                offset_y -= textsize * 1.5
            else:
                blf.color(font, tErrorColor[0], tErrorColor[1], tErrorColor[2], tErrorColor[3])
                blf.position(font, base_column_x + 9 + tColumnWidth, offset_y, 0)
                blf.draw(font, "No UVMaps")
                offset_y -= textsize * 1.5

            # Scale line (only if any scale warnings)
            if scale_stat:
                blf.color(font, tColor[0], tColor[1], tColor[2], tColor[3])
                blf.position(font, offset_x, offset_y, 0)
                blf.draw(font, "Scale:")
                blf.color(font, tErrorColor[0], tErrorColor[1], tErrorColor[2], tErrorColor[3])
                col_x = base_column_x
                for s in scale_stat:
                    dim = blf.dimensions(font, s)
                    blf.position(font, col_x + dim[1] + 3, offset_y, 0)
                    blf.draw(font, s)
                    col_x += dim[0] + tColumnWidth
                offset_y -= textsize * 1.5
        else:
            blf.color(font, tColor[0], tColor[1], tColor[2], tColor[3])
            blf.position(font, offset_x, offset_y, 0)
            blf.draw(font, "- - -")

        # Selection scaled warning (only build list when there are selected objects)
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
                blf.color(font, tColor[0], tColor[1], tColor[2], tColor[3])
                blf.position(font, offset_x, offset_y, 0)
                blf.draw(font, "Selection:")
                blf.color(font, tErrorColor[0], tErrorColor[1], tErrorColor[2], tErrorColor[3])
                col_x = base_column_x
                msg = "There are scaled objects"
                dim = blf.dimensions(font, msg)
                blf.position(font, col_x + dim[1] + 3, offset_y, 0)
                blf.draw(font, msg)
                offset_y -= textsize * 1.5

    except Exception:
        pass
