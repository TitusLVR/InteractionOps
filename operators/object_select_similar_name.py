import bpy
import re


class IOPS_OT_SelectSimilarName(bpy.types.Operator):
    """Select objects with similar base names (ignoring .001, .002 suffixes)"""

    bl_idname = "iops.object_select_similar_name"
    bl_label = "Select Similar Name"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def get_base_name(self, name):
        """Strip numeric suffix like .001, .088 from object name."""
        # Match .XXX where X is a digit at the end of the name
        match = re.match(r'^(.+?)(\.\d+)?$', name)
        if match:
            return match.group(1)
        return name

    def execute(self, context):
        active = context.active_object
        if not active:
            self.report({'WARNING'}, "No active object")
            return {'CANCELLED'}

        base_name = self.get_base_name(active.name)

        # Find and select all objects with same base name
        count = 0
        for obj in bpy.data.objects:
            if obj.visible_get():  # Only select visible objects
                obj_base = self.get_base_name(obj.name)
                if obj_base == base_name:
                    obj.select_set(True)
                    count += 1

        self.report({'INFO'}, f"Selected {count} objects with base name '{base_name}'")
        return {'FINISHED'}
