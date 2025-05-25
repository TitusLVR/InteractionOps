import bpy
import json
import os

from .operators.hotkeys.load_hotkeys import (
    IOPS_OT_LoadUserHotkeys,
    IOPS_OT_LoadDefaultHotkeys,
)
from .operators.hotkeys.save_hotkeys import IOPS_OT_SaveUserHotkeys

from .operators.preferences.io_addon_preferences import (
    IOPS_OT_SaveAddonPreferences,
    IOPS_OT_LoadAddonPreferences,
)

from .operators.align_origin_to_normal import IOPS_OT_AlignOriginToNormal
from .operators.mouseover_fill_select import IOPS_MouseoverFillSelect
from .operators.materials_from_textures import IOPS_OT_MaterialsFromTextures
from .operators.cursor_origin.mesh import IOPS_OT_CursorOrigin_Mesh
from .operators.curve_spline_type import IOPS_OT_CurveSplineType
from .operators.curve_subdivide import IOPS_OT_CurveSubdivide
from .operators.grid_from_active import IOPS_OT_ToGridFromActive
from .operators.iops import IOPS_OT_Main
from .operators.library_reload import IOPS_OT_Reload_Libraries
from .operators.image_reload import IOPS_OT_Reload_Images
from .operators.maya_isolate import IOPS_OT_MayaIsolate
from .operators.split_screen_area import IOPS_OT_SwitchScreenArea
from .operators.outliner_collection_ops import (
    IOPS_OT_Collections_Include,
    IOPS_OT_Collections_Exclude,
)

if bpy.app.version[0] < 3:
    from .operators.split_screen_area import IOPS_OT_SplitScreenArea
else:
    from .operators.split_screen_area_new import IOPS_OT_SplitScreenArea

from .operators.mesh_convert_selection import (
    IOPS_OT_ToEdges,
    IOPS_OT_ToFaces,
    IOPS_OT_ToVerts,
)

from .operators.modes import (
    IOPS_OT_ESC,
    IOPS_OT_F1,
    IOPS_OT_F2,
    IOPS_OT_F3,
    IOPS_OT_F4,
    IOPS_OT_F5,
)

from .operators.object_align_to_face import IOPS_OT_AlignObjectToFace
from .operators.object_match_transform_active import IOPS_OT_MatchTransformActive
from .operators.mesh_to_grid import IOPS_OT_mesh_to_grid
from .operators.mesh_copy_edges_length import IOPS_MESH_OT_CopyEdgesLength
from .operators.mesh_copy_edges_angle import IOPS_MESH_OT_CopyEdgesAngle
from .operators.drag_snap import IOPS_OT_DragSnap
from .operators.drag_snap_uv import IOPS_OT_DragSnapUV
from .operators.drag_snap_cursor import IOPS_OT_DragSnapCursor
from .operators.object_normalize import IOPS_OT_object_normalize
from .operators.object_replace import IOPS_OT_Object_Replace
from .operators.object_rotate import (
    IOPS_OT_object_rotate_MX,
    IOPS_OT_object_rotate_MY,
    IOPS_OT_object_rotate_MZ,
    IOPS_OT_object_rotate_X,
    IOPS_OT_object_rotate_Y,
    IOPS_OT_object_rotate_Z,
)
from .operators.object_auto_smooth import IOPS_OT_AutoSmooth, IOPS_OT_ClearCustomNormals

from .operators.object_three_point_rotation import IOPS_OT_ThreePointRotation
from .operators.object_visual_origin import IOPS_OT_VisualOrigin
from .operators.mesh_quick_snap import IOPS_OT_Mesh_QuickSnap

from .operators.save_load_space_data import IOPS_OT_LoadSpaceData, IOPS_OT_SaveSpaceData

from .prefs.addon_preferences import IOPS_AddonPreferences
from .prefs.addon_properties import IOPS_AddonProperties
from .prefs.addon_properties import IOPS_SceneProperties

