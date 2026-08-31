import bpy

from . import iops_mod_registry


class IOPS_OT_ModCursorTarget(bpy.types.Operator):
    """Create an empty at the 3D cursor (location AND rotation) and
    assign it as target to the active object's active modifier.
    Shift: to every modifier on the active object instead.
    Alt: also fill same-type modifiers with an empty target across
    the selection"""

    bl_idname = "iops.mod_cursor_target"
    bl_label = "Cursor to Modifier Target"
    bl_options = {"REGISTER", "UNDO"}

    alt: bpy.props.BoolProperty(options={"SKIP_SAVE"})
    shift: bpy.props.BoolProperty(options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj is not None
                and any(iops_mod_registry.object_fields(md)
                        for md in obj.modifiers))

    def invoke(self, context, event):
        self.alt = event.alt
        self.shift = event.shift
        return self.execute(context)

    def execute(self, context):
        active = context.active_object
        if self.shift:
            targets = [md for md in active.modifiers
                       if iops_mod_registry.object_fields(md)]
        else:
            md = active.modifiers.active
            if md is None or not iops_mod_registry.object_fields(md):
                self.report({"WARNING"},
                            "Active modifier has no object target field")
                return {"CANCELLED"}
            targets = [md]

        name = "all" if self.shift else targets[0].type.lower()
        empty = bpy.data.objects.new(f"iops_target_{name}", None)
        empty.empty_display_type = "PLAIN_AXES"
        empty.empty_display_size = 0.5
        context.collection.objects.link(empty)
        empty.matrix_world = context.scene.cursor.matrix

        assigned = 0
        for md in targets:
            field = iops_mod_registry.object_fields(md)[0]
            setattr(md, field, empty)
            # RNA pointer polls can reject an empty (e.g. Boolean object)
            if getattr(md, field, None) == empty:
                assigned += 1
        if self.alt:
            types = {md.type for md in targets}
            for obj in context.selected_objects:
                for other in obj.modifiers:
                    if other in targets or other.type not in types:
                        continue
                    field = iops_mod_registry.object_fields(other)[0]
                    if getattr(other, field, None) is None:
                        setattr(other, field, empty)
                        if getattr(other, field, None) == empty:
                            assigned += 1
        self.report({"INFO"},
                    f"{empty.name}: assigned to {assigned} modifier(s)")
        return {"FINISHED"}
