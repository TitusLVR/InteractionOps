import bpy

from . import iops_mod_registry


def find_users(objects, target):
    """Objects whose modifiers reference `target`. Registry object-field
    fast path; identity comparison; no bpy.ops."""
    users = []
    for obj in objects:
        if obj is target:
            continue
        for md in obj.modifiers:
            hit = False
            for fname in iops_mod_registry.object_fields(md):
                if getattr(md, fname, None) is target:
                    hit = True
                    break
            if hit:
                users.append(obj)
                break
    return users


class IOPS_OT_ModSelectTargetUsers(bpy.types.Operator):
    """Select every object that uses the active object as a modifier
    target (Boolean object, Mirror object, Curve, Lattice, ...) and
    make the first user the active object"""

    bl_idname = "iops.mod_select_target_users"
    bl_label = "Select Modifier Users of Active"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and context.active_object

    def execute(self, context):
        active = context.active_object
        users = find_users(context.view_layer.objects, active)
        for obj in users:
            obj.select_set(True)
        if users:
            context.view_layer.objects.active = users[0]
        self.report({"INFO"},
                    f"{active.name}: selected {len(users)} user object(s)")
        return {"FINISHED"}
