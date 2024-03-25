import bpy


def ContextOverride():
    for window in bpy.context.window_manager.windows:
        screen = window.screen
        for area in screen.areas:
            if area.type == "TEXT_EDITOR":
                for region in area.regions:
                    if region.type == "WINDOW":
                        context_override = {
                            "window": window,
                            "screen": screen,
                            "area": area,
                            "region": region,
                            "scene": bpy.context.scene,
                            "edit_object": bpy.context.edit_object,
                            "active_object": bpy.context.active_object,
                            "selected_objects": bpy.context.selected_objects,
                        }
                        return context_override
    raise Exception("ERROR: TEXT_EDITOR not found!")


class IOPS_OT_RunText(bpy.types.Operator):
    """Run Current Script in Text Editor"""

    bl_idname = "iops.scripts_run_text"
    bl_label = "IOPS Run Text"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        context_override = ContextOverride()
        with context.temp_override(**context_override):
            bpy.ops.text.run_script()
        return {"FINISHED"}
