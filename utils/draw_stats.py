import bpy
import blf

def draw_iops_statistics():
    prefs = bpy.context.preferences.addons["InteractionOps"].preferences
    if prefs.iops_stat:
        active_object = bpy.context.active_object
        selected_objects = [ob for ob in bpy.context.selected_objects if ob.type == "MESH"]
        try:
            # Text settings
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
            # FontID
            font = 0
            blf.size(font, tCSize)
            if tShadow:
                blf.enable(font, blf.SHADOW)
                blf.shadow(font, int(tSBlur), tSColor[0], tSColor[1], tSColor[2], tSColor[3])
                blf.shadow_offset(font, tSPosX, tSPosY)
            else:
                blf.disable(0, blf.SHADOW)

            textsize = tCSize
            uidpi = bpy.context.preferences.system.ui_scale
            #End of text settings

            # Check if overlays are enabled
            area_3d = [area for area in bpy.context.screen.areas if area.type == "VIEW_3D"][
                0
            ]
            for space in area_3d.spaces:
                if space.type == "VIEW_3D":
                    show_overlays = space.overlay.show_overlays

            tColor = (tColor[0], tColor[1], tColor[2], tColor[3] * show_overlays)
            tKColor = (tKColor[0], tKColor[1], tKColor[2], tKColor[3] * show_overlays)
            tErrorColor = (
                tErrorColor[0],
                tErrorColor[1],
                tErrorColor[2],
                tErrorColor[3] * show_overlays,
            )

            t_offset = 0
            for region in area_3d.regions:
                if region.type == "TOOLS":
                    t_offset = region.width

            offset_x = tCPosX + t_offset
            offset_y = area_3d.height - tCPosY
            size_multiplier = textsize * uidpi

            if active_object and active_object.type == "MESH":
                # Check if active object has UVMaps
                uvmaps = []
                scale_stat = []
                selected_scale_stat = []
                if active_object and active_object.type == "MESH":
                    active_uvmap = ""
                    active_render = ""
                    # Collect UV data
                    if active_object.data.uv_layers:
                        active_uvmap = active_object.data.uv_layers.active.name
                        for uvmap in active_object.data.uv_layers:
                            uvmaps.append(uvmap.name)
                            # Get active render uvmap
                            if uvmap.active_render:
                                active_render = uvmap.name
                    # Check object scale for non-uniform scaling and negative scaling
                    scale = active_object.scale
                    #more than one scale value
                    if scale[0] != 1 and scale[1] != 1 and scale[2] != 1:
                        scale_stat.append("≠ 1")
                    #non-uniform scale
                    if scale[0] != scale[1] or scale[1] != scale[2] or scale[0] != scale[2]:
                        scale_stat.append("Non-uniform")
                    if scale[0] < 0 or scale[1] < 0 or scale[2] < 0:
                        scale_stat.append("Negative")

                # Draw UVMaps and Scale info list
                active_object_stats = [
                    ["UVMaps:", uvmaps],
                    ["Scale:", scale_stat],
                ]
                # k-key, v-value
                for k, v in active_object_stats:
                    if k == "UVMaps:":
                        # Column 1
                        blf.color(font, tColor[0], tColor[1], tColor[2], tColor[3])
                        blf.position(font, offset_x, offset_y, 0)
                        blf.draw(font, k)

                        column_offset_x = offset_x + size_multiplier + tColumnOffset
                        if v:
                            for uvmap in v:
                                # Column N
                                blf.color(font, tColor[0], tColor[1], tColor[2], tColor[3])
                                if uvmap == active_render:
                                    uvmap = "[ " + uvmap + " ]"
                                if (
                                    uvmap == active_uvmap
                                    or uvmap == "[ " + active_uvmap + " ]"
                                ):
                                    blf.color(
                                        font, tKColor[0], tKColor[1], tKColor[2], tKColor[3]
                                    )

                                dim = blf.dimensions(font, uvmap)
                                blf.position(font, column_offset_x + dim[1], offset_y, 0)
                                blf.draw(font, uvmap)
                                column_offset_x += dim[0] + tColumnWidth
                            offset_y -= textsize * 1.5
                        else:
                            blf.color(
                                font,
                                tErrorColor[0],
                                tErrorColor[1],
                                tErrorColor[2],
                                tErrorColor[3],
                            )
                            column_offset_x = offset_x + size_multiplier + tColumnOffset
                            blf.position(font, column_offset_x + len("No UVMaps") + tColumnWidth, offset_y, 0)
                            blf.draw(font, "No UVMaps")
                            offset_y -= textsize * 1.5

                    if k == "Scale:" and v != []:
                        # Column 1
                        blf.color(font, tColor[0], tColor[1], tColor[2], tColor[3])
                        blf.position(font, offset_x, offset_y, 0)
                        blf.draw(font, k)
                        column_offset_x = offset_x + size_multiplier + tColumnOffset
                        for scale in v:
                            # Column N
                            blf.color(
                                font,
                                tErrorColor[0],
                                tErrorColor[1],
                                tErrorColor[2],
                                tErrorColor[3],
                            )
                            dim = blf.dimensions(font, scale)
                            blf.position(font, column_offset_x + dim[1] + 3, offset_y, 0)
                            blf.draw(font, scale)
                            column_offset_x += dim[0] + tColumnWidth
                        offset_y -= textsize * 1.5
            else:
                blf.color(font, tColor[0], tColor[1], tColor[2], tColor[3])
                blf.position(font, offset_x, offset_y, 0)
                blf.draw(font, "- - -")

            # Check if there are a non-uniform scale or negative scaling in selected_objects just add "Scaled objects in selection" to the list
            if selected_objects:
                scaled_objects = []
                for obj in selected_objects:
                    if obj != active_object:
                        scale = obj.scale
                        if scale[0] != 1 or scale[1] != 1 or scale[2] != 1:
                            scaled_objects.append(obj)
                # Check if there are scaled objects in selection and add to the list
                if scaled_objects:
                    selected_scale_stat.append("There are scaled objects")

                # Draw UVMaps and Scale info list
                selected_objects_stats = [
                    ["Selection:", selected_scale_stat]
                ]

                # k-key, v-value
                for k, v in selected_objects_stats:
                    if k == "Selection:" and v != []:
                        # Column 1
                        blf.color(font, tColor[0], tColor[1], tColor[2], tColor[3])
                        blf.position(font, offset_x, offset_y, 0)
                        blf.draw(font, k)
                        column_offset_x = offset_x + size_multiplier + tColumnOffset
                        for scale in v:
                            # Column N
                            blf.color(
                                font,
                                tErrorColor[0],
                                tErrorColor[1],
                                tErrorColor[2],
                                tErrorColor[3],
                            )
                            dim = blf.dimensions(font, scale)
                            blf.position(font, column_offset_x + dim[1] + 3, offset_y, 0)
                            blf.draw(font, scale)
                            column_offset_x += dim[0] + tColumnWidth
                        offset_y -= textsize * 1.5

        except Exception:
            pass
    else:
        return 0
