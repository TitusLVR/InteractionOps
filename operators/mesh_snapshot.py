"""Mesh Snapshot: copy the selected faces of every mesh in edit mode into
new objects and park them in the ``iops_mesh_snapshot`` collection.

The source meshes are never touched -- the selected faces are copied
via a bmesh clone (so UVs, attributes, material indices and other
custom-data layers survive) and the new object is an ``Object.copy()``
of the source with the data swapped, so transform, parent and (by
default) the modifier stack come along. The user stays in edit mode
with the original selection intact. Counterpart of MACHIN3 Smart Face
in face mode.
"""
import bpy
import bmesh
from bpy.props import BoolProperty

SNAPSHOT_COLLECTION = "iops_mesh_snapshot"
SNAPSHOT_SUFFIX = "_snapshot"


def _collection_in_scene(scene, coll):
    return coll is scene.collection or coll in scene.collection.children_recursive


def get_snapshot_collection(scene):
    """Return the snapshot collection, creating it (or re-linking an
    orphaned one) under the scene root when needed."""
    coll = bpy.data.collections.get(SNAPSHOT_COLLECTION)
    if coll is None:
        coll = bpy.data.collections.new(SNAPSHOT_COLLECTION)
    if not _collection_in_scene(scene, coll):
        scene.collection.children.link(coll)
    return coll


def snapshot_mesh_from_edit(obj):
    """Build a new Mesh holding only the selected faces of ``obj``'s
    edit-mesh. Returns None when nothing is selected."""
    bm_src = bmesh.from_edit_mesh(obj.data)
    if not any(f.select for f in bm_src.faces):
        return None

    bm = bm_src.copy()
    doomed = [f for f in bm.faces if not f.select]
    if doomed:
        bmesh.ops.delete(bm, geom=doomed, context="FACES")
    # Wire edges / loose verts of the source never belonged to a face.
    loose = [v for v in bm.verts if not v.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")

    me = bpy.data.meshes.new(obj.data.name + SNAPSHOT_SUFFIX)
    bm.to_mesh(me)
    bm.free()
    for mat in obj.data.materials:
        me.materials.append(mat)
    return me


class IOPS_OT_mesh_snapshot(bpy.types.Operator):
    """Copy the selected faces into new objects inside the iops_mesh_snapshot collection"""

    bl_idname = "iops.mesh_snapshot"
    bl_label = "Mesh Snapshot"
    bl_options = {"REGISTER", "UNDO"}
    is_bindable = True

    keep_modifiers: BoolProperty(
        name="Keep Modifiers",
        description="Copy the modifier stack of the source object onto the snapshot",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        return context.mode == "EDIT_MESH"

    def execute(self, context):
        scene = context.scene
        made = []
        for obj in context.objects_in_mode_unique_data:
            if obj.type != "MESH":
                continue
            me = snapshot_mesh_from_edit(obj)
            if me is None:
                continue
            snap = obj.copy()
            snap.data = me
            snap.name = obj.name + SNAPSHOT_SUFFIX
            if not self.keep_modifiers:
                snap.modifiers.clear()
            made.append(snap)

        if not made:
            self.report({"WARNING"}, "No faces selected")
            return {"CANCELLED"}

        coll = get_snapshot_collection(scene)
        for snap in made:
            coll.objects.link(snap)
        self.report({"INFO"}, f"Snapshot: {len(made)} object(s) -> {coll.name}")
        return {"FINISHED"}
