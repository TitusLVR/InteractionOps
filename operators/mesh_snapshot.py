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

``copy_targets`` (cage mode with modifiers kept) also clones every
object a kept modifier points at -- mirror / array / boolean / hook /
shrinkwrap targets, UV-project projectors, Object sockets of Nodes
modifiers -- recursively through the clones' own stacks, re-points the
snapshot's modifiers at the clones and links them into the same
collection next to the snapshot. Targets shared by several snapshots of
one run are cloned once.
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


def _modifier_object_slots(mod):
    """Yield ``(owner, attr)`` pairs for every Object pointer ``mod``
    holds, so callers can ``getattr``/``setattr`` them uniformly."""
    for prop in mod.bl_rna.properties:
        if (prop.type == "POINTER" and not prop.is_readonly
                and prop.fixed_type is not None
                and prop.fixed_type.identifier == "Object"):
            yield mod, prop.identifier
    if mod.type == "UV_PROJECT":
        for proj in mod.projectors:
            yield proj, "object"
    if mod.type == "NODES" and mod.node_group is not None:
        inputs = mod.properties.inputs
        for prop in inputs.bl_rna.properties:
            if prop.type != "POINTER" or prop.identifier == "rna_type":
                continue
            item = getattr(inputs, prop.identifier, None)
            if item is None:
                continue
            vprop = item.bl_rna.properties.get("value")
            if (vprop is not None and vprop.type == "POINTER"
                    and vprop.fixed_type is not None
                    and vprop.fixed_type.identifier == "Object"):
                yield item, "value"


def _clone_target(src, memo, made):
    """Deep-ish copy of a modifier target: own object, own data, no
    animation, its own modifier targets cloned in turn. ``memo`` maps
    source -> clone and is seeded with the snapshots themselves so a
    modifier pointing at another snapshotted object lands on its
    snapshot rather than on a fresh copy."""
    dup = memo.get(src)
    if dup is not None:
        return dup
    dup = src.copy()
    if dup.data is not None:
        dup.data = dup.data.copy()
    dup.name = src.name + SNAPSHOT_SUFFIX
    dup.animation_data_clear()
    memo[src] = dup
    made.append(dup)
    retarget_modifiers(dup, memo, made)
    return dup


def retarget_modifiers(obj, memo, made):
    """Point every Object slot in ``obj``'s stack at a clone (creating
    the clones on demand); new clones are appended to ``made``."""
    for mod in obj.modifiers:
        for owner, attr in _modifier_object_slots(mod):
            tgt = getattr(owner, attr)
            if tgt is None:
                continue
            setattr(owner, attr, _clone_target(tgt, memo, made))


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
    copy_targets: BoolProperty(
        name="Copy Modifier Targets",
        description="Also clone the objects the kept modifiers point at (mirror, array, boolean, hook, node inputs...), re-point the snapshot's modifiers to the clones and link them next to the snapshot",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        return context.mode == "EDIT_MESH"

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "evaluated")
        col = layout.column()
        col.active = not self.evaluated
        col.prop(self, "keep_modifiers")
        row = col.row()
        row.active = col.active and self.keep_modifiers
        row.prop(self, "copy_targets")

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
                made.append((obj, self._wrap(obj, me, baked=False)))
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
                        made.append((obj, self._wrap(obj, me, baked=True)))
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
            pairs = self._snapshot_evaluated(context)
        else:
            pairs = self._snapshot_cage(context)
        made = [snap for _, snap in pairs]

        if not made:
            self.report({"WARNING"}, "No faces selected")
            return {"CANCELLED"}

        targets = []
        if not self.evaluated and self.keep_modifiers and self.copy_targets:
            memo = dict(pairs)
            for snap in made:
                retarget_modifiers(snap, memo, targets)

        coll = get_snapshot_collection(scene)
        for ob in made + targets:
            coll.objects.link(ob)
        msg = f"Snapshot: {len(made)} object(s)"
        if targets:
            msg += f" + {len(targets)} target(s)"
        self.report({"INFO"}, msg + f" -> {coll.name}")
        return {"FINISHED"}
