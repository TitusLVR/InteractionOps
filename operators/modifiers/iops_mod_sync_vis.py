import bpy


class IOPS_OT_ModSyncVis(bpy.types.Operator):
    """Set every modifier's render visibility to match its viewport
    visibility, across the selection"""

    bl_idname = "iops.mod_sync_vis"
    bl_label = "Sync Render Visibility"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and context.selected_objects

    def execute(self, context):
        synced = 0
        for obj in context.selected_objects:
            for md in obj.modifiers:
                if md.show_render != md.show_viewport:
                    md.show_render = md.show_viewport
                    synced += 1
        self.report({"INFO"}, f"Synced {synced} modifier(s)")
        return {"FINISHED"}
