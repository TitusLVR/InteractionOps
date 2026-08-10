import bpy

from . import iops_mod_registry, iops_mod_presets as presets


class IOPS_OT_ModStackAction(bpy.types.Operator):
    """Row action in the active object's modifier stack list"""

    bl_idname = "iops.mod_stack_action"
    bl_label = "Modifier Stack Action"
    bl_options = {"REGISTER", "UNDO"}

    index: bpy.props.IntProperty(options={"SKIP_SAVE"})
    action: bpy.props.EnumProperty(
        items=[
            ("MOVE_UP", "Move Up", "Move modifier up"),
            ("MOVE_DOWN", "Move Down", "Move modifier down"),
            ("APPLY", "Apply", "Apply this modifier"),
            ("APPLY_UP_TO", "Apply Up To Here",
             "Apply the stack through this modifier on the whole "
             "selection, in stack order"),
            ("REMOVE", "Remove", "Remove this modifier"),
            ("SAVE_PRESET", "Save As Default Preset",
             "Use this modifier's settings when adding this type "
             "from the grid"),
        ],
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        return (context.mode == "OBJECT" and context.active_object
                and context.active_object.modifiers)

    def execute(self, context):
        obj = context.active_object
        if self.index < 0 or self.index >= len(obj.modifiers):
            self.report({"WARNING"}, "Modifier index out of range")
            return {"CANCELLED"}
        md = obj.modifiers[self.index]

        if self.action == "MOVE_UP":
            obj.modifiers.move(self.index, max(0, self.index - 1))
        elif self.action == "MOVE_DOWN":
            obj.modifiers.move(self.index,
                               min(len(obj.modifiers) - 1, self.index + 1))
        elif self.action == "APPLY":
            name = md.name
            try:
                with context.temp_override(object=obj, active_object=obj,
                                           selected_editable_objects=[obj]):
                    bpy.ops.object.modifier_apply(modifier=name)
                self.report({"INFO"}, f"Applied {name}")
            except RuntimeError as e:
                self.report({"WARNING"}, f"Apply failed: {e}")
                return {"CANCELLED"}
        elif self.action == "APPLY_UP_TO":
            target = (md.type, md.name)
            applied = 0
            failed = 0
            skipped = {}
            for o in context.selected_objects:
                count, reason, fail_count = iops_mod_registry.smart_apply_object(
                    context, o, up_to=target)
                applied += count
                failed += fail_count
                if reason:
                    skipped[reason] = skipped.get(reason, 0) + 1
            msg = f"Applied {applied} modifier(s) up to {md.name}"
            if failed:
                msg += f", {failed} failed (see console)"
            for reason, n in skipped.items():
                msg += f", {n} object(s) skipped ({reason})"
            self.report({"INFO"}, msg)
        elif self.action == "REMOVE":
            obj.modifiers.remove(md)
        elif self.action == "SAVE_PRESET":
            if presets.save_default(md):
                self.report({"INFO"},
                            f"{md.type}: saved as default preset for the grid")
            else:
                self.report({"WARNING"}, "Could not write preset file")
        return {"FINISHED"}