from .operators.assign_vertex_color import (
    IOPS_OT_VertexColorAssign,
    IOPS_OT_VertexColorAlphaAssign,
)
from .operators.object_drop_it import IOPS_OT_Drop_It
from .operators.object_kitbash_grid import IOPS_OT_KitBash_Grid
from .operators.align_between_two import IOPS_OT_Align_between_two

from .ui.iops_tm_panel import (
    IOPS_OT_edit_origin,
    IOPS_OT_transform_orientation_create,
    IOPS_OT_transform_orientation_cleanup,
    IOPS_OT_transform_orientation_delete,
    IOPS_OT_homonize_uvmaps_names,
    IOPS_OT_uvmaps_cleanup,
    IOPS_PT_TPS_Panel,
    IOPS_PT_TM_Panel,
    IOPS_OT_Call_TPS_Panel,
    IOPS_OT_Call_TM_Panel,
    IOPS_PT_VCol_Panel,
)

from .ui.iops_data_panel import IOPS_PT_DATA_Panel, IOPS_OT_Call_Data_Panel

from .ui.iops_pie_split import (
    IOPS_OT_Split_Area_Pie_1,
    IOPS_OT_Split_Area_Pie_2,
    IOPS_OT_Split_Area_Pie_3,
    IOPS_OT_Split_Area_Pie_4,
    IOPS_OT_Split_Area_Pie_6,
    IOPS_OT_Split_Area_Pie_7,
    IOPS_OT_Split_Area_Pie_8,
    IOPS_OT_Split_Area_Pie_9,
    IOPS_MT_Pie_Split,
    IOPS_OT_Call_Pie_Split,
)

from .ui.iops_pie_menu import IOPS_MT_Pie_Menu, IOPS_OT_Call_Pie_Menu
from .ui.iops_pie_edit import IOPS_MT_Pie_Edit, IOPS_OT_Call_Pie_Edit
from .operators.z_ops import (
    Z_OT_GrowLoop,
    Z_OT_ShrinkLoop,
    Z_OT_GrowRing,
    Z_OT_ShrinkRing,
    Z_OT_SelectBoundedLoop,
    Z_OT_SelectBoundedRing,
    Z_OT_EdgeEq,
    Z_OT_EdgeLineUp,
    Z_OT_ContextDelete,
    Z_OT_PutOn,
    Z_OT_Mirror,
    Z_OT_EdgeConnect,
)

from .operators.easy_mod_curve import IOPS_OT_Easy_Mod_Curve
from .operators.easy_mod_array import (
    IOPS_OT_Easy_Mod_Array_Caps,
    IOPS_OT_Easy_Mod_Array_Curve,
)
from .operators.easy_mod_shwarp import IOPS_OT_Easy_Mod_Shwarp
from .operators.object_name_from_active import IOPS_OT_Object_Name_From_Active

from .operators.object_uvmaps_cleaner import (
    IOPS_OT_Clean_UVMap_0,
    IOPS_OT_Clean_UVMap_1,
    IOPS_OT_Clean_UVMap_2,
    IOPS_OT_Clean_UVMap_3,
    IOPS_OT_Clean_UVMap_4,
    IOPS_OT_Clean_UVMap_5,
    IOPS_OT_Clean_UVMap_6,
    IOPS_OT_Clean_UVMap_7,
)

from .operators.object_uvmaps_add_remove import (
    IOPS_OT_Add_UVMap,
    IOPS_OT_Remove_UVMap_by_Active_Name,
    IOPS_OT_Active_UVMap_by_Active,
)

from .operators.executor import (
    IOPS_OT_Executor,
    IOPS_PT_ExecuteList,
    IOPS_OT_Call_MT_Executor,
)
from .operators.render_asset_thumbnail import IOPS_OT_RenderAssetThumbnail
from .operators.run_text import IOPS_OT_RunText
from .operators.ui_prop_switch import (
    IOPS_OT_ActiveObject_Scroll_UP,
    IOPS_OT_ActiveObject_Scroll_DOWN,
)
from .operators.snap_combos import IOPS_OT_SetSnapCombo


