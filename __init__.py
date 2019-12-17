
import bpy

from .operators.align_origin_to_normal import IOPS_OT_AlignOriginToNormal
from .operators.cursor_origin.mesh import IOPS_OT_CursorOrigin_Mesh
from .operators.curve_spline_type import IOPS_OT_CurveSplineType
from .operators.curve_subdivide import IOPS_OT_CurveSubdivide
from .operators.iops import IOPS_OT_Main
from .operators.mesh_convert_selection import (IOPS_OT_ToEdges,
                                               IOPS_OT_ToFaces,
                                               IOPS_OT_ToVerts)
from .operators.modes import (IOPS_OT_ESC, IOPS_OT_F1, IOPS_OT_F2, IOPS_OT_F3,
                              IOPS_OT_F4, IOPS_OT_F5)
from .operators.object_align_to_face import IOPS_OT_AlignObjectToFace
from .operators.object_match_transform_active import IOPS_OT_MatchTransformActive
from .operators.object_rotate import (IOPS_OT_mesh_to_grid,
                                      IOPS_OT_object_normalize,
                                      IOPS_OT_object_rotate_MX,
                                      IOPS_OT_object_rotate_MY,
                                      IOPS_OT_object_rotate_MZ,
                                      IOPS_OT_object_rotate_X,
                                      IOPS_OT_object_rotate_Y,
                                      IOPS_OT_object_rotate_Z)
from .operators.object_three_point_rotation import IOPS_OT_ThreePointRotation
from .operators.object_visual_origin import *
from .operators.object_visual_origin import IOPS_OT_VisualOrigin
from .prefs.addon_preferences import IOPS_AddonPreferences
from .ui.iops_pie_menu import IOPS_MT_iops_pie_menu
from .ui.iops_tm_panel import IOPS_OT_edit_origin
from .ui.iops_tm_panel import IOPS_OT_transform_orientation_create
from .ui.iops_tm_panel import IOPS_OT_transform_orientation_cleanup
from .ui.iops_tm_panel import IOPS_OT_transform_orientation_delete
from .ui.iops_tm_panel import IOPS_OT_uvmaps_cleanup
from .ui.iops_tm_panel import IOPS_PT_iops_tm_panel
from .ui.iops_tm_panel import IOPS_PT_iops_transform_panel


bl_info = {
    "name": "iOps",
    "authors": "Titus, Cyrill, Aleksey",
    "version": (1, 5, 0),
    "blender": (2, 81, 0),
    "location": "View3D > Toolbar and View3D",
    "description": "Handy functions to speed up workflow",
    "warning": "",
    "wiki_url": "https://blenderartists.org/t/interactionops-iops/",
    "tracker_url": "https://github.com/TitusLVR/InteractionOps",
    "category": "Tools"
}


# WarningMessage
def ShowMessageBox(text="", title="WARNING", icon="ERROR"):
    def draw(self, context):
        self.layout.label(text=text)
    bpy.context.window_manager.popup_menu(draw, title=title, icon=icon)


def register_keymaps():
    keys = [
        ('iops.f1',                         'F1',           'PRESS', False, False, False),
        ('iops.f2',                         'F2',           'PRESS', False, False, False),
        ('iops.f3',                         'F3',           'PRESS', False, False, False),
        ('iops.f4',                         'F4',           'PRESS', False, False, False),
        ('iops.f5',                         'F5',           'PRESS', False, False, False),
        ('iops.esc',                        'ESC',          'PRESS', False, False, False),
        ('iops.to_verts',                   'F1',           'PRESS', False, True, False),
        ('iops.to_edges',                   'F2',           'PRESS', False, True, False),
        ('iops.to_faces',                   'F3',           'PRESS', False, True, False),
        ('iops.object_rotate_z',            'RIGHT_ARROW',  'PRESS', False, False, False),
        ('iops.object_rotate_mz',           'RIGHT_ARROW',  'PRESS', False, False, True),
        ('iops.object_rotate_y',            'DOWN_ARROW',   'PRESS', False, False, False),
        ('iops.object_rotate_my',           'DOWN_ARROW',   'PRESS', False, False, True),
        ('iops.object_rotate_x',            'LEFT_ARROW',   'PRESS', False, False, False),
        ('iops.object_rotate_mx',           'LEFT_ARROW',   'PRESS', False, False, True),
        ('iops.object_normalize',           'UP_ARROW',     'PRESS', False, False, False),
        ('iops.mesh_to_grid',               'UP_ARROW',     'PRESS', False, False, False),
        ('iops.modal_three_point_rotation', 'R',            'PRESS', True, True, True),
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
           IOPS_MT_iops_pie_menu,
           IOPS_OT_transform_orientation_create,
           IOPS_OT_transform_orientation_delete,
           IOPS_OT_transform_orientation_cleanup,
           IOPS_OT_uvmaps_cleanup,
           IOPS_PT_iops_transform_panel,
           IOPS_PT_iops_tm_panel,
           IOPS_OT_edit_origin,
           IOPS_OT_mesh_to_grid,
           IOPS_OT_ThreePointRotation,
           IOPS_OT_AlignOriginToNormal,
           IOPS_OT_MatchTransformActive,
           IOPS_AddonPreferences
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
