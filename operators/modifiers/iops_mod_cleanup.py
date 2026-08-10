import bpy

from . import iops_mod_registry

# Types outside the curated registry whose first object field is required
_REQUIRED_FALLBACK = {"HOOK", "DATA_TRANSFER", "MESH_DEFORM",
                      "SURFACE_DEFORM", "MASK"}


def is_dead(md):
    """Reason string if the modifier does nothing, else None."""
    if not md.show_viewport and not md.show_render:
        return "disabled everywhere"
    desc = iops_mod_registry.REGISTRY.get(md.type)
    requires = (desc.requires_target if desc
                else md.type in _REQUIRED_FALLBACK)
    if requires:
        fields = iops_mod_registry.object_fields(md)
        if fields and getattr(md, fields[0], None) is None:
            return "missing target"
    if desc is not None and desc.is_noop is not None:
        try:
            if desc.is_noop(md):
                return "no-op settings"
        except AttributeError:
            pass
    return None


class IOPS_OT_ModCleanup(bpy.types.Operator):
    """Remove dead modifiers across the selection: missing required
    targets, disabled in both viewport and render, or no-op settings
    (Bevel width 0, Array count 1, Subsurf levels 0, ...)"""

    bl_idname = "iops.mod_cleanup"
    bl_label = "Cleanup Modifiers"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and context.selected_objects

    def execute(self, context):
        removed = 0
        touched = set()
        for obj in context.selected_objects:
            for md in list(obj.modifiers):
                if is_dead(md):
                    obj.modifiers.remove(md)
                    removed += 1
                    touched.add(obj.name)
        self.report({"INFO"},
                    f"Removed {removed} modifier(s) on {len(touched)} object(s)")
        return {"FINISHED"}
