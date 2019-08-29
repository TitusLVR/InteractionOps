bl_info = {
    "name": "iOps",
    "author": "Titus, Cyrill, Aleksey",
    "version": (1, 5, 0),
    "blender": (2, 80, 0),
    "location": "View3D > Toolbar and View3D",
    "description": "Speed up workflow with faster operations",
    "warning": "",
    "wiki_url": "https://blenderartists.org/t/interactionops-iops/",
    "tracker_url": "https://github.com/TitusLVR/InteractionOps",
    "category": "Tools"
}

import bpy
from .operators.iops import IOPS_OT_Main
from .operators.modes import (IOPS_OT_MODE_F1,
                              IOPS_OT_MODE_F2,
                              IOPS_OT_MODE_F3,
                              IOPS_OT_MODE_F4)
from .operators.cursor_origin.curve import (IOPS_OT_CursorOrigin_Curve,
                                            IOPS_OT_CursorOrigin_Curve_Edit)
from .operators.cursor_origin.empty import IOPS_OT_CursorOrigin_Empty
from .operators.cursor_origin.gpen import (IOPS_OT_CursorOrigin_Gpen,
                                           IOPS_OT_CursorOrigin_Gpen_Edit)
from .operators.cursor_origin.mesh import IOPS_OT_CursorOrigin_Mesh
from .operators.cursor_origin.mesh_edit import IOPS_OT_CursorOrigin_Mesh_Edit
from .operators.object_align_to_face import IOPS_OT_AlignObjectToFace
from .operators.align_origin_to_normal import IOPS_OT_AlignOriginToNormal
from .operators.object_visual_origin import *
from .operators.object_visual_origin import IOPS_OT_VisualOrigin
from .operators.curve_subdivide import IOPS_OT_CurveSubdivide
from .operators.curve_spline_type import IOPS_OT_CurveSplineType
from .operators.mesh_convert_selection import (IOPS_OT_ToFaces,
                                               IOPS_OT_ToEdges,
                                               IOPS_OT_ToVerts)
from .operators.object_match_transform_active import IOPS_OT_MatchTransformActive
from .operators.object_rotate import (IOPS_OT_object_rotate_Z,
                                               IOPS_OT_object_rotate_MZ,
                                               IOPS_OT_object_rotate_Y,
                                               IOPS_OT_object_rotate_MY,
                                               IOPS_OT_object_rotate_X,
                                               IOPS_OT_object_rotate_MX,
                                               IOPS_OT_object_normalize,
                                               IOPS_OT_mesh_to_grid)
from .prefs.addon_preferences import IOPS_AddonPreferences
from .ui.iops_pie_menu import IOPS_MT_iops_pie_menu
from .ui.iops_tm_panel import *


# WarningMessage
def ShowMessageBox(text="", title="WARNING", icon="ERROR"):
    def draw(self, context):
        self.layout.label(text=text)
    bpy.context.window_manager.popup_menu(draw, title=title, icon=icon)

