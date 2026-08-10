import bpy

from . import iops_mod_registry
from .iops_mod_select_users import find_users

# Targets whose world matrix feeds the modifier directly
_MATRIX_TARGET_TYPES = {"MIRROR", "ARRAY", "SIMPLE_DEFORM", "SCREW", "CAST"}
# Targets that deform through their own data space — can't compensate
_DATA_SPACE_TYPES = {"CURVE", "LATTICE", "MESH_DEFORM", "SURFACE_DEFORM"}


class IOPS_OT_ModSafeApplyTransform(bpy.types.Operator):
    """Apply object transform without breaking modifiers: pivots
    matrix-based targets through a compensating empty and rescales
    distance-based modifier settings (Bevel width, Solidify thickness...)"""

    bl_idname = "iops.mod_safe_apply_transform"
    bl_label = "Safe Apply Transform"
    bl_options = {"REGISTER", "UNDO"}

    location: bpy.props.BoolProperty(name="Location", default=True)
    rotation: bpy.props.BoolProperty(name="Rotation", default=True)
    scale: bpy.props.BoolProperty(name="Scale", default=True)

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and context.selected_objects

    def execute(self, context):
        applied = 0
        skipped = {}
        warnings = []
        all_objects = list(context.view_layer.objects)

        for obj in context.selected_objects:
            if obj.type == "EMPTY":
                skipped["empty (no data)"] = skipped.get("empty (no data)", 0) + 1
                continue

            # --- scenario A: who references me, and how badly ---
            matrix_refs = []   # (modifier, field) pairs to re-pivot
            blocked = False
            for user in find_users(all_objects, obj):
                for md in user.modifiers:
                    for fname in iops_mod_registry.object_fields(md):
                        if getattr(md, fname, None) is not obj:
                            continue
                        if md.type in _DATA_SPACE_TYPES:
                            blocked = True
                        elif md.type in _MATRIX_TARGET_TYPES:
                            matrix_refs.append((md, fname))
            if blocked:
                skipped["data-space deform target (Curve/Lattice)"] = \
                    skipped.get("data-space deform target (Curve/Lattice)", 0) + 1
                continue

            matrix_before = obj.matrix_world.copy()
            pivot = None
            if matrix_refs:
                pivot = bpy.data.objects.new(f"iops_pivot_{obj.name}", None)
                pivot.empty_display_type = "PLAIN_AXES"
                pivot.empty_display_size = 0.5
                context.collection.objects.link(pivot)
                pivot.matrix_world = matrix_before
                for md, fname in matrix_refs:
                    setattr(md, fname, pivot)

            # --- apply ---
            if obj.data is not None and obj.data.users > 1:
                obj.data = obj.data.copy()
            try:
                with context.temp_override(
                        active_object=obj,
                        selected_editable_objects=[obj]):
                    bpy.ops.object.transform_apply(
                        location=self.location,
                        rotation=self.rotation,
                        scale=self.scale)
            except RuntimeError as e:
                skipped[str(e)] = skipped.get(str(e), 0) + 1
                if pivot is not None:
                    for md, fname in matrix_refs:
                        setattr(md, fname, obj)
                    bpy.data.objects.remove(pivot)
                continue

            if pivot is not None:
                pivot.parent = obj
                pivot.matrix_parent_inverse = obj.matrix_world.inverted()
                pivot.matrix_world = matrix_before

            # --- scenario B: rescale distance-based settings ---
            if self.scale:
                s = matrix_before.to_scale()
                if any(abs(c - 1.0) > 1e-6 for c in s):
                    factor = (s.x + s.y + s.z) / 3.0
                    if max(s) - min(s) > 1e-4:
                        warnings.append(
                            f"{obj.name}: non-uniform scale, distance "
                            f"settings rescaled by mean {factor:.3f}")
                    for md in obj.modifiers:
                        desc = iops_mod_registry.REGISTRY.get(md.type)
                        if desc is None:
                            continue
                        for pname in desc.scale_props:
                            try:
                                value = getattr(md, pname)
                                if hasattr(value, "__len__"):
                                    setattr(md, pname,
                                            [v * c for v, c in zip(value, s)])
                                else:
                                    setattr(md, pname, value * factor)
                            except AttributeError:
                                pass
            applied += 1

        msg = f"Safe-applied transform on {applied} object(s)"
        for reason, n in skipped.items():
            msg += f"; {n} skipped ({reason})"
        level = "WARNING" if (skipped or warnings) else "INFO"
        for w in warnings:
            print("IOPS Safe Apply:", w)
        self.report({level}, msg)
        return {"FINISHED"}
