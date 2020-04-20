import bpy
import json
import os

from .operators.hotkeys.load_hotkeys import (IOPS_OT_LoadUserHotkeys, IOPS_OT_LoadDefaultHotkeys)
from .operators.hotkeys.save_hotkeys import IOPS_OT_SaveUserHotkeys
from .operators.align_origin_to_normal import IOPS_OT_AlignOriginToNormal
from .operators.cursor_origin.mesh import IOPS_OT_CursorOrigin_Mesh
from .operators.curve_spline_type import IOPS_OT_CurveSplineType
from .operators.curve_subdivide import IOPS_OT_CurveSubdivide
from .operators.grid_from_active import IOPS_OT_ToGridFromActive 
from .operators.iops import IOPS_OT_Main
from .operators.maya_isolate import IOPS_OT_MayaIsolate
from .operators.mesh_convert_selection import (IOPS_OT_ToEdges,
                                               IOPS_OT_ToFaces,
                                               IOPS_OT_ToVerts)
from .operators.modes import (IOPS_OT_ESC, IOPS_OT_F1, IOPS_OT_F2, IOPS_OT_F3,
                              IOPS_OT_F4, IOPS_OT_F5)
from .operators.object_align_to_face import IOPS_OT_AlignObjectToFace
from .operators.object_match_transform_active import IOPS_OT_MatchTransformActive
from .operators.mesh_to_grid import IOPS_OT_mesh_to_grid
from .operators.drag_snap import IOPS_OT_DragSnap
from .operators.object_normalize import IOPS_OT_object_normalize
from .operators.object_rotate import (IOPS_OT_object_rotate_MX,
                                      IOPS_OT_object_rotate_MY,
                                      IOPS_OT_object_rotate_MZ,
                                      IOPS_OT_object_rotate_X,
                                      IOPS_OT_object_rotate_Y,
                                      IOPS_OT_object_rotate_Z)
from .operators.object_three_point_rotation import IOPS_OT_ThreePointRotation
from .operators.object_visual_origin import IOPS_OT_VisualOrigin
from .prefs.addon_preferences import IOPS_AddonPreferences
from .prefs.addon_properties import IOPS_AddonProperties

from .operators.assign_vertex_color import (IOPS_OT_VertexColorAssign)
                                            

from .ui.iops_tm_panel import (IOPS_OT_edit_origin,
                               IOPS_OT_transform_orientation_create,
                               IOPS_OT_transform_orientation_cleanup,
                               IOPS_OT_transform_orientation_delete,
                               IOPS_OT_homonize_uvmaps_names,
                               IOPS_OT_uvmaps_cleanup,
                               IOPS_PT_TPS_Panel,
                               IOPS_PT_TM_Panel,
                               IOPS_OT_Call_TPS_Panel,
                               IOPS_OT_Call_TM_Panel,
                               IOPS_PT_VCol_Panel)
from .ui.iops_pie_menu import IOPS_MT_Pie_Menu, IOPS_OT_Call_Pie_Menu
from .ui.iops_pie_edit import IOPS_MT_Pie_Edit, IOPS_OT_Call_Pie_Edit
from .operators.z_ops import (Z_OT_GrowLoop,
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
                              Z_OT_EdgeConnect)

from .operators.executor import IOPS_OT_EXECUTOR
from .operators.run_text import IOPS_OT_RunText
from .operators.array_rig import (IOPS_OT_ARRIG)
from .operators.ui_prop_switch import (IOPS_OT_PropScroll_UP,
                                       IOPS_OT_PropScroll_DOWN)  

from .utils.functions import (register_keymaps, unregister_keymaps)
# Hotkeys
from .prefs.hotkeys_default import keys_default as keys_default


bl_info = {
    "name": "iOps",
    "authors": "Titus, Cyrill, Aleksey",
    "version": (2, 1, 0),
    "blender": (2, 81, 0),
    "location": "View3D > Toolbar and View3D",
    "description": "Handy functions to speed up workflow",
    "warning": "",
    "wiki_url": "https://blenderartists.org/t/interactionops-iops/",
    "tracker_url": "https://github.com/TitusLVR/InteractionOps",
    "category": "Tools"
}

# Classes for reg and unreg
classes = (IOPS_OT_Main,
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
           IOPS_OT_VisualOrigin,
           IOPS_OT_object_rotate_Z,
           IOPS_OT_object_rotate_MZ,
           IOPS_OT_object_rotate_Y,
           IOPS_OT_object_rotate_MY,
           IOPS_OT_object_rotate_X,
           IOPS_OT_object_rotate_MX,
           IOPS_OT_object_normalize,
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
           IOPS_OT_Call_Pie_Edit,
           IOPS_OT_EXECUTOR,
           IOPS_OT_ARRIG,
           IOPS_AddonPreferences,
           IOPS_AddonProperties,
           IOPS_OT_LoadDefaultHotkeys,
           IOPS_OT_LoadUserHotkeys,
           IOPS_OT_SaveUserHotkeys, 
           IOPS_OT_RunText,     
           IOPS_OT_MayaIsolate,   
           IOPS_OT_DragSnap,
           IOPS_OT_PropScroll_UP,
           IOPS_OT_PropScroll_DOWN,
           IOPS_OT_VertexColorAssign,
           IOPS_PT_VCol_Panel,  
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
           Z_OT_EdgeConnect
           )

reg_cls, unreg_cls = bpy.utils.register_classes_factory(classes)


def register():
    reg_cls()
    bpy.types.WindowManager.IOPS_AddonProperties = bpy.props.PointerProperty(type=IOPS_AddonProperties)
    path = bpy.utils.script_path_user()
    user_hotkeys_file = os.path.join(path, 'presets', 'keyconfig', "IOPS", "iops_hotkeys_user.py")
    if os.path.exists(user_hotkeys_file):
        with open(user_hotkeys_file) as f:
            keys_user = json.load(f)
        register_keymaps(keys_user)
    else:
        register_keymaps(keys_default)
    print("IOPS Registered!")


def unregister():
    unreg_cls()
    del bpy.types.WindowManager.IOPS_AddonProperties
    unregister_keymaps()
    print("IOPS Unregistered!")


if __name__ == "__main__":
    register()