from .utils.functions import register_keymaps, unregister_keymaps, fix_old_keymaps

# Hotkeys
from .prefs.hotkeys_default import keys_default as keys_default

# Preferences
from .operators.preferences.io_addon_preferences import load_iops_preferences

# IOPS Statistics
from .utils.draw_stats import draw_iops_statistics

# IOPS UV Channel Hop
from .operators.mesh_uv_channel_hop import IOPS_OT_Mesh_UV_Channel_Hop

# IOPS Cursor rotate
from .operators.cursor_rotate import IOPS_OT_Cursor_Rotate

# IOPS Edge bisect with cursor
from .operators.mesh_cursor_bisect import IOPS_OT_Mesh_Cursor_Bisect

# Open asset in current Blender
from .operators.open_asset_in_current_blender import IOPS_OT_OpenAssetInCurrentBlender

bl_info = {
    "name": "iOps",
    "authors": "Titus, Cyrill, Aleksey",
    "version": (2, 1, 3),
    "blender": (4, 2, 0),
    "location": "View3D > Toolbar and View3D",
    "description": "iOPS - Boost your Blender Interactivity :p",
    "warning": "",
    "wiki_url": "https://interactionops-docs.readthedocs.io/en/latest/index.html",
    "tracker_url": "https://github.com/TitusLVR/InteractionOps/issues",
    "category": "Tools",
}


