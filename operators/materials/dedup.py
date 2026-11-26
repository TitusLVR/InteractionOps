"""Numbered-duplicate cleanup of the iOps Materials panel.

A local `Steel.001` merges into `Steel` when both have the same
fingerprint: the editable settings of the material and its node tree
(node types, editable properties, ID pointers by name, unlinked input and
output default values, links). Cosmetic node data is ignored.
"""
import bpy

from ...utils import materials_core as core
from . import common, slots, state

# Material settings that never change how it shades.
_MAT_SKIP = {
    "name", "name_full", "use_fake_user", "use_extra_user", "tag",
    "is_runtime_data", "paint_active_slot", "preview_render_type",
    "use_preview_world", "use_nodes", "session_uid", "is_evaluated",
    "is_missing", "is_embedded_data", "is_library_indirect",
    "library_weak_reference", "asset_data", "override_library",
    "original", "users", "use_extra_recalc_data", "is_editable",
}
# Node data that is layout or display only.
_NODE_SKIP = {
    "name", "label", "location", "location_absolute", "width", "height",
    "width_hidden", "dimensions", "select", "color", "use_custom_color",
    "hide", "show_options", "show_preview", "show_texture", "parent",
    "warning_propagation", "color_tag", "bl_idname", "bl_label",
    "bl_description", "bl_icon", "bl_static_type", "bl_width_default",
    "bl_width_min", "bl_width_max", "bl_height_default", "bl_height_min",
    "bl_height_max", "type", "internal_links", "inputs", "outputs",
    "rna_type", "is_active_output",
}
_SIMPLE = {"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM"}
_COSMETIC_NODES = {"NodeFrame", "NodeReroute"}


def _id_ref(value):
    if value is None:
        return None
    lib = getattr(value, "library", None)
    return (type(value).__name__, value.name,
            lib.filepath if lib is not None else "")


def _rna_values(owner, skip):
    """(prop, frozen value) for editable simple props and ID pointers."""
    out = []
    for prop in owner.bl_rna.properties:
        pid = prop.identifier
        if pid in skip or prop.is_readonly and prop.type != "POINTER":
            continue
        try:
            value = getattr(owner, pid)
        except (AttributeError, RuntimeError):
            continue
        if prop.type in _SIMPLE:
            out.append((pid, core.freeze(value)))
        elif prop.type == "POINTER" and isinstance(value, bpy.types.ID):
            out.append((pid, _id_ref(value)))
    return tuple(out)


def _socket_value(socket):
    if not hasattr(socket, "default_value"):
        return None
    try:
        return core.freeze(socket.default_value)
    except (AttributeError, TypeError):
        return None


def _node_fingerprint(node):
    inputs = tuple(
        (s.identifier, None if s.is_linked else _socket_value(s))
        for s in node.inputs)
    outputs = tuple((s.identifier, _socket_value(s)) for s in node.outputs)
    extra = ()
    # curve / ramp nodes keep their data in nested structs
    ramp = getattr(node, "color_ramp", None)
    if ramp is not None:
        extra += (("ramp", ramp.interpolation, ramp.color_mode,
                   tuple((core.freeze(e.position), core.freeze(e.color))
                         for e in ramp.elements)),)
    mapping = getattr(node, "mapping", None)
    if mapping is not None and hasattr(mapping, "curves"):
        extra += (("curves", tuple(
            tuple(core.freeze(p.location) for p in c.points)
            for c in mapping.curves)),)
    return (node.bl_idname, _rna_values(node, _NODE_SKIP), inputs, outputs,
            extra)


def tree_fingerprint(tree):
    if tree is None:
        return None
    nodes = tuple(sorted(
        (n.name, _node_fingerprint(n)) for n in tree.nodes
        if n.bl_idname not in _COSMETIC_NODES))
    links = tuple(sorted(
        (lk.from_node.name, lk.from_socket.identifier,
         lk.to_node.name, lk.to_socket.identifier, lk.is_muted)
        for lk in tree.links
        if lk.from_node.bl_idname not in _COSMETIC_NODES
        and lk.to_node.bl_idname not in _COSMETIC_NODES))
    # links through reroutes: resolve to their real ends
    for lk in tree.links:
        if lk.to_node.bl_idname == "NodeReroute" and \
                lk.from_node.bl_idname != "NodeReroute":
            for end in _reroute_ends(lk.to_node):
                links += ((lk.from_node.name, lk.from_socket.identifier)
                          + end,)
    return nodes, tuple(sorted(links))


def _reroute_ends(reroute, depth=0):
    ends = []
    if depth > 64:
        return ends
    for lk in reroute.outputs[0].links:
        if lk.to_node.bl_idname == "NodeReroute":
            ends.extend(_reroute_ends(lk.to_node, depth + 1))
        else:
            ends.append((lk.to_node.name, lk.to_socket.identifier, False))
    return ends


