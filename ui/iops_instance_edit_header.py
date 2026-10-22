import bpy

from ..operators.instance_edit_state import session_active


def draw_iops_instance_edit_header(self, context):
    """Appended to VIEW3D_MT_editor_menus right after the Selection Sets row.
    The red Stop/Restore pair of an open session is always drawn; the idle
    Edit Instance button follows the iops_instance_edit_header preference."""
    if context.mode not in {"OBJECT", "EDIT_MESH"}:
        return
    layout = self.layout
    layout.separator()
    if session_active(context.scene):
        row = layout.row(align=True)
        row.alert = True
        row.operator("iops.instance_edit_stop", text="", icon="OUTLINER_COLLECTION", depress=True)
        row.operator("iops.instance_edit_restore", text="", icon="RECOVER_LAST")
        return
    prefs = context.preferences.addons["InteractionOps"].preferences
    if prefs.iops_instance_edit_header:
        layout.row(align=True).operator("iops.instance_edit_start", text="", icon="OUTLINER_COLLECTION")