# Tool fkn tip (ops , button, state, ctrl, alt, shift)
def register_keymaps():
    keys = [
        ('iops.mode_f1',                   'F1', 'PRESS', False, False, False),
        ('iops.mode_f2',                   'F2', 'PRESS', False, False, False),
        ('iops.mode_f3',                   'F3', 'PRESS', False, False, False),
        ('iops.mode_f4',                   'F4', 'PRESS', False, False, False),
        ('iops.curve_subdivide',           'F2', 'PRESS', False, False, False),
        ('iops.curve_spline_type',         'F3', 'PRESS', False, False, False),
        ('iops.cursor_origin_mesh',        'F4', 'PRESS', False, False, False),
        ('iops.cursor_origin_mesh_edit',   'F4', 'PRESS', False, False, False),
        ('iops.cursor_origin_curve',       'F4', 'PRESS', False, False, False),
        ('iops.cursor_origin_curve_edit',  'F4', 'PRESS', False, False, False),
        ('iops.cursor_origin_empty',       'F4', 'PRESS', False, False, False),
        ('iops.cursor_origin_gpen',        'F4', 'PRESS', False, False, False),
        ('iops.cursor_origin_gpen_edit',   'F4', 'PRESS', False, False, False),
        ('iops.align_object_to_face',      'F5', 'PRESS', False, False, False),
        ('iops.align_origin_to_normal',    'F5', 'PRESS', False, True,  False),
        ('iops.to_verts',                  'F1', 'PRESS', False, True,  False),
        ('iops.to_edges',                  'F2', 'PRESS', False, True,  False),
        ('iops.to_faces',                  'F3', 'PRESS', False, True,  False),
        ('iops.object_rotate_z',  'RIGHT_ARROW', 'PRESS', False, False, False),
        ('iops.object_rotate_mz', 'RIGHT_ARROW', 'PRESS', False,  False, True),
        ('iops.object_rotate_y',   'DOWN_ARROW', 'PRESS', False, False, False),
        ('iops.object_rotate_my',  'DOWN_ARROW', 'PRESS', False,  False, True),
        ('iops.object_rotate_x',   'LEFT_ARROW', 'PRESS', False, False, False),
        ('iops.object_rotate_mx',  'LEFT_ARROW', 'PRESS', False,  False, True),
        ('iops.object_normalize',   'UP_ARROW', 'PRESS', False,  False, False),
        ('iops.mesh_to_grid',   'UP_ARROW', 'PRESS', False,  False, False),
        #('bpy.ops.wm.call_menu_pie(name="IOPS_MT_iops_pie_menu")',                  'F1', 'PRESS', True, False,  False), 
               
    ]

    keyconfigs = bpy.context.window_manager.keyconfigs
    keymapItems = (bpy.context.window_manager.keyconfigs.addon.keymaps.new("Window").keymap_items)
    for k in keys:
        found = False
        for kc in keyconfigs:
            keymap = kc.keymaps.get("Window")
            if keymap:
                kmi = keymap.keymap_items
                for item in kmi:
                    if item.idname.startswith('iops.') and item.idname == str(k[0]):
                        found = True
                    else:
                        found = False
        if not found:
            kmi = keymapItems.new(k[0], k[1], k[2], ctrl=k[3], alt=k[4], shift=k[5])
            kmi.active = True


def unregister_keymaps():
    keyconfigs = bpy.context.window_manager.keyconfigs
    for kc in keyconfigs:
        keymap = kc.keymaps.get("Window")
        if keymap:
            keymapItems = keymap.keymap_items
            toDelete = tuple(
                item for item in keymapItems if item.idname.startswith('iops.'))
            for item in toDelete:
                keymapItems.remove(item)

# Classes for reg and unreg
classes = (IOPS_AddonPreferences,
           IOPS_OT_Main,           
           IOPS_OT_MODE_F1,
           IOPS_OT_MODE_F2,
           IOPS_OT_MODE_F3,
           IOPS_OT_MODE_F4,
           IOPS_OT_CursorOrigin_Curve,
           IOPS_OT_CursorOrigin_Curve_Edit,
           IOPS_OT_CursorOrigin_Empty,
           IOPS_OT_CursorOrigin_Gpen,
           IOPS_OT_CursorOrigin_Gpen_Edit,
           IOPS_OT_CursorOrigin_Mesh,
           IOPS_OT_CursorOrigin_Mesh_Edit,
           IOPS_OT_CurveSubdivide,
           IOPS_OT_CurveSplineType,
           IOPS_OT_ToFaces,
           IOPS_OT_ToEdges,
           IOPS_OT_ToVerts,
           IOPS_OT_AlignObjectToFace,
           IOPS_OT_AlignOriginToNormal,
           IOPS_OT_VisualOrigin,
           IOPS_OT_MatchTransformActive,
           IOPS_OT_object_rotate_Z,
           IOPS_OT_object_rotate_MZ,
           IOPS_OT_object_rotate_Y,
           IOPS_OT_object_rotate_MY,
           IOPS_OT_object_rotate_X,
           IOPS_OT_object_rotate_MX,
           IOPS_OT_object_normalize,
           IOPS_MT_iops_pie_menu,
           IOPS_OT_transform_orientation_create,
           IOPS_OT_transform_orientation_delete,
           IOPS_OT_transform_orientation_cleanup,           
           IOPS_OT_pivot_point_bbox,
           IOPS_OT_pivot_point_cursor,
           IOPS_OT_pivot_point_individual_origins,
           IOPS_OT_pivot_point_median_point,
           IOPS_OT_pivot_point_active_element,
           IOPS_OT_snap_target_closest,
           IOPS_OT_snap_target_center,
           IOPS_OT_snap_target_median,
           IOPS_OT_snap_target_active,
           IOPS_PT_iops_transform_panel,
           IOPS_PT_iops_tm_panel,            
           IOPS_OT_mesh_to_grid         
           )

reg_cls, unreg_cls = bpy.utils.register_classes_factory(classes)


def register():
    reg_cls()
    register_keymaps()    
    print("IOPS Registered!")


def unregister():    
    unreg_cls()
    unregister_keymaps()
  
    print("IOPS Unregistered!")


if __name__ == "__main__":
    register()
