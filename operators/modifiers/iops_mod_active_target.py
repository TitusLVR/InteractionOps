import bpy

from . import iops_mod_registry


class IOPS_OT_ModActiveTarget(bpy.types.Operator):
    """Assign the active object as modifier target across the selection:
    fills every empty object field (Boolean object, Mirror object,
    Shrinkwrap target, ...) on the other selected objects"""

    bl_idname = "iops.mod_active_target"
    bl_label = "Active Object to Modifier Target"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (context.active_object
                and len(context.selected_objects) > 1)

    def execute(self, context):
        active = context.active_object
        assigned = 0
        touched = set()
        for obj in context.selected_objects:
            if obj is active:
                continue
            for md in obj.modifiers:
                fields = iops_mod_registry.object_fields(md)
                if fields and getattr(md, fields[0], None) is None:
                    setattr(md, fields[0], active)
                    assigned += 1
                    touched.add(obj.name)
        self.report({"INFO"},
                    f"{active.name}: assigned to {assigned} modifier(s) "
                    f"on {len(touched)} object(s)")
        return {"FINISHED"}
