import bpy

# Apply All / collapse the stack: bake the evaluated (viewport) geometry
# into the mesh and drop every modifier — like native Visual Geometry
# to Mesh, but across the selection. One depsgraph evaluation total
# (the viewport already has it), instead of the per-modifier
# re-evaluation avalanche of applying a heavy stack one by one.


class IOPS_OT_ModCollapseStack(bpy.types.Operator):
    """Apply All: bake the visual (evaluated) geometry into the mesh
    and remove all modifiers, for every selected mesh object"""

    bl_idname = "iops.mod_collapse_stack"
    bl_label = "Collapse Stack"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and context.selected_objects

    def execute(self, context):
        depsgraph = context.evaluated_depsgraph_get()
        collapsed = 0
        skipped = {}

        def skip(reason):
            skipped[reason] = skipped.get(reason, 0) + 1

        # Bake all evaluated meshes FIRST: swapping obj.data mid-loop
        # tags the depsgraph, and evaluated_get on a tagged graph would
        # force a fresh (and for heavy stacks, expensive) re-evaluation
        # per object.
        baked = []
        for obj in context.selected_objects:
            if obj.type != "MESH":
                skip("non-mesh")
                continue
            if not obj.modifiers:
                skip("no modifiers")
                continue
            if obj.data is not None and getattr(obj.data, "shape_keys", None):
                skip("shape keys")
                continue
            try:
                mesh = bpy.data.meshes.new_from_object(
                    obj.evaluated_get(depsgraph),
                    preserve_all_data_layers=True,
                    depsgraph=depsgraph)
            except RuntimeError as e:
                skip(str(e))
                continue
            baked.append((obj, mesh))

        for obj, mesh in baked:
            mesh.name = obj.data.name if obj.data.users == 1 else obj.name
            old = obj.data
            obj.data = mesh
            obj.modifiers.clear()
            if old is not None and old.users == 0:
                bpy.data.meshes.remove(old)
            collapsed += 1

        msg = f"Collapsed stack on {collapsed} object(s)"
        for reason, n in skipped.items():
            msg += f"; {n} skipped ({reason})"
        self.report({"INFO"} if collapsed else {"WARNING"}, msg)
        return {"FINISHED"}
