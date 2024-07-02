import bpy
import blf


def draw_iops_statistics():
    prefs = bpy.context.preferences.addons["InteractionOps"].preferences
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

    active_object = bpy.context.active_object
    # Check if active object is a mesh
    if active_object and active_object.type == "MESH":
        # Check if active object has UVMaps
        uvmaps = ""
        active_uvmap = ""
        if active_object.data.uv_layers:
            active_uvmap = active_object.data.uv_layers.active.name
            for uvmap in active_object.data.uv_layers:
                # Add brackets and add active uvmap but not twice
                # if uvmap != active_object.data.uv_layers.active:
                uvmaps += "" + uvmap.name + ", "
                # delete last comma
            if uvmaps:
                uvmaps = uvmaps[:-2]
        else:
            uvmaps = "No UVMaps"
        # Check object scale for non-uniform scaling and negative scaling
        scale = active_object.scale
        scale_info = ""
        if scale[0] != scale[1] or scale[1] != scale[2] or scale[0] != scale[2]:
            uniform_scale_stat = "Non-uniform"
        else:
            uniform_scale_stat = ""
        if scale[0] < 0 or scale[1] < 0 or scale[2] < 0:
            negative_scale_stat = ", Negative scaling"
        else:
            negative_scale_stat = ""

        scale_stat = uniform_scale_stat + negative_scale_stat

        if scale_stat == "":
            scale_info = "Uniform"

        #
        iops_text = [
            ["UVMaps:", str(uvmaps)],
            [str(scale_info), str(scale_stat)],
        ]
    else:
        iops_text = []

    # FontID
    font = 0
    blf.color(font, tColor[0], tColor[1], tColor[2], tColor[3])
    blf.size(font, tCSize)
    if tShadow:
        blf.enable(font, blf.SHADOW)
        blf.shadow(font, int(tSBlur), tSColor[0], tSColor[1], tSColor[2], tSColor[3])
        blf.shadow_offset(font, tSPosX, tSPosY)
    else:
        blf.disable(0, blf.SHADOW)

    textsize = tCSize
    uidpi = bpy.context.preferences.system.ui_scale
    try:
        area_3d = [area for area in bpy.context.screen.areas if area.type == "VIEW_3D"][
            0
        ]
        t_offset = 0
        for region in area_3d.regions:
            if region.type == "TOOLS":
                t_offset = region.width

        offset_x = tCPosX + t_offset
        offset_y = area_3d.height - tCPosY

        columnoffs = (textsize * 4) * uidpi
        if iops_text:
            for line in iops_text:
                if line[0] == "UVMaps:":
                    # Column 1
                    blf.color(font, tColor[0], tColor[1], tColor[2], tColor[3])
                    blf.position(font, offset_x, offset_y, 0)
                    blf.draw(font, line[0])

                    uvmaps_list = line[1].split(", ")

                    column_offset_x = offset_x + columnoffs
                    for uvmap in uvmaps_list:
                        # Column 2
                        blf.color(font, tColor[0], tColor[1], tColor[2], tColor[3])
                        if uvmap == active_uvmap:
                            blf.color(
                                font, tKColor[0], tKColor[1], tKColor[2], tKColor[3]
                            )
                        if line[0] == "UVMaps:" and line[1] == "No UVMaps":
                            blf.color(
                                font,
                                tErrorColor[0],
                                tErrorColor[1],
                                tErrorColor[2],
                                tErrorColor[3],
                            )

                        dim = blf.dimensions(font, uvmap)
                        blf.position(font, column_offset_x + dim[1] + 4, offset_y, 0)
                        blf.draw(font, uvmap)
                        column_offset_x += dim[0] + 6
                    offset_y -= textsize * 1.5

                elif line[0] != "Uniform" and line[1] != "":
                    # Column 1
                    line[0] = "Scaling:"
                    blf.color(font, tColor[0], tColor[1], tColor[2], tColor[3])
                    blf.position(font, offset_x, offset_y, 0)
                    blf.draw(font, line[0])
                    # Column 2
                    blf.color(
                        font,
                        tErrorColor[0],
                        tErrorColor[1],
                        tErrorColor[2],
                        tErrorColor[3],
                    )
                    blf.position(font, offset_x + columnoffs + 4, offset_y, 0)
                    blf.draw(font, line[1])
                    offset_y -= textsize * 1.5
        else:
            blf.color(font, tColor[0], tColor[1], tColor[2], tColor[3])
            blf.position(font, offset_x, offset_y, 0)
            blf.draw(font, "- - -")
    except Exception:
        pass
