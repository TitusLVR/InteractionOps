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
from .operators.preferences.io_theme import (
    IOPS_OT_ThemeSaveAs,
    IOPS_OT_ThemeSave,
    IOPS_OT_ThemeDelete,
    IOPS_OT_ThemeOpenFolder,
    ensure_default_presets as _ensure_default_theme_presets,
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
from .operators.instance_collection_append import (
    IOPS_OT_Instance_Collection_Append,
    IOPS_OT_Scan_Source_Collections,
    IOPS_UL_SourceCollectionsList,
    IOPS_OT_Select_All_Collections,
)
from .operators.image_reload import IOPS_OT_Reload_Images
from .operators.maya_isolate import IOPS_OT_MayaIsolate
from .operators.split_screen_area import IOPS_OT_SwitchScreenArea
from .operators.outliner_collection_ops import (
    IOPS_OT_Collections_Include,
    IOPS_OT_Collections_Exclude,
    IOPS_OT_Collections_Remove_Keep_Objects,
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

from .operators.ui_toggles import (
    IOPS_OT_HelpToggleMarker,
    IOPS_OT_HudParamsToggleMarker,
)

from .operators.object_align_to_face import IOPS_OT_AlignObjectToFace
from .operators.object_match_transform_active import IOPS_OT_MatchTransformActive
from .operators.mesh_to_grid import IOPS_OT_mesh_to_grid
from .operators.mesh_copy_edges_length import IOPS_MESH_OT_CopyEdgesLength
from .operators.mesh_copy_edges_angle import IOPS_MESH_OT_CopyEdgesAngle
from .operators.drag_snap import IOPS_OT_DragSnap
from .operators.drag_snap_uv import IOPS_OT_DragSnapUV
from .operators.uv_info import IOPS_OT_UVInfoRect
from .operators.uv_visual_cursor import IOPS_OT_VisualCursorUV
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
from .operators.object_change_scale import IOPS_OT_ChangeScale

from .operators.object_three_point_rotation import IOPS_OT_ThreePointRotation
from .operators.object_visual_origin import IOPS_OT_VisualOrigin
from .operators.mesh_quick_snap import IOPS_OT_Mesh_QuickSnap

from .operators.save_load_space_data import IOPS_OT_LoadSpaceData, IOPS_OT_SaveSpaceData

from .prefs.addon_preferences import IOPS_AddonPreferences
from .prefs.theme import classes as _theme_classes
from .prefs.addon_properties import IOPS_AddonProperties
from .prefs.addon_properties import IOPS_SceneProperties, IOPS_CollectionItem, IOPS_ExecutorScriptItem, IOPS_WidgetListItem, IOPS_RenameSettings

from .operators.assign_vertex_color import (
    IOPS_OT_VertexColorAssign,
    IOPS_OT_VertexColorAlphaAssign,
)
from .operators.object_color import (
    IOPS_OT_ObjectColor_Apply,
    IOPS_OT_ObjectColor_CopyFromActive,
    IOPS_OT_ObjectColor_ApplyRecent,
)
from .ui.iops_object_color_panel import IOPS_PT_Object_Color_Panel
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
    IOPS_PT_Collection_Append_Panel,
    IOPS_OT_Call_Collection_Append_Panel,
    IOPS_PT_VCol_Panel,
)

from .ui.iops_data_panel import IOPS_PT_DATA_Panel, IOPS_OT_Call_Data_Panel
from .ui.iops_mod_window import IOPS_OT_Modifier_Window

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
from .operators.open_asset_in_current_blender import IOPS_OT_OpenAssetInCurrentBlender
from .ui.iops_pie_edit import (
    IOPS_MT_Pie_Edit,
    IOPS_OT_Call_Pie_Edit,
    IOPS_MT_Pie_Edit_Modes,
    IOPS_OT_Set_Empty_Size,
    IOPS_OT_Set_Empty_Display,
    IOPS_OT_Copy_Empty_Size_From_Active,
    IOPS_OT_ReloadEmptyReferenceImage,
    IOPS_OT_Reload_Instance_Library,
)
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
from .operators.object_radial_array import IOPS_OT_Object_Radial_Array
from .operators.object_aligner import IOPS_OT_Object_Aligner
from .operators.easy_mod_shwarp import IOPS_OT_Easy_Mod_Shwarp
from .operators.object_name_from_active import IOPS_OT_Object_Name_From_Active, IOPS_OT_Object_Name_From_Active_Apply
from .operators.object_select_similar_name import IOPS_OT_SelectSimilarName

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
from .operators.widgets_panel import classes as _widgets_panel_classes
from .operators.render_asset_thumbnail import IOPS_OT_RenderAssetThumbnail
from .operators.run_text import IOPS_OT_RunText
from .operators.ui_prop_switch import (
    IOPS_OT_ActiveObject_Scroll_UP,
    IOPS_OT_ActiveObject_Scroll_DOWN,
)
from .operators.snap_combos import IOPS_OT_SetSnapCombo


from .utils.functions import (register_keymaps, unregister_keymaps,
                               fix_old_keymaps, merge_missing_defaults,
                               build_bindable_defaults,
                               register_ui_toggle_keymaps)

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
from .operators.mesh_quick_connect import IOPS_OT_Mesh_Quick_Connect
from .operators.mesh_to_tris_to_quad import IOPS_OT_MeshToTrisToQuads
from .operators.mesh_straight_bevel import IOPS_OT_straight_bevel
from .operators.mesh_shear import IOPS_OT_mesh_shear
# from .operators.mesh_polygon_bevel import IOPS_OT_polygon_bevel  # WIP

from .operators.mesh_visual_uv import IOPS_OT_MeshVisualUV
from .operators.mesh_uv_shortest_mark import IOPS_OT_Mesh_UV_Shortest_Mark
from .operators.open_asset_in_new_blender import IOPS_OT_OpenAssetInNewBlender
from .operators.draw_theme_preview import (IOPS_OT_DrawThemePreview,
                                            IOPS_OT_StopThemePreview)

# GPU Widget framework (persistent clickable viewport panels)
from .ui import widgets as ui_widgets
from .prefs.widget_composer import classes as _widget_composer_classes
from .operators.preferences.io_widgets import classes as _io_widgets_classes

# Concrete GPU widget definitions (widgets/edge_data.py, ...). Optional —
# the framework registers fine without it while the package lands.
try:
    from . import widgets as iops_widgets
except ModuleNotFoundError:
    iops_widgets = None
    print("IOPS: concrete widgets package not found, framework only")

# Asset Management
from .operators.assets_management import (
    IOPS_OT_AssetMoveToCatalog,
    IOPS_OT_AssetCreateCatalog,
    IOPS_OT_AssetDeleteCatalog,
    IOPS_OT_AssetDeleteEmptyCatalogs,
    IOPS_OT_AssetSearchMoveToCatalog,
    IOPS_OT_AssetSearchDeleteCatalog,
    IOPS_OT_AssetMark,
    IOPS_OT_AssetClear,
    IOPS_OT_SetAssetLibrary,
    IOPS_OT_SelectInAssetBrowser,
    IOPS_OT_ClearAssetBrowserFilter,
    IOPS_OT_RefreshAssetBrowser,
    IOPS_OT_ExpandInstanceCollection,
    IOPS_OT_Call_Pie_Assets,
    register_pool_menus,
    unregister_pool_menus,
)
from .ui.iops_pie_assets import (
    IOPS_MT_AssetMarkSub,
    IOPS_MT_CatalogBrowseActive,
    IOPS_MT_AssetDeleteCatalogsSub,
    IOPS_MT_Pie_Assets,
)

# Material Override
from .operators.material_override import (
    IOPS_MaterialOverrideSettings,
    IOPS_OT_Material_Override_Clear_Rendering_Flag,
    IOPS_OT_Material_Override_Refresh_Previews,
    IOPS_OT_Material_Override_Generate_Previews,
    IOPS_OT_Material_Override_Apply,
    IOPS_OT_Material_Override_Clear,
    IOPS_PT_Material_Override_Panel,
    IOPS_OT_Call_Material_Override_Panel,
)

bl_info = {
    "name": "iOps",
    "authors": "Titus, Cyrill, Aleksey",
    "version": (7, 7, 7),
    "blender": (5, 0, 0),
    "location": "View3D > Toolbar and View3D",
    "description": "iOPS - Boost your Blender Interactivity :p",
    "warning": "",
    "wiki_url": "https://interactionops-docs.readthedocs.io/en/latest/index.html",
    "tracker_url": "https://github.com/TitusLVR/InteractionOps/issues",
    "category": "Tools",
}


# Classes for reg and unreg
classes = (
    *_theme_classes,
    *_widget_composer_classes,  # PropertyGroups before IOPS_AddonPreferences
    IOPS_AddonPreferences,
    *_io_widgets_classes,
    IOPS_OT_DrawThemePreview,
    IOPS_OT_StopThemePreview,
    IOPS_CollectionItem,
    IOPS_ExecutorScriptItem,
    IOPS_AddonProperties,
    IOPS_WidgetListItem,
    IOPS_RenameSettings,  # PointerProperty target — must register before IOPS_SceneProperties
    IOPS_SceneProperties,
    IOPS_OT_Collections_Include,
    IOPS_OT_Collections_Exclude,
    IOPS_OT_Collections_Remove_Keep_Objects,
    IOPS_OT_Main,
    IOPS_OT_F1,
    IOPS_OT_F2,
    IOPS_OT_F3,
    IOPS_OT_F4,
    IOPS_OT_F5,
    IOPS_OT_ESC,
    IOPS_OT_HelpToggleMarker,
    IOPS_OT_HudParamsToggleMarker,
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
    IOPS_OT_ChangeScale,
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
    IOPS_PT_Collection_Append_Panel,
    IOPS_OT_Call_Collection_Append_Panel,
    IOPS_PT_TPS_Panel,
    IOPS_OT_Call_TPS_Panel,
    IOPS_MT_Pie_Menu,
    IOPS_OT_Call_Pie_Menu,
    IOPS_MT_Pie_Edit,
    IOPS_MT_Pie_Edit_Modes,
    IOPS_OT_Set_Empty_Size,
    IOPS_OT_Set_Empty_Display,
    IOPS_OT_Copy_Empty_Size_From_Active,
    IOPS_OT_ReloadEmptyReferenceImage,
    IOPS_OT_Reload_Instance_Library,
    IOPS_OT_OpenAssetInNewBlender,
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
    IOPS_OT_Object_Radial_Array,
    IOPS_OT_Object_Aligner,
    IOPS_OT_Easy_Mod_Shwarp,
    IOPS_OT_Mesh_QuickSnap,
    IOPS_OT_LoadDefaultHotkeys,
    IOPS_OT_LoadUserHotkeys,
    IOPS_OT_SaveUserHotkeys,
    IOPS_OT_SaveAddonPreferences,
    IOPS_OT_LoadAddonPreferences,
    IOPS_OT_ThemeSaveAs,
    IOPS_OT_ThemeSave,
    IOPS_OT_ThemeDelete,
    IOPS_OT_ThemeOpenFolder,
    IOPS_OT_RenderAssetThumbnail,
    IOPS_OT_RunText,
    IOPS_OT_MayaIsolate,
    IOPS_OT_Mesh_Cursor_Bisect,
    IOPS_OT_Mesh_Quick_Connect,
    IOPS_OT_DragSnap,
    IOPS_OT_DragSnapUV,
    IOPS_OT_UVInfoRect,
    IOPS_OT_VisualCursorUV,
    IOPS_OT_DragSnapCursor,
    IOPS_OT_ActiveObject_Scroll_UP,
    IOPS_OT_ActiveObject_Scroll_DOWN,
    IOPS_OT_VertexColorAssign,
    IOPS_OT_VertexColorAlphaAssign,
    IOPS_PT_VCol_Panel,
    IOPS_OT_ObjectColor_Apply,
    IOPS_OT_ObjectColor_CopyFromActive,
    IOPS_OT_ObjectColor_ApplyRecent,
    IOPS_PT_Object_Color_Panel,
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
    IOPS_OT_Object_Name_From_Active_Apply,
    IOPS_OT_SelectSimilarName,
    IOPS_MouseoverFillSelect,
    IOPS_MESH_OT_CopyEdgesLength,
    IOPS_MESH_OT_CopyEdgesAngle,
    IOPS_OT_SetSnapCombo,
    IOPS_OT_Reload_Libraries,
    IOPS_OT_Scan_Source_Collections,
    IOPS_OT_Instance_Collection_Append,
    IOPS_OT_Select_All_Collections,
    IOPS_UL_SourceCollectionsList,
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
    IOPS_OT_AssetMoveToCatalog,
    IOPS_OT_AssetCreateCatalog,
    IOPS_OT_AssetDeleteCatalog,
    IOPS_OT_AssetDeleteEmptyCatalogs,
    IOPS_OT_AssetSearchMoveToCatalog,
    IOPS_OT_AssetSearchDeleteCatalog,
    IOPS_OT_AssetMark,
    IOPS_OT_AssetClear,
    IOPS_OT_SetAssetLibrary,
    IOPS_MT_AssetMarkSub,
    IOPS_MT_CatalogBrowseActive,
    IOPS_MT_AssetDeleteCatalogsSub,
    IOPS_MT_Pie_Assets,
    IOPS_OT_SelectInAssetBrowser,
    IOPS_OT_ClearAssetBrowserFilter,
    IOPS_OT_RefreshAssetBrowser,
    IOPS_OT_ExpandInstanceCollection,
    IOPS_OT_Call_Pie_Assets,
    IOPS_OT_Modifier_Window,
    IOPS_OT_MeshToTrisToQuads,
    IOPS_OT_straight_bevel,
    IOPS_OT_mesh_shear,
    IOPS_OT_MeshVisualUV,
    IOPS_OT_Mesh_UV_Shortest_Mark,
    # IOPS_OT_polygon_bevel,  # WIP
    IOPS_MaterialOverrideSettings,
    IOPS_OT_Material_Override_Clear_Rendering_Flag,
    IOPS_OT_Material_Override_Refresh_Previews,
    IOPS_OT_Material_Override_Generate_Previews,
    IOPS_OT_Material_Override_Apply,
    IOPS_OT_Material_Override_Clear,
    IOPS_PT_Material_Override_Panel,
    IOPS_OT_Call_Material_Override_Panel,
    # GPU widget operators (iops.widget_toggle / iops.widget_interact)
    *ui_widgets.classes,
    *_widgets_panel_classes,
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
        try:
            with open(user_hotkeys_file, encoding='utf-8') as f:
                keys_user = json.load(f)
            if not isinstance(keys_user, list):
                print("IOPS: Invalid hotkeys file format, using defaults")
                keys_user = keys_default
            # Merge in any defaults the saved file predates, so operators added
            # since the user last saved become bindable (in-memory only).
            register_keymaps(merge_missing_defaults(keys_user))
        except (json.JSONDecodeError, IOError, UnicodeDecodeError, Exception) as e:
            print(f"IOPS: Error loading user hotkeys - {e}, using defaults")
            register_keymaps(build_bindable_defaults())
    else:
        register_keymaps(build_bindable_defaults())

    register_ui_toggle_keymaps()
    bpy.context.window_manager.keyconfigs.update()


def _sync_hud_from_blender_theme_if_pristine():
    """First-install convenience: if the user hasn't touched any of the
    HUD color/panel prefs (all still equal to their hardcoded defaults),
    seed them from Blender's current theme so the HUD blends with the
    rest of the UI out of the box. Skipped silently if the user has
    customised any of those prefs."""
    try:
        prefs = bpy.context.preferences.addons["InteractionOps"].preferences
        t = prefs.iops_theme
    except (KeyError, AttributeError):
        return
    watched = ("color_hud_header", "color_hud_key",
               "color_hud_active_value", "color_hud_label",
               "color_hud_label_inactive", "color_hud_stats_error",
               "panel_bg_color")
    if any(t.is_property_set(p) for p in watched):
        return
    try:
        bpy.ops.iops.theme_use_blender_hud_colors()
    except (RuntimeError, AttributeError) as e:
        print(f"IOPS: initial HUD theme sync skipped: {e}")


def register():
    reg_cls()
    register_pool_menus()
    try:
        _ensure_default_theme_presets()
    except Exception as e:
        print(f"IOPS: ensure_default_theme_presets failed: {e}")
    try:
        _sync_hud_from_blender_theme_if_pristine()
    except Exception as e:
        print(f"IOPS: HUD theme sync failed: {e}")

    bpy.types.WindowManager.IOPS_AddonProperties = bpy.props.PointerProperty(
        type=IOPS_AddonProperties
    )


    bpy.types.Scene.IOPS = bpy.props.PointerProperty(type=IOPS_SceneProperties)
    bpy.types.Scene.iops_material_override_settings = bpy.props.PointerProperty(type=IOPS_MaterialOverrideSettings)
    try:
        bpy.types.MESH_MT_CopyFaceSettings.append(add_copy_edge_length_item)
        bpy.types.VIEW3D_MT_copypopup.append(object_copy_match_dimensions)
        bpy.types.VIEW3D_MT_edit_mesh_select_similar.append(select_interior_faces)
    except Exception:
        print(
            "MESH_MT_CopyFaceSettings not found, enable the Copy 'Attributes Menu' addon"
        )
    bpy.types.OUTLINER_MT_collection.append(outliner_collection_ops)
    bpy.types.ASSETBROWSER_MT_context_menu.append(open_asset_in_current_blender)
    bpy.types.VIEW3D_MT_object_apply.append(object_apply_change_scale)
    register_select_similar_name_menu()

    # Register the draw handler if the statistics are enabled and disable the statistics if they are not
    if bpy.context.preferences.addons["InteractionOps"].preferences.iops_stat:
        global draw_handler
        from .ui.draw import safe_handler_add
        draw_handler = safe_handler_add(
            bpy.types.SpaceView3D,
            draw_iops_statistics, tuple(), "WINDOW", "POST_PIXEL",
        )
        print("IOPS Statistics Registered!")
    else:
        print("IOPS Statistics Disabled!")

    load_iops_preferences()
    keymap_registration()

    # GPU widget framework: app handlers + persisted widget state + the
    # LEFTMOUSE interact keymap entry. Must run after the operator classes
    # are registered and after load_iops_preferences().
    ui_widgets.register()
    if iops_widgets is not None and hasattr(iops_widgets, "register"):
        iops_widgets.register()
        # Composed (JSON) widgets + the prefs Widgets-tab mirror
        try:
            from .widgets import composed
            from .prefs import widget_composer
            problems = composed.load_all()
            for fn, errors in problems.items():
                print(f"IOPS widgets: {fn}: {'; '.join(errors)}")
            widget_composer.sync_from_files()
        except Exception as e:
            print(f"IOPS widgets: composed widget load failed: {e}")

    print("IOPS Registered!")


def unregister():
    # GPU widget teardown first (reverse of register): concrete widgets,
    # then the framework — saves widget state to prefs, removes ONLY its
    # own keymap entry and app/draw handlers. Guarded so a failure here
    # never blocks the rest of the addon's unregister.
    try:
        if iops_widgets is not None and hasattr(iops_widgets, "unregister"):
            iops_widgets.unregister()
        ui_widgets.unregister()
    except Exception as e:
        print("IOPS: widget system unregister failed:", e)
    # Persist the current prefs (incl. the full Theme snapshot — preset
    # name, colors, font sizes, HUD placement) before anything is torn
    # down, so manual tweaks survive addon reloads without requiring an
    # explicit Save click or a userpref.blend write.
    try:
        from .operators.preferences.io_addon_preferences import save_iops_preferences
        save_iops_preferences()
    except Exception as e:
        print("IOPS: prefs autosave on unregister failed:", e)
    # Kill any running theme-preview install before classes go away, so
    # the draw handlers + 60fps timer don't outlive the operator class.
    try:
        from .operators.draw_theme_preview import cleanup_live_installs
        cleanup_live_installs()
    except Exception as e:
        print("IOPS: theme-preview cleanup failed:", e)
    try:
        bpy.types.MESH_MT_CopyFaceSettings.remove(add_copy_edge_length_item)
        bpy.types.VIEW3D_MT_copypopup.remove(object_copy_match_dimensions)
        bpy.types.OUTLINER_MT_collection.remove(outliner_collection_ops)
        bpy.types.VIEW3D_MT_edit_mesh_select_similar.remove(select_interior_faces)
        bpy.types.ASSETBROWSER_MT_context_menu.remove(open_asset_in_current_blender)
        bpy.types.VIEW3D_MT_object_apply.remove(object_apply_change_scale)
    except Exception as e:
        print(e)
        pass
    unregister_select_similar_name_menu()
    unregister_pool_menus()
    unreg_cls()
    del bpy.types.Scene.IOPS
    del bpy.types.Scene.iops_material_override_settings
    del bpy.types.WindowManager.IOPS_AddonProperties
    unregister_keymaps()

    # Unregister the draw handler
    global draw_handler
    if draw_handler is not None:
        from .ui.draw import safe_handler_remove
        safe_handler_remove(draw_handler, bpy.types.SpaceView3D, "WINDOW")
    draw_handler = None

    print("IOPS Unregistered!")


def add_copy_edge_length_item(self, context):
    self.layout.operator(IOPS_MESH_OT_CopyEdgesLength.bl_idname)
    self.layout.operator(IOPS_MESH_OT_CopyEdgesAngle.bl_idname)

def open_asset_in_current_blender(self, context):
    self.layout.operator(IOPS_OT_OpenAssetInCurrentBlender.bl_idname)
    self.layout.separator()
    self.layout.operator(IOPS_OT_RenderAssetThumbnail.bl_idname, text="Render Asset Thumbnail")
    self.layout.operator(IOPS_OT_Call_Pie_Assets.bl_idname, text="Move Asset to Catalog")

def outliner_collection_ops(self, context):
    self.layout.separator()
    self.layout.operator(IOPS_OT_Collections_Include.bl_idname)
    self.layout.operator(IOPS_OT_Collections_Exclude.bl_idname)
    self.layout.separator()
    self.layout.operator(IOPS_OT_Collections_Remove_Keep_Objects.bl_idname, icon="TRASH")


def select_interior_faces(self, context):
    self.layout.operator("mesh.select_interior_faces")


def object_apply_change_scale(self, context):
    self.layout.separator()
    self.layout.operator(IOPS_OT_ChangeScale.bl_idname)


def object_copy_match_dimensions(self, context):
    # Appended to the Copy Attributes Menu addon's object Ctrl+C popup.
    self.layout.operator(IOPS_OT_MatchTransformActive.bl_idname,
                         text="Match Object's Dimensions")


def select_grouped_similar_name(self, context):
    self.layout.operator(IOPS_OT_SelectSimilarName.bl_idname)


def register_select_similar_name_menu():
    """Register Select Similar Name to View3D Select menu and HOPS menu if available."""
    bpy.types.VIEW3D_MT_select_object.append(select_grouped_similar_name)
    if hasattr(bpy.types, "HOPS_MT_SelectGrouped"):
        bpy.types.HOPS_MT_SelectGrouped.append(select_grouped_similar_name)


def unregister_select_similar_name_menu():
    """Unregister Select Similar Name from menus."""
    try:
        bpy.types.VIEW3D_MT_select_object.remove(select_grouped_similar_name)
    except Exception:
        pass
    if hasattr(bpy.types, "HOPS_MT_SelectGrouped"):
        try:
            bpy.types.HOPS_MT_SelectGrouped.remove(select_grouped_similar_name)
        except Exception:
            pass


if __name__ == "__main__":
    register()
