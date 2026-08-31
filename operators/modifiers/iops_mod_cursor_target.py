import bpy

from . import iops_mod_registry


class IOPS_OT_ModCursorTarget(bpy.types.Operator):
    """Create an empty at the 3D cursor (location AND rotation) and
    assign it as target to the active object's active modifier.
    Alt: also fill same-type modifiers with an empty target across
    the selection"""

    bl_idname = "iops.mod_cursor_target"
    bl_label = "Cursor to Modifier Target"
    bl_options = {"REGISTER", "UNDO"}

    alt: bpy.props.BoolProperty(options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj is not None
                and obj.modifiers.active is not None
                and iops_mod_registry.object_fields(obj.modifiers.active))

    def invoke(self, context, event):
        self.alt = event.alt
        return self.execute(context)

    def execute(self, context):
        active = context.active_object
        md = active.modifiers.active
        field = iops_mod_registry.object_fields(md)[0]

        empty = bpy.data.objects.new(f"iops_target_{md.type.lower()}", None)
        empty.empty_display_type = "PLAIN_AXES"
        empty.empty_display_size = 0.5
        context.collection.objects.link(empty)
        empty.matrix_world = context.scene.cursor.matrix

        assigned = 0
        setattr(md, field, empty)
        assigned += 1
        if self.alt:
            for obj in context.selected_objects:
                for other in obj.modifiers:
                    if other is md or other.type != md.type:
                        continue
                    if getattr(other, field, None) is None:
                        setattr(other, field, empty)
                        assigned += 1
        self.report({"INFO"},
                    f"{empty.name}: assigned to {assigned} modifier(s)")
        return {"FINISHED"}