# Classes for reg and unreg
classes = (
    IOPS_AddonPreferences,
    IOPS_AddonProperties,
    IOPS_SceneProperties,
    IOPS_OT_Collections_Include,
    IOPS_OT_Collections_Exclude,
    IOPS_OT_Main,
    IOPS_OT_F1,
    IOPS_OT_F2,
    IOPS_OT_F3,
    IOPS_OT_F4,
    IOPS_OT_F5,
    IOPS_OT_ESC,
    IOPS_OT_CursorOrigin_Mesh,
    IOPS_OT_CurveSubdivide,
    IOPS_OT_CurveSplineType,
    IOPS_OT_ToFaces,
    IOPS_OT_ToEdges,
    IOPS_OT_ToVerts,
    IOPS_OT_AlignObjectToFace,
    IOPS_OT_Align_between_two,
    IOPS_OT_VisualOrigin,
    IOPS_OT_AutoSmooth,
    IOPS_OT_ClearCustomNormals,
    IOPS_OT_object_rotate_Z,
    IOPS_OT_object_rotate_MZ,
    IOPS_OT_object_rotate_Y,
    IOPS_OT_object_rotate_MY,
    IOPS_OT_object_rotate_X,
    IOPS_OT_object_rotate_MX,
    IOPS_OT_object_normalize,
    IOPS_OT_Object_Replace,
    IOPS_OT_ToGridFromActive,
    IOPS_OT_transform_orientation_create,
    IOPS_OT_transform_orientation_delete,
    IOPS_OT_transform_orientation_cleanup,
    IOPS_OT_homonize_uvmaps_names,
    IOPS_OT_uvmaps_cleanup,
    IOPS_OT_edit_origin,
    IOPS_OT_mesh_to_grid,
    IOPS_OT_ThreePointRotation,
    IOPS_OT_AlignOriginToNormal,
    IOPS_OT_MatchTransformActive,
    IOPS_PT_TM_Panel,
    IOPS_OT_Call_TM_Panel,
    IOPS_PT_TPS_Panel,
    IOPS_OT_Call_TPS_Panel,
    IOPS_MT_Pie_Menu,
    IOPS_OT_Call_Pie_Menu,
    IOPS_MT_Pie_Edit,
    IOPS_OT_Split_Area_Pie_1,
    IOPS_OT_Split_Area_Pie_2,
    IOPS_OT_Split_Area_Pie_3,
    IOPS_OT_Split_Area_Pie_4,
    IOPS_OT_Split_Area_Pie_6,
    IOPS_OT_Split_Area_Pie_7,
    IOPS_OT_Split_Area_Pie_8,
    IOPS_OT_Split_Area_Pie_9,
    IOPS_OT_Call_Pie_Edit,
    IOPS_MT_Pie_Split,
    IOPS_OT_Call_Pie_Split,
    IOPS_PT_DATA_Panel,
    IOPS_OT_Call_Data_Panel,
    IOPS_OT_Easy_Mod_Curve,
    IOPS_OT_Executor,
    IOPS_PT_ExecuteList,
    IOPS_OT_Call_MT_Executor,
    IOPS_OT_Easy_Mod_Array_Caps,
    IOPS_OT_Easy_Mod_Array_Curve,
    IOPS_OT_Easy_Mod_Shwarp,
    IOPS_OT_Mesh_QuickSnap,
    IOPS_OT_LoadDefaultHotkeys,
    IOPS_OT_LoadUserHotkeys,
    IOPS_OT_SaveUserHotkeys,
    IOPS_OT_SaveAddonPreferences,
    IOPS_OT_LoadAddonPreferences,
    IOPS_OT_RenderAssetThumbnail,
    IOPS_OT_RunText,
    IOPS_OT_MayaIsolate,
    IOPS_OT_Mesh_Cursor_Bisect,
    IOPS_OT_DragSnap,
    IOPS_OT_DragSnapUV,
    IOPS_OT_DragSnapCursor,
    IOPS_OT_ActiveObject_Scroll_UP,
    IOPS_OT_ActiveObject_Scroll_DOWN,
    IOPS_OT_VertexColorAssign,
    IOPS_OT_VertexColorAlphaAssign,
    IOPS_PT_VCol_Panel,
    IOPS_OT_SplitScreenArea,
    IOPS_OT_SwitchScreenArea,
    IOPS_OT_SaveSpaceData,
    IOPS_OT_LoadSpaceData,
    IOPS_OT_MaterialsFromTextures,
    IOPS_OT_Drop_It,
    IOPS_OT_KitBash_Grid,
    IOPS_OT_Clean_UVMap_0,
    IOPS_OT_Clean_UVMap_1,
    IOPS_OT_Clean_UVMap_2,
    IOPS_OT_Clean_UVMap_3,
    IOPS_OT_Clean_UVMap_4,
    IOPS_OT_Clean_UVMap_5,
    IOPS_OT_Clean_UVMap_6,
    IOPS_OT_Clean_UVMap_7,
    IOPS_OT_Add_UVMap,
    IOPS_OT_Remove_UVMap_by_Active_Name,
    IOPS_OT_Active_UVMap_by_Active,
    IOPS_OT_Mesh_UV_Channel_Hop,
    IOPS_OT_Object_Name_From_Active,
    IOPS_MouseoverFillSelect,
    IOPS_MESH_OT_CopyEdgesLength,
    IOPS_MESH_OT_CopyEdgesAngle,
    IOPS_OT_SetSnapCombo,
    IOPS_OT_Reload_Libraries,
    IOPS_OT_Reload_Images,
    IOPS_OT_Cursor_Rotate,
    Z_OT_GrowLoop,
    Z_OT_ShrinkLoop,
    Z_OT_GrowRing,
    Z_OT_ShrinkRing,
    Z_OT_SelectBoundedLoop,
    Z_OT_SelectBoundedRing,
    Z_OT_EdgeEq,
    Z_OT_EdgeLineUp,
    Z_OT_ContextDelete,
    Z_OT_PutOn,
    Z_OT_Mirror,
    Z_OT_EdgeConnect,
    IOPS_OT_OpenAssetInCurrentBlender,
)

reg_cls, unreg_cls = bpy.utils.register_classes_factory(classes)

