bl_info = {
    "name": "iOps",
    "author": "Titus, Cyrill",
    "version": (1, 4, 1),
    "blender": (2, 80, 0),
    "location": "View3D > Toolbar and View3D",
    "description": "Interaction operators (iOps) - for workflow speedup",
    "warning": "",
    "wiki_url": "https://blenderartists.org/t/interactionops-iops/1146238",
    "tracker_url": "",
    "category": "Mesh"
    }

import bpy
from .operators.iops import IOPS
from .operators.modes import (IOPS_OT_MODE_F1,
                              IOPS_OT_MODE_F2,
                              IOPS_OT_MODE_F3,
                              IOPS_OT_MODE_F4)
from .operators.cursor_origin.curve import (IOPS_OT_CursorOrigin_Curve, 
                                           IOPS_OT_CursorOrigin_Curve_Edit)
from .operators.cursor_origin.empty import IOPS_OT_CursorOrigin_Empty
from .operators.cursor_origin.gpen import (IOPS_OT_CursorOrigin_Gpen,
                                           IOPS_OT_CursorOrigin_Gpen_Edit)
from .operators.cursor_origin.mesh import (IOPS_OT_CursorOrigin_Mesh,
                                           IOPS_OT_CursorOrigin_Mesh_Edit)
from .operators.align_object_to_face import AlignObjectToFace
from .prefs.addon_preferences import IOPS_AddonPreferences


# WarningMessage
def ShowMessageBox(text="", title="WARNING", icon="ERROR"):
    def draw(self, context):
        self.layout.label(text=text)
    bpy.context.window_manager.popup_menu(draw, title=title, icon=icon)


def register_keymaps():
    keymapItems = (bpy.context
                      .window_manager
                      .keyconfigs
                      .addon
                      .keymaps
                      .new("Window")
                      .keymap_items)

    kmi = keymapItems.new('iops.mode_f1', 'F1', 'PRESS')
    kmi.active = True
    kmi = keymapItems.new('iops.mode_f2', 'F2', 'PRESS')
    kmi.active = True
    kmi = keymapItems.new('iops.mode_f3', 'F3', 'PRESS')
    kmi.active = True
    kmi = keymapItems.new('iops.mode_f4', 'F4', 'PRESS')
    kmi.active = True
    kmi = keymapItems.new('iops.cursor_origin_mesh', 'F4', 'PRESS')
    kmi.active = True
    kmi = keymapItems.new('iops.cursor_origin_mesh_edit', 'F4', 'PRESS')
    kmi.active = True
    kmi = keymapItems.new('iops.cursor_origin_curve', 'F4', 'PRESS')
    kmi.active = True
    kmi = keymapItems.new('iops.cursor_origin_curve_edit', 'F4', 'PRESS')
    kmi.active = True
    kmi = keymapItems.new('iops.cursor_origin_empty', 'F4', 'PRESS')
    kmi.active = True
    kmi = keymapItems.new('iops.cursor_origin_gpen', 'F4', 'PRESS')
    kmi.active = True
    kmi = keymapItems.new('iops.cursor_origin_gpen_edit', 'F4', 'PRESS')
    kmi.active = True
    kmi = keymapItems.new('iops.align_object_to_face', 'F6', 'PRESS')
    kmi.active = True


def unregister_keymaps():
    allKeymaps = bpy.context.window_manager.keyconfigs.addon.keymaps
    keymap = allKeymaps.get("Window")
    if keymap:
        keymapItems = keymap.keymap_items
        toDelete = tuple(
                item for item in keymapItems if item.idname.startswith('iops.')
            )
        for item in toDelete:
            keymapItems.remove(item)

# Classes for reg and unreg
classes = (IOPS,
           IOPS_AddonPreferences,
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
           AlignObjectToFace,
           )

reg_cls, unreg_cls = bpy.utils.register_classes_factory(classes)


def register():
    reg_cls()
    register_keymaps()
    print("IOPS Registered?!")


def unregister():
    unreg_cls()
    unregister_keymaps()
    print("IOPS Unregistered!")

if __name__ == "__main__":
    register()
