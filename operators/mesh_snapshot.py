"""Mesh Snapshot: copy the selected faces of every mesh in edit mode into
new objects and park them in the ``iops_mesh_snapshot`` collection.

The source meshes are never touched -- the selected faces are copied
via a bmesh clone (so UVs, attributes, material indices and other
custom-data layers survive) and the new object is an ``Object.copy()``
of the source with the data swapped, so transform, parent and (by
default) the modifier stack come along. The user stays in edit mode
with the original selection intact. Counterpart of MACHIN3 Smart Face
in face mode.

``evaluated=True`` snapshots what the viewport shows instead of the
cage: the selected faces are tagged with a boolean face attribute, the
objects drop to Object Mode so the depsgraph runs the full modifier
stack, the evaluated mesh is filtered down to the faces that still
carry the tag (modifiers propagate generic attributes, so bevel /
subdiv / mirror output inherits it), and edit mode is re-entered on the
same objects. The result has no modifiers -- they are baked in.
"""
import bpy
import bmesh
from bpy.props import BoolProperty

SNAPSHOT_COLLECTION = "iops_mesh_snapshot"
SNAPSHOT_SUFFIX = "_snapshot"
TAG_ATTR = "iops_snapshot_tag"


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


def _strip_untagged(bm, keep):
    """Drop every face for which ``keep(face)`` is False plus whatever
    verts end up without a face."""
    doomed = [f for f in bm.faces if not keep(f)]
    if doomed:
        bmesh.ops.delete(bm, geom=doomed, context="FACES")
    loose = [v for v in bm.verts if not v.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")


def snapshot_mesh_from_edit(obj):
    """Build a new Mesh holding only the selected faces of ``obj``'s
    edit-mesh. Returns None when nothing is selected."""
    bm_src = bmesh.from_edit_mesh(obj.data)
    if not any(f.select for f in bm_src.faces):
        return None

    bm = bm_src.copy()
    _strip_untagged(bm, lambda f: f.select)

    me = bpy.data.meshes.new(obj.data.name + SNAPSHOT_SUFFIX)
    bm.to_mesh(me)
    bm.free()
    for mat in obj.data.materials:
        me.materials.append(mat)
    return me


def tag_selected_faces(me):
    """Object Mode: write the face selection into a boolean face
    attribute. Returns False when no face is selected (no tag written)."""
    sel = [p.select for p in me.polygons]
    if not any(sel):
        return False
    attr = me.attributes.get(TAG_ATTR)
    if attr is not None and (attr.domain != "FACE" or attr.data_type != "BOOLEAN"):
        me.attributes.remove(attr)
        attr = None
    if attr is None:
        attr = me.attributes.new(TAG_ATTR, "BOOLEAN", "FACE")
    attr.data.foreach_set("value", sel)
    me.update()
    return True


def untag_faces(me):
    attr = me.attributes.get(TAG_ATTR)
    if attr is not None:
        me.attributes.remove(attr)


def snapshot_mesh_evaluated(obj, depsgraph):
    """Object Mode, source already tagged: bake the evaluated mesh and
    keep only the tagged faces. Returns None when nothing survived."""
    obj_eval = obj.evaluated_get(depsgraph)
    me = bpy.data.meshes.new_from_object(
        obj_eval, preserve_all_data_layers=True, depsgraph=depsgraph)
    me.name = obj.data.name + SNAPSHOT_SUFFIX
    attr = me.attributes.get(TAG_ATTR)
    if attr is None or attr.domain != "FACE" or len(me.polygons) == 0:
        bpy.data.meshes.remove(me)
        return None
    tags = [bool(d.value) for d in attr.data]
    me.attributes.remove(attr)

    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    _strip_untagged(bm, lambda f: tags[f.index])
    if not bm.faces:
        bm.free()
        bpy.data.meshes.remove(me)
        return None
    bm.to_mesh(me)
    bm.free()
    return me


class IOPS_OT_mesh_snapshot(bpy.types.Operator):
    """Copy the selected faces into new objects inside the iops_mesh_snapshot collection"""

    bl_idname = "iops.mesh_snapshot"
    bl_label = "Mesh Snapshot"
    bl_options = {"REGISTER", "UNDO"}
    is_bindable = True

    evaluated: BoolProperty(
        name="Evaluated",
        description="Snapshot the evaluated result (modifiers applied) of the selected faces instead of the cage geometry",
        default=False,
    )
    keep_modifiers: BoolProperty(
        name="Keep Modifiers",
        description="Copy the modifier stack of the source object onto the snapshot",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        return context.mode == "EDIT_MESH"

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "evaluated")
        row = layout.row()
        row.active = not self.evaluated
        row.prop(self, "keep_modifiers")

    def _wrap(self, obj, me, baked):
        snap = obj.copy()
        snap.data = me
        snap.name = obj.name + SNAPSHOT_SUFFIX
        # Object.copy() shares the source action/drivers; a snapshot must
        # stay where the user puts it, not snap back to keyed transforms.
        snap.animation_data_clear()
        if baked or not self.keep_modifiers:
            snap.modifiers.clear()
        return snap

    def _snapshot_cage(self, context):
        made = []
        for obj in context.objects_in_mode_unique_data:
            if obj.type != "MESH":
                continue
            me = snapshot_mesh_from_edit(obj)
            if me is not None:
                made.append(self._wrap(obj, me, baked=False))
        return made

    def _snapshot_evaluated(self, context):
        """Round-trip through Object Mode so the depsgraph evaluates
        the full stack (edit mode skips modifiers hidden from it)."""
        edit_objs = [o for o in context.objects_in_mode if o.type == "MESH"]
        active = context.view_layer.objects.active
        bpy.ops.object.mode_set(mode="OBJECT")
        tagged = [o for o in edit_objs if tag_selected_faces(o.data)]
        made = []
        try:
            if tagged:
                depsgraph = context.evaluated_depsgraph_get()
                for obj in tagged:
                    me = snapshot_mesh_evaluated(obj, depsgraph)
                    if me is not None:
                        made.append(self._wrap(obj, me, baked=True))
        finally:
            for obj in tagged:
                untag_faces(obj.data)
            for obj in context.view_layer.objects:
                obj.select_set(obj in edit_objs)
            context.view_layer.objects.active = active
            bpy.ops.object.mode_set(mode="EDIT")
        return made

    def execute(self, context):
        scene = context.scene
        if self.evaluated:
            made = self._snapshot_evaluated(context)
        else:
            made = self._snapshot_cage(context)

        if not made:
            self.report({"WARNING"}, "No faces selected")
            return {"CANCELLED"}

        coll = get_snapshot_collection(scene)
        for snap in made:
            coll.objects.link(snap)
        self.report({"INFO"}, f"Snapshot: {len(made)} object(s) -> {coll.name}")
        return {"FINISHED"}
