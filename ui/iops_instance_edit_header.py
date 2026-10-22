import os
import time

import bpy

from ..operators.instance_edit_state import active_session, session_active

# Rollback buttons stat a backup file per library; cache so a redraw storm
# does not hit the disk. (timestamp, paths)
_ROLLBACK_TTL = 2.0
_rollback_cache = (float("-inf"), [])


def _rollback_paths():
    global _rollback_cache
    now = time.monotonic()
    if now - _rollback_cache[0] >= _ROLLBACK_TTL:
        from ..operators.instance_edit_linked import backup_exists_for_any_library

        _rollback_cache = (now, backup_exists_for_any_library())
    return _rollback_cache[1]


def _active_linked_instancer(context):
    obj = getattr(context, "active_object", None)
    if obj is None or obj.type != "EMPTY":
        return False
    coll = obj.instance_collection
    return coll is not None and coll.library is not None


def draw_iops_instance_edit_header(self, context):
    """Appended to VIEW3D_MT_editor_menus right after the Selection Sets row.
    The red button pair of an open session is drawn in every mode and
    regardless of the preference: it is the only way out. LOCAL session:
    Stop/Restore (they switch to Object Mode themselves); LINKED session:
    Commit/Cancel, plus the session depth when nested. The idle Edit button
    (Edit Instance, or Edit Linked on a linked instancer) shows in Object and
    Edit Mode only and follows the iops_instance_edit_header preference.
    Rollback buttons show in Object Mode with no session open."""
    layout = self.layout
    scene = context.scene
    if scene is not None and session_active(scene):
        layout.separator()
        row = layout.row(align=True)
        row.alert = True
        if active_session(scene).kind == "LINKED":
            row.operator("iops.instance_edit_commit", text="", icon="LINKED", depress=True)
            row.operator("iops.instance_edit_cancel", text="", icon="X")
        else:
            row.operator("iops.instance_edit_stop", text="", icon="OUTLINER_COLLECTION", depress=True)
            row.operator("iops.instance_edit_restore", text="", icon="RECOVER_LAST")
        depth = len(scene.iops_instance_edit.sessions)
        if depth > 1:
            layout.label(text=f"{depth}")
        return
    if context.mode not in {"OBJECT", "EDIT_MESH"}:
        return
    prefs = context.preferences.addons["InteractionOps"].preferences
    if prefs.iops_instance_edit_header:
        layout.separator()
        icon = "LINKED" if _active_linked_instancer(context) else "OUTLINER_COLLECTION"
        layout.row(align=True).operator("iops.instance_edit_start", text="", icon=icon)
    if context.mode == "OBJECT":
        for path in _rollback_paths():
            op = layout.row(align=True).operator(
                "iops.instance_edit_rollback_source",
                text="",
                icon="LOOP_BACK",
            )
            op.source_path = path
