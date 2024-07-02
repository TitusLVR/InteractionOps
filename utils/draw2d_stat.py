from os import name
from re import I
import bpy
import blf

from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
    FloatVectorProperty,
)


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

    if active_object and active_object.type == 'MESH':
        # UVMAPS
        uvmaps = ""
        for uvmap in active_object.data.uv_layers:
            #Add brackets and add active uvmap but not twice
            if uvmap == active_object.data.uv_layers.active:
                uvmaps += "[" + uvmap.name + "], "
            else:                
                uvmaps += uvmap.name + ", "
            #delete last comma
        uvmaps = uvmaps[:-2]

        # Check object scale for non-uniform scaling and negative scaling        
        scale = active_object.scale
        if scale[0] != scale[1] or scale[1] != scale[2] or scale[0] != scale[2]:
            uniform_scale_stat = "Non-uniform"
        else:
            uniform_scale_stat = "Uniform"

        if scale[0] < 0 or scale[1] < 0 or scale[2] < 0:
            negative_scale_stat = ", Negative scaling"
        else:
            negative_scale_stat = ""
        
        scale_stat = uniform_scale_stat + negative_scale_stat
    

        iops_text = [
            ["UVMaps:", str(uvmaps)],
            ["Scale:", str(scale_stat)],
        ]
    else:
        iops_text = [
            ["- - -", ""],
        ]

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
    
    rw = bpy.context.region.width#  - get_3d_view_tools_panel_overlay_width(bpy.context.area, "right")
    rh = bpy.context.region.height - 50 * uidpi
    
    offset_x = rw - tCPosX * uidpi
    offset_y = rh - tCPosY * uidpi
    
    
    columnoffs = (textsize * 6) * uidpi

    for line in reversed(iops_text):
        #Column 1
        blf.color(font, tColor[0], tColor[1], tColor[2], tColor[3])
        blf.position(font, offset_x, offset_y, 0)
        blf.draw(font, line[0])
        #Column 2

        if line[1] != "":
            blf.color(font, tKColor[0], tKColor[1], tKColor[2], tKColor[3])
        else:
            blf.color(font, tErrorColor[0], tErrorColor[1], tErrorColor[2], tErrorColor[3])
            line[1] = "No UVMaps"
        
        if line[0] == "Scale:" and line[1] != "Uniform":
            blf.color(font, tErrorColor[0], tErrorColor[1], tErrorColor[2], tErrorColor[3])

        blf.position(font, offset_x + columnoffs, offset_y, 0)
        blf.draw(font, line[1])
        offset_y += textsize * 1.5
        