# def draw_iops_hud():
#     # set_drawing_dpi(get_dpi())
#     # dpi_factor = get_dpi_factor()

#     # if addon.preference().color.Hops_display_logo:
#     draw_logo_hops()
draw_handler = None


def keymap_registration():
    path = bpy.utils.script_path_user()
    user_hotkeys_file = os.path.join(path, "presets", "IOPS", "iops_hotkeys_user.py")
    fix_old_keymaps()

    if os.path.exists(user_hotkeys_file):
        with open(user_hotkeys_file) as f:
            keys_user = json.load(f)
        register_keymaps(keys_user)
    else:
        register_keymaps(keys_default)


def register():
    # Register keymaps with a delay
    # bpy.app.timers.register(keymap_registration, first_interval=1.0)
    # bpy.app.timers.register(unregister_keymaps, first_interval=1.0)
    # bpy.app.timers.register(delayed_keymap_registration, first_interval=1.5)

    reg_cls()

    bpy.types.WindowManager.IOPS_AddonProperties = bpy.props.PointerProperty(
        type=IOPS_AddonProperties
    )


    bpy.types.Scene.IOPS = bpy.props.PointerProperty(type=IOPS_SceneProperties)
    try:
        bpy.types.MESH_MT_CopyFaceSettings.append(add_copy_edge_length_item)
        bpy.types.VIEW3D_MT_edit_mesh_select_similar.append(select_interior_faces)
    except Exception:
        print(
            "MESH_MT_CopyFaceSettings not found, enable the Copy 'Attributes Menu' addon"
        )
    bpy.types.OUTLINER_MT_collection.append(outliner_collection_ops)
    bpy.types.ASSETBROWSER_MT_context_menu.append(open_asset_in_current_blender)

    # Register the draw handler if the statistics are enabled and disable the statistics if they are not
    if bpy.context.preferences.addons["InteractionOps"].preferences.iops_stat:
        global draw_handler
        draw_handler = bpy.types.SpaceView3D.draw_handler_add(
            draw_iops_statistics, tuple(), "WINDOW", "POST_PIXEL"
        )
        print("IOPS Statistics Registered!")
    else:
        print("IOPS Statistics Disabled!")

    load_iops_preferences()
    keymap_registration()

    print("IOPS Registered!")


def unregister():
    try:
        bpy.types.MESH_MT_CopyFaceSettings.remove(add_copy_edge_length_item)
        bpy.types.OUTLINER_MT_collection.remove(outliner_collection_ops)
        bpy.types.VIEW3D_MT_edit_mesh_select_similar.remove(select_interior_faces)
        bpy.types.ASSETBROWSER_MT_context_menu.remove(open_asset_in_current_blender)
    except Exception as e:
        print(e)
        pass
    unreg_cls()
    del bpy.types.Scene.IOPS
    del bpy.types.WindowManager.IOPS_AddonProperties
    unregister_keymaps()

    # Unregister the draw handler
    global draw_handler
    if draw_handler is not None:
        bpy.types.SpaceView3D.draw_handler_remove(draw_handler, "WINDOW")
    draw_handler = None

    print("IOPS Unregistered!")


def add_copy_edge_length_item(self, context):
    self.layout.operator(IOPS_MESH_OT_CopyEdgesLength.bl_idname)
    self.layout.operator(IOPS_MESH_OT_CopyEdgesAngle.bl_idname)

def open_asset_in_current_blender(self, context):
    self.layout.operator(IOPS_OT_OpenAssetInCurrentBlender.bl_idname)

def outliner_collection_ops(self, context):
    self.layout.separator()
    self.layout.operator(IOPS_OT_Collections_Include.bl_idname)
    self.layout.operator(IOPS_OT_Collections_Exclude.bl_idname)


def select_interior_faces(self, context):
    self.layout.operator("mesh.select_interior_faces")


if __name__ == "__main__":
    register()
