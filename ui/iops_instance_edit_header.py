import bpy

from ..operators.instance_edit_state import session_active


def draw_iops_instance_edit_header(self, context):
    """Appended to VIEW3D_MT_editor_menus right after the Selection Sets row.
    The red Stop/Restore pair of an open session is drawn in every mode and
    regardless of the preference: it is the only way out, and Stop/Restore
    switch to Object Mode themselves. The idle Edit Instance button shows in
    Object and Edit Mode only and follows the iops_instance_edit_header
    preference."""
    layout = self.layout
    scene = context.scene
    if scene is not None and session_active(scene):
        layout.separator()
        row = layout.row(align=True)
        row.alert = True
        row.operator("iops.instance_edit_stop", text="", icon="OUTLINER_COLLECTION", depress=True)
        row.operator("iops.instance_edit_restore", text="", icon="RECOVER_LAST")
        return
    if context.mode not in {"OBJECT", "EDIT_MESH"}:
        return
    prefs = context.preferences.addons["InteractionOps"].preferences
    if prefs.iops_instance_edit_header:
        layout.separator()
        layout.row(align=True).operator("iops.instance_edit_start", text="", icon="OUTLINER_COLLECTION")
