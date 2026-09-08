import bpy

from . import iops_mod_registry

# Types outside the curated registry whose first object field is required
_REQUIRED_FALLBACK = {"HOOK", "DATA_TRANSFER", "MESH_DEFORM",
                      "SURFACE_DEFORM", "MASK"}


def is_dead(md, viewport_off=False):
    """Reason string if the modifier does nothing, else None.

    viewport_off: also treat anything hidden in the viewport as dead,
    regardless of its render flag (the Alt variant of Cleanup).
    """
    if not md.show_viewport and (viewport_off or not md.show_render):
        return ("disabled in viewport" if md.show_render
                else "disabled everywhere")
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
    (Bevel width 0, Array count 1, Subsurf levels 0, ...).
    Alt: also remove every modifier disabled in the viewport"""

    bl_idname = "iops.mod_cleanup"
    bl_label = "Cleanup Modifiers"
    bl_options = {"REGISTER", "UNDO"}

    alt: bpy.props.BoolProperty(
        name="Viewport-Disabled Too",
        description="Also remove modifiers hidden in the viewport, even "
                    "if they still render",
        default=False, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def invoke(self, context, event):
        self.alt = event.alt  # Alt on the panel button
        return self.execute(context)

    def execute(self, context):
        removed = 0
        touched = set()
        for obj in context.selected_objects:
            for md in list(obj.modifiers):
                if is_dead(md, viewport_off=self.alt):
                    obj.modifiers.remove(md)
                    removed += 1
                    touched.add(obj.name)
        self.report({"INFO"},
                    f"Removed {removed} modifier(s) on {len(touched)} object(s)")
        return {"FINISHED"}
