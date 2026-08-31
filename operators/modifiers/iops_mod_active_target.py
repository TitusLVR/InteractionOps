import bpy

from . import iops_mod_registry


class IOPS_OT_ModActiveTarget(bpy.types.Operator):
    """Assign the active object as target (Boolean object, Mirror
    object, Shrinkwrap target, ...) to the active modifier of every
    other selected object (overwrites their current target).
    Shift: to all their modifiers instead of just the active one.
    Alt: only fill empty target fields, never overwrite"""

    bl_idname = "iops.mod_active_target"
    bl_label = "Active Object to Modifier Target"
    bl_options = {"REGISTER", "UNDO"}

    alt: bpy.props.BoolProperty(options={"SKIP_SAVE"})
    shift: bpy.props.BoolProperty(options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return (context.active_object
                and len(context.selected_objects) > 1)

    def invoke(self, context, event):
        self.alt = event.alt
        self.shift = event.shift
        return self.execute(context)

    def execute(self, context):
        active = context.active_object
        assigned = 0
        touched = set()
        for obj in context.selected_objects:
            if obj is active:
                continue
            mods = (list(obj.modifiers) if self.shift
                    else [obj.modifiers.active])
            for md in mods:
                if md is None:
                    continue
                fields = iops_mod_registry.object_fields(md)
                if not fields:
                    continue
                if self.alt and getattr(md, fields[0], None) is not None:
                    continue
                setattr(md, fields[0], active)
                # RNA pointer polls can reject some object types
                if getattr(md, fields[0], None) == active:
                    assigned += 1
                    touched.add(obj.name)
        self.report({"INFO"},
                    f"{active.name}: assigned to {assigned} modifier(s) "
                    f"on {len(touched)} object(s)")
        return {"FINISHED"}
