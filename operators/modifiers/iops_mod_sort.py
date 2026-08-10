import bpy

from . import iops_mod_registry

# Geometry-nodes "Smooth by Angle" (Blender 4.1+ auto smooth) must stay
# at the very end of the stack or shading breaks.
_SMOOTH_BY_ANGLE = "smooth by angle"
_TAIL_NODES_WEIGHT = 95


def sort_weight(md):
    if md.type == "NODES":
        ng = getattr(md, "node_group", None)
        if ng is not None and _SMOOTH_BY_ANGLE in ng.name.lower():
            return _TAIL_NODES_WEIGHT
        return 50
    desc = iops_mod_registry.REGISTRY.get(md.type)
    return desc.sort_weight if desc else 50


class IOPS_OT_ModSortStack(bpy.types.Operator):
    """Sort modifier stacks across the selection: Mirror/Array first,
    Weighted Normal / Triangulate / Smooth by Angle last"""

    bl_idname = "iops.mod_sort_stack"
    bl_label = "Sort Modifier Stacks"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and context.selected_objects

    def execute(self, context):
        changed = 0
        for obj in context.selected_objects:
            if len(obj.modifiers) < 2:
                continue
            # stable: equal weights keep their relative order
            desired = sorted(obj.modifiers,
                             key=lambda m: sort_weight(m))
            desired_names = [m.name for m in desired]
            if desired_names == [m.name for m in obj.modifiers]:
                continue
            for target_idx, name in enumerate(desired_names):
                current_idx = obj.modifiers.find(name)
                if current_idx != target_idx:
                    obj.modifiers.move(current_idx, target_idx)
            changed += 1
        self.report({"INFO"}, f"Sorted stacks on {changed} object(s)")
        return {"FINISHED"}