def material_fingerprint(mat):
    return (_rna_values(mat, _MAT_SKIP), tree_fingerprint(mat.node_tree))


def _data_using(materials):
    """Object data whose slots (data or object level) hold any of
    `materials`."""
    wanted = {m.as_pointer() for m in materials}
    found = {}
    for obj in bpy.data.objects:
        data = obj.data
        if data is None or not hasattr(data, "materials"):
            continue
        if any(s.material is not None and s.material.as_pointer() in wanted
               for s in obj.material_slots):
            found[data.as_pointer()] = data
    return list(found.values())


def merge_duplicates(force=False, only_base=None, touched=None):
    """Merge numbered local duplicates into their originals (see the module
    docstring). Returns (plans, linked numbered materials skipped). Object
    data that used a merged duplicate is appended to `touched` (a list)."""
    local = [m for m in bpy.data.materials if m.library is None]
    linked = [m for m in bpy.data.materials if m.library is not None
              and core.is_numbered(m.name)
              and (only_base is None or core.base_name(m.name) == only_base)]
    by_name = {m.name: m for m in local}
    names = list(by_name)
    groups = core.group_by_base(names)
    wanted = {n for base, members in groups.items()
              if (only_base is None or base == only_base)
              and any(core.is_numbered(x) for x in members)
              for n in members}
    fingerprints = {n: material_fingerprint(by_name[n]) for n in wanted}
    plans = core.plan_merge(names, fingerprints, force=force,
                            only_base=only_base)
    if touched is not None:
        touched.extend(_data_using(
            [by_name[n] for p in plans for n in p.merges]))
    for plan in plans:
        original = by_name[plan.original]
        for dup_name in plan.merges:
            dup = by_name[dup_name]
            dup.user_remap(original)
            bpy.data.materials.remove(dup)
        if plan.rename:
            original.name = plan.base
    state.invalidate_sources()
    return plans, len(linked)


class IOPS_OT_MaterialsMergeDuplicates(bpy.types.Operator):
    """Merge numbered duplicates (Steel.001) into their original and relink
    their users, then collapse slots holding the same material and remove
    empty slots. Only equivalent materials merge unless Force is on; linked
    library materials are left alone. Each part can be switched off in the
    Adjust Last Operation panel"""

    bl_idname = "iops.materials_merge_duplicates"
    bl_label = "Merge Duplicates and Relink"
    bl_options = {"REGISTER", "UNDO"}

    base: bpy.props.StringProperty(
        name="Group", description="Merge only this base name (empty: all)",
        options={"SKIP_SAVE", "HIDDEN"})
    merge: bpy.props.BoolProperty(
        name="Merge Duplicates", description="Relink numbered duplicates to "
        "the original and remove them", default=True, options={"SKIP_SAVE"})
    collapse_slots: bpy.props.BoolProperty(
        name="Collapse Duplicate Slots", description="Slots holding the same "
        "material collapse into the first one; their faces move along",
        default=True, options={"SKIP_SAVE"})
    remove_empty: bpy.props.BoolProperty(
        name="Remove Empty Slots", description="Remove every empty slot; its "
        "faces move to the first remaining slot", default=True,
        options={"SKIP_SAVE"})
    force: bpy.props.BoolProperty(
        name="Force", description="Merge duplicates that differ from the "
        "original too", default=False, options={"SKIP_SAVE"})

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "merge")
        sub = layout.row()
        sub.active = self.merge
        sub.prop(self, "force")
        layout.prop(self, "collapse_slots")
        layout.prop(self, "remove_empty")

    def execute(self, context):
        touched = []
        if self.merge:
            plans, linked = merge_duplicates(self.force, self.base or None,
                                             touched)
        else:
            plans, linked = None, 0
        repeats = empties = None
        slot_skipped = {}
        if self.collapse_slots or self.remove_empty:
            # merge on: data the merge touched plus the assignment targets;
            # merge off: a plain slot cleanup of the assignment targets
            good, _skipped = common.split_compatible(
                common.target_objects(context))
            touched.extend(o.data for o in good)
            r, e, slot_skipped = slots.cleanup_many(
                touched, self.collapse_slots, self.remove_empty)
            repeats = r if self.collapse_slots else None
            empties = e if self.remove_empty else None
        state.invalidate_sources()
        self._fix_active(context, plans or [])
        common.tag_redraw(context)
        self.report({"INFO"}, core.format_merge_report(
            plans, linked, repeats, empties, slot_skipped))
        return {"FINISHED"}

    def _fix_active(self, context, plans):
        # an active material that was merged away points at its original
        st = state.get_state(context)
        if common.find_material(st.active_name, st.active_library) is None:
            for plan in plans:
                if st.active_name in plan.merges or \
                        st.active_name == plan.original:
                    st.active_name = plan.base if plan.rename else plan.original
                    st.active_library = ""
