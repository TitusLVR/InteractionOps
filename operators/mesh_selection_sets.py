import bpy
import bmesh

from ..utils.selection_sets_core import (
    DOMAINS,
    make_attr_name,
    parse_attr_name,
    sanitize_set_name,
    unique_name,
    group_sets,
    merge_membership,
    diff_membership,
)


class IOPS_SS_ObjectRef(bpy.types.PropertyGroup):
    """One object reference inside a scene selection set (name only)."""
    pass


class IOPS_SS_SceneSet(bpy.types.PropertyGroup):
    objects: bpy.props.CollectionProperty(type=IOPS_SS_ObjectRef)


def scene_get(scene, name):
    return scene.iops_selection_sets.get(name)


def scene_list_sets(scene):
    """{name: (alive, total)} — alive counts refs still present in the
    scene; dead refs are kept (the user decides to re-save or delete)."""
    out = {}
    for item in scene.iops_selection_sets:
        total = len(item.objects)
        alive = sum(1 for ref in item.objects if ref.name in scene.objects)
        out[item.name] = (alive, total)
    return out


def scene_write_membership(scene, name, obj_names):
    item = scene_get(scene, name)
    if item is None:
        item = scene.iops_selection_sets.add()
        item.name = name
    item.objects.clear()
    for obj_name in sorted(obj_names):
        ref = item.objects.add()
        ref.name = obj_name


def scene_save_set(scene, name, objects):
    scene_write_membership(scene, name, [o.name for o in objects])


def scene_membership(scene, name):
    item = scene_get(scene, name)
    if item is None:
        return set()
    return {ref.name for ref in item.objects}


def scene_delete_set(scene, name):
    idx = scene.iops_selection_sets.find(name)
    if idx >= 0:
        scene.iops_selection_sets.remove(idx)


def scene_rename_set(scene, old, new):
    item = scene_get(scene, old)
    if item is not None:
        item.name = new


# Wired to the UI mirror's dirty-tag by ui/iops_selection_sets_panel.py at
# register time; a no-op until then so the backend has no UI dependency.
def _tag_mirror_dirty():
    pass


# Wired by the UI module to rebuild_mirror(context, force=True); no-op
# until then. Lets operators refresh the mirror synchronously when they
# need to re-point the active row right after a change (e.g. New Set).
def _rebuild_mirror_now(context):
    pass


# Wired by the UI module — keeps the preview overlay tracking a set
# through a rename.
def _preview_renamed(old, new):
    pass


def _set_active_mirror_row(context, name):
    """Make `name` the active UIList row so the header shows the last
    recalled set. The mirror lives on WindowManager (wired by the UI
    module); a bare hasattr guard keeps this backend UI-independent."""
    wm = context.window_manager
    if not hasattr(wm, "iops_ss_mirror"):
        return
    idx = wm.iops_ss_mirror.find(name)
    if idx >= 0:
        wm.iops_ss_index = idx


# ----------------------------------------------------------------------
# bmesh backend (Edit Mode)
# ----------------------------------------------------------------------
def _dom_seq(bm, domain):
    return {"V": bm.verts, "E": bm.edges, "F": bm.faces}[domain]


def _dom_layers(bm, domain):
    return _dom_seq(bm, domain).layers.int


def bm_list_sets(bm):
    names = []
    for d in DOMAINS:
        names.extend(_dom_layers(bm, d).keys())
    return group_sets(names)


def bm_save_set(bm, name, mode):
    """Write current selection into set `name` on the domains enabled in
    `mode` (tool_settings.mesh_select_mode triple)."""
    for d, on in zip(DOMAINS, mode):
        if not on:
            continue
        layers = _dom_layers(bm, d)
        attr = make_attr_name(d, name)
        layer = layers.get(attr)
        if layer is None:
            layer = layers.new(attr)
        for e in _dom_seq(bm, d):
            e[layer] = 1 if e.select else 0


def bm_delete_set(bm, name):
    for d in DOMAINS:
        layers = _dom_layers(bm, d)
        layer = layers.get(make_attr_name(d, name))
        if layer is not None:
            layers.remove(layer)


def bm_delete_all(bm):
    count = 0
    for d in DOMAINS:
        layers = _dom_layers(bm, d)
        for key in list(layers.keys()):
            if parse_attr_name(key) is not None:
                layers.remove(layers[key])
                count += 1
    return count


def bm_rename_set(bm, old, new):
    """bmesh layers can't be renamed in place: new + copy_from + remove.
    layers.new() may invalidate existing layer references — re-fetch."""
    for d in DOMAINS:
        layers = _dom_layers(bm, d)
        if layers.get(make_attr_name(d, old)) is None:
            continue
        layers.new(make_attr_name(d, new))
        src = layers.get(make_attr_name(d, old))
        dst = layers.get(make_attr_name(d, new))
        dst.copy_from(src)
        layers.remove(src)


def bm_set_membership(bm, name):
    """{domain: set(element indices)} for the set's stored domains."""
    out = {}
    for d in DOMAINS:
        layer = _dom_layers(bm, d).get(make_attr_name(d, name))
        if layer is None:
            continue
        seq = _dom_seq(bm, d)
        seq.index_update()
        out[d] = {e.index for e in seq if e[layer]}
    return out


def bm_write_membership(bm, name, membership):
    """Create/overwrite set `name` from {domain: set(indices)}."""
    bm_delete_set(bm, name)
    for d, indices in membership.items():
        layer = _dom_layers(bm, d).new(make_attr_name(d, name))
        seq = _dom_seq(bm, d)
        seq.index_update()
        for e in seq:
            e[layer] = 1 if e.index in indices else 0


def bm_set_count(bm, name):
    total = 0
    for d in DOMAINS:
        layer = _dom_layers(bm, d).get(make_attr_name(d, name))
        if layer is not None:
            total += sum(1 for e in _dom_seq(bm, d) if e[layer])
    return total


def _expanded_membership(bm, name):
    """{domain: set(indices)} with downward expansion — a member face
    implies its edges and verts, a member edge its verts — so booleans
    against a selection in another domain behave intuitively."""
    member = bm_set_membership(bm, name)
    verts = set(member.get("V", ()))
    edges = set(member.get("E", ()))
    faces = set(member.get("F", ()))
    if faces:
        bm.faces.ensure_lookup_table()
        for i in faces:
            f = bm.faces[i]
            edges.update(e.index for e in f.edges)
            verts.update(v.index for v in f.verts)
    if edges:
        bm.edges.ensure_lookup_table()
        for i in edges:
            e = bm.edges[i]
            verts.update(v.index for v in e.verts)
    return {"V": verts, "E": edges, "F": faces}


def _bm_current_selection(bm):
    out = {}
    for d in DOMAINS:
        seq = _dom_seq(bm, d)
        seq.index_update()
        out[d] = {e.index for e in seq if e.select}
    return out


def _bm_set_exact_selection(bm, result):
    """Make the selection exactly `result` ({domain: indices}).

    bmesh select assignment flushes downward (a face drags its verts and
    edges), and blanket select_flush(True) over-selects — any face whose
    verts happen to end up all-selected lights up. So: clear everything,
    select exactly the result, and let the per-element downward flush plus
    one select_flush_mode() settle mode consistency. Hidden elements are
    never selected."""
    for d in reversed(DOMAINS):     # faces first: their flush-down is moot
        for e in _dom_seq(bm, d):
            e.select = False
    for d in DOMAINS:               # verts first: faces re-flush downward
        keep = result.get(d, ())
        for e in _dom_seq(bm, d):
            if e.index in keep and not e.hide:
                e.select = True
    bm.select_flush_mode()


def bm_apply_selection(bm, name, action):
    """Boolean of the current selection with the set, per domain:
    SET = set, EXTEND = union, SUBTRACT = difference."""
    allowed = _expanded_membership(bm, name)
    if action == "SET":
        result = allowed
    else:
        current = _bm_current_selection(bm)
        op = (set.union if action == "EXTEND" else set.difference)
        result = {d: op(current[d], allowed[d]) for d in DOMAINS}
    _bm_set_exact_selection(bm, result)


def bm_intersect_selection(bm, name):
    """Keep selected only what is both selected and in the set."""
    allowed = _expanded_membership(bm, name)
    current = _bm_current_selection(bm)
    _bm_set_exact_selection(
        bm, {d: current[d] & allowed[d] for d in DOMAINS})


def edit_meshes(context):
    """(object, bmesh) for every unique mesh in edit mode."""
    for obj in context.objects_in_mode_unique_data:
        if obj.type == "MESH":
            yield obj, bmesh.from_edit_mesh(obj.data)


def all_edit_set_names(context):
    names = set()
    for _obj, bm in edit_meshes(context):
        names.update(bm_list_sets(bm).keys())
    return sorted(names)


def _flags_for(context, set_name):
    """Union of the set's flags across all meshes in edit."""
    flags = set()
    for _obj, bm in edit_meshes(context):
        flags.update(bm_list_sets(bm).get(set_name, ""))
    return "".join(d for d in DOMAINS if d in flags)


def _update_edit_meshes(context):
    for obj, _bm in edit_meshes(context):
        bmesh.update_edit_mesh(obj.data, loop_triangles=False,
                               destructive=False)


def _have_edit_selection(context):
    return any(
        obj.data.total_vert_sel or obj.data.total_edge_sel
        or obj.data.total_face_sel
        for obj, _bm in edit_meshes(context)
    )


# ----------------------------------------------------------------------
# Operators
# ----------------------------------------------------------------------
class IOPS_OT_SSNew(bpy.types.Operator):
    """Save the current selection as a new selection set"""
    bl_idname = "iops.ss_new"
    bl_label = "New Selection Set"
    bl_options = {"REGISTER", "UNDO"}

    set_name: bpy.props.StringProperty(name="Name", default="Set")

    @classmethod
    def poll(cls, context):
        if context.mode == "EDIT_MESH":
            return _have_edit_selection(context)
        return context.mode == "OBJECT" and bool(context.selected_objects)

    def execute(self, context):
        if context.mode == "OBJECT":
            scene = context.scene
            name = unique_name(sanitize_set_name(self.set_name),
                               [s.name for s in scene.iops_selection_sets])
            scene_save_set(scene, name, context.selected_objects)
            _tag_mirror_dirty()
            _rebuild_mirror_now(context)
            _set_active_mirror_row(context, name)
            return {"FINISHED"}
        name = unique_name(sanitize_set_name(self.set_name),
                           all_edit_set_names(context))
        mode = context.tool_settings.mesh_select_mode[:]
        for obj, bm in edit_meshes(context):
            me = obj.data
            if me.total_vert_sel or me.total_edge_sel or me.total_face_sel:
                bm_save_set(bm, name, mode)
        _update_edit_meshes(context)
        _tag_mirror_dirty()
        _rebuild_mirror_now(context)
        _set_active_mirror_row(context, name)
        return {"FINISHED"}


class IOPS_OT_SSRecall(bpy.types.Operator):
    """Select the set's elements"""
    bl_idname = "iops.ss_recall"
    bl_label = "Select Set"
    bl_options = {"REGISTER", "UNDO"}

    set_name: bpy.props.StringProperty(name="Set")
    action: bpy.props.EnumProperty(items=[
        ("SET", "Set", "Replace selection"),
        ("EXTEND", "Extend", "Add to selection"),
        ("SUBTRACT", "Subtract", "Remove from selection"),
        ("INTERSECT", "Intersect",
         "Keep only what is both selected and in the set"),
    ], default="SET")

    @classmethod
    def poll(cls, context):
        return context.mode in {"EDIT_MESH", "OBJECT"}

    def execute(self, context):
        if context.mode == "OBJECT":
            scene = context.scene
            if scene_get(scene, self.set_name) is None:
                self.report({"WARNING"}, f"Set '{self.set_name}' not found")
                return {"CANCELLED"}
            member = scene_membership(scene, self.set_name)
            if self.action == "INTERSECT":
                for obj in context.selected_objects:
                    if obj.name not in member:
                        obj.select_set(False)
                _set_active_mirror_row(context, self.set_name)
                return {"FINISHED"}
            if self.action == "SET":
                for obj in context.selected_objects:
                    obj.select_set(False)
            select = self.action != "SUBTRACT"
            last = None
            for obj_name in sorted(member):
                obj = scene.objects.get(obj_name)
                if obj is not None and not obj.hide_get():
                    obj.select_set(select)
                    if select:
                        last = obj
            if last is not None and self.action == "SET":
                context.view_layer.objects.active = last
            _set_active_mirror_row(context, self.set_name)
            return {"FINISHED"}
        flags = _flags_for(context, self.set_name)
        if not flags:
            self.report({"WARNING"}, f"Set '{self.set_name}' not found")
            return {"CANCELLED"}
        if self.action == "SET":
            bpy.ops.mesh.select_all(action="DESELECT")
            context.tool_settings.mesh_select_mode = tuple(
                d in flags for d in DOMAINS)
        for _obj, bm in edit_meshes(context):
            if self.action == "INTERSECT":
                bm_intersect_selection(bm, self.set_name)
            else:
                bm_apply_selection(bm, self.set_name, self.action)
            active = bm.select_history.active
            if active is not None and not active.select:
                bm.select_history.remove(active)
        _update_edit_meshes(context)
        _set_active_mirror_row(context, self.set_name)
        return {"FINISHED"}


class IOPS_OT_SSReplace(bpy.types.Operator):
    """Overwrite the set with the current selection"""
    bl_idname = "iops.ss_replace"
    bl_label = "Replace Selection Set"
    bl_options = {"REGISTER", "UNDO"}

    set_name: bpy.props.StringProperty(name="Set")

    @classmethod
    def poll(cls, context):
        if context.mode == "EDIT_MESH":
            return _have_edit_selection(context)
        return context.mode == "OBJECT" and bool(context.selected_objects)

    def execute(self, context):
        if context.mode == "OBJECT":
            scene_save_set(context.scene, self.set_name, context.selected_objects)
            _tag_mirror_dirty()
            return {"FINISHED"}
        mode = context.tool_settings.mesh_select_mode[:]
        for _obj, bm in edit_meshes(context):
            bm_delete_set(bm, self.set_name)
            bm_save_set(bm, self.set_name, mode)
        _update_edit_meshes(context)
        _tag_mirror_dirty()
        return {"FINISHED"}


class IOPS_OT_SSDelete(bpy.types.Operator):
    """Delete this selection set"""
    bl_idname = "iops.ss_delete"
    bl_label = "Delete Selection Set"
    bl_options = {"REGISTER", "UNDO"}

    set_name: bpy.props.StringProperty(name="Set")

    @classmethod
    def poll(cls, context):
        return context.mode in {"EDIT_MESH", "OBJECT"}

    def execute(self, context):
        if context.mode == "OBJECT":
            scene_delete_set(context.scene, self.set_name)
            _tag_mirror_dirty()
            return {"FINISHED"}
        for _obj, bm in edit_meshes(context):
            bm_delete_set(bm, self.set_name)
        _update_edit_meshes(context)
        _tag_mirror_dirty()
        return {"FINISHED"}


class IOPS_OT_SSBool(bpy.types.Operator):
    """Boolean of the current selection with the set — the result
    becomes the selection.
    Shift: reversed — the selection is applied to the set itself
    (e.g. Subtract removes the selection from the set)"""
    bl_idname = "iops.ss_bool"
    bl_label = "Selection Set Boolean"
    bl_options = {"REGISTER", "UNDO"}

    set_name: bpy.props.StringProperty(name="Set")
    mode: bpy.props.EnumProperty(items=[
        ("EXTEND", "Extend", "Union"),
        ("SUBTRACT", "Subtract", "Difference"),
        ("INTERSECT", "Intersect", "Intersection"),
        ("DIFFERENCE", "Difference", "Symmetric difference"),
    ], default="EXTEND")
    into_set: bpy.props.BoolProperty(
        name="Apply To Set", default=False,
        description="Write the result into the set instead of the selection")

    _OPS = {"EXTEND": set.union, "SUBTRACT": set.difference,
            "INTERSECT": set.intersection, "DIFFERENCE": set.symmetric_difference}

    @classmethod
    def poll(cls, context):
        return context.mode in {"EDIT_MESH", "OBJECT"}

    def invoke(self, context, event):
        self.into_set = event.shift
        return self.execute(context)

    def execute(self, context):
        op = self._OPS[self.mode]
        if context.mode == "OBJECT":
            scene = context.scene
            if scene_get(scene, self.set_name) is None:
                self.report({"WARNING"}, f"Set '{self.set_name}' not found")
                return {"CANCELLED"}
            member = scene_membership(scene, self.set_name)
            sel = {o.name for o in context.selected_objects}
            if self.into_set:
                scene_write_membership(scene, self.set_name,
                                       op(member, sel))
                _tag_mirror_dirty()
            else:
                result = op(sel, member)
                for obj in context.selected_objects:
                    obj.select_set(False)
                for obj_name in sorted(result):
                    obj = scene.objects.get(obj_name)
                    if obj is not None and not obj.hide_get():
                        obj.select_set(True)
            _set_active_mirror_row(context, self.set_name)
            return {"FINISHED"}
        if not _flags_for(context, self.set_name):
            self.report({"WARNING"}, f"Set '{self.set_name}' not found")
            return {"CANCELLED"}
        for _obj, bm in edit_meshes(context):
            if self.into_set:
                # selection modifies the set, on its stored domains only
                member = bm_set_membership(bm, self.set_name)
                if not member:
                    continue
                new = {}
                for d, indices in member.items():
                    seq = _dom_seq(bm, d)
                    seq.index_update()
                    sel = {e.index for e in seq if e.select}
                    new[d] = op(indices, sel)
                bm_write_membership(bm, self.set_name, new)
            elif self.mode == "INTERSECT":
                bm_intersect_selection(bm, self.set_name)
            elif self.mode == "DIFFERENCE":
                allowed = _expanded_membership(bm, self.set_name)
                current = _bm_current_selection(bm)
                _bm_set_exact_selection(
                    bm, {d: current[d] ^ allowed[d] for d in DOMAINS})
            else:
                bm_apply_selection(bm, self.set_name, self.mode)
        _update_edit_meshes(context)
        if self.into_set:
            _tag_mirror_dirty()
        _set_active_mirror_row(context, self.set_name)
        return {"FINISHED"}


class IOPS_OT_SSRename(bpy.types.Operator):
    """Rename this selection set"""
    bl_idname = "iops.ss_rename"
    bl_label = "Rename Selection Set"
    bl_options = {"REGISTER", "UNDO"}

    set_name: bpy.props.StringProperty(name="Set", options={"HIDDEN"})
    new_name: bpy.props.StringProperty(name="Name")

    @classmethod
    def poll(cls, context):
        return context.mode in {"EDIT_MESH", "OBJECT"}

    def invoke(self, context, event):
        self.new_name = self.set_name
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        old = self.set_name
        new = sanitize_set_name(self.new_name)
        if not old or new == old:
            return {"CANCELLED"}
        if context.mode == "OBJECT":
            if scene_get(context.scene, old) is None:
                self.report({"WARNING"}, f"Set '{old}' not found")
                return {"CANCELLED"}
            taken = [s.name for s in context.scene.iops_selection_sets
                     if s.name != old]
            new = unique_name(new, taken)
            scene_rename_set(context.scene, old, new)
        else:
            taken = [n for n in all_edit_set_names(context) if n != old]
            new = unique_name(new, taken)
            for _obj, bm in edit_meshes(context):
                bm_rename_set(bm, old, new)
            _update_edit_meshes(context)
        _preview_renamed(old, new)
        _tag_mirror_dirty()
        _rebuild_mirror_now(context)
        _set_active_mirror_row(context, new)
        return {"FINISHED"}


def bm_selection_membership(bm, mode):
    out = {}
    for d, on in zip(DOMAINS, mode):
        if not on:
            continue
        seq = _dom_seq(bm, d)
        seq.index_update()
        out[d] = {e.index for e in seq if e.select}
    return out


def _bm_select_membership(bm, membership):
    """Select exactly the given {domain: indices} (additive; caller
    deselects first)."""
    for d, indices in membership.items():
        seq = _dom_seq(bm, d)
        seq.index_update()
        for e in seq:
            if e.index in indices and not e.hide:
                e.select = True
    bm.select_flush(True)
    bm.select_flush_mode()


class IOPS_OT_SSUnion(bpy.types.Operator):
    """Merge the checked sets into a new set or into the target set"""
    bl_idname = "iops.ss_union"
    bl_label = "Union Selection Sets"
    bl_options = {"REGISTER", "UNDO"}

    set_names: bpy.props.StringProperty(name="Sets")  # ';'-joined
    target: bpy.props.StringProperty(name="Target", default="")

    @classmethod
    def poll(cls, context):
        return context.mode in {"EDIT_MESH", "OBJECT"}

    def execute(self, context):
        names = [n for n in self.set_names.split(";") if n]
        if len(names) < 2 and not (self.target and len(names) == 1):
            self.report({"WARNING"}, "Check at least two sets to union")
            return {"CANCELLED"}
        # Union → Active must include the target's own content, or an
        # unchecked target gets silently overwritten by the checked sets.
        if self.target and self.target not in names:
            names.append(self.target)
        if context.mode == "OBJECT":
            scene = context.scene
            merged = set().union(
                *(scene_membership(scene, n) for n in names))
            target = self.target or unique_name(
                "Union", [s.name for s in scene.iops_selection_sets])
            scene_write_membership(scene, target, merged)
        else:
            target = self.target or unique_name(
                "Union", all_edit_set_names(context))
            for _obj, bm in edit_meshes(context):
                merged = merge_membership(
                    bm_set_membership(bm, n) for n in names)
                if merged:
                    bm_write_membership(bm, target, merged)
            _update_edit_meshes(context)
        _tag_mirror_dirty()
        return {"FINISHED"}


class IOPS_OT_SSDifference(bpy.types.Operator):
    """Select the symmetric difference: between two checked sets, or
    between the current selection and one set"""
    bl_idname = "iops.ss_difference"
    bl_label = "Selection Sets Difference"
    bl_options = {"REGISTER", "UNDO"}

    set_names: bpy.props.StringProperty(name="Sets")  # ';'-joined, 1 or 2

    @classmethod
    def poll(cls, context):
        return context.mode in {"EDIT_MESH", "OBJECT"}

    def execute(self, context):
        names = [n for n in self.set_names.split(";") if n]
        if not names or len(names) > 2:
            self.report({"WARNING"},
                        "Check one set (vs selection) or exactly two sets")
            return {"CANCELLED"}
        if context.mode == "OBJECT":
            scene = context.scene
            # Unlike edit mode (a set may legitimately exist on only some
            # meshes in multi-edit), an object-level set either exists in
            # the scene or it doesn't — diffing against a silently-empty
            # missing set would be misleading, so ss_recall's consistency
            # is mirrored here.
            for n in names:
                if scene_get(scene, n) is None:
                    self.report({"WARNING"}, f"Set '{n}' not found")
                    return {"CANCELLED"}
            a = (scene_membership(scene, names[0]) if len(names) == 2
                 else {o.name for o in context.selected_objects})
            b = scene_membership(scene, names[-1])
            result = a ^ b
            for obj in context.selected_objects:
                obj.select_set(False)
            for obj_name in result:
                obj = scene.objects.get(obj_name)
                if obj is not None and not obj.hide_get():
                    obj.select_set(True)
        else:
            mode = context.tool_settings.mesh_select_mode[:]
            per_bm = []
            for obj, bm in edit_meshes(context):
                a = (bm_set_membership(bm, names[0]) if len(names) == 2
                     else bm_selection_membership(bm, mode))
                b = bm_set_membership(bm, names[-1])
                per_bm.append((obj, bm, diff_membership(a, b)))
            bpy.ops.mesh.select_all(action="DESELECT")
            for _obj, bm, result in per_bm:
                _bm_select_membership(bm, result)
            _update_edit_meshes(context)
        return {"FINISHED"}


class IOPS_OT_SSDeleteAll(bpy.types.Operator):
    """Delete all selection sets"""
    bl_idname = "iops.ss_delete_all"
    bl_label = "Delete All Selection Sets"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode in {"EDIT_MESH", "OBJECT"}

    def execute(self, context):
        if context.mode == "OBJECT":
            n = len(context.scene.iops_selection_sets)
            context.scene.iops_selection_sets.clear()
            _tag_mirror_dirty()
            return {"FINISHED"} if n else {"CANCELLED"}
        removed = 0
        for _obj, bm in edit_meshes(context):
            removed += bm_delete_all(bm)
        _update_edit_meshes(context)
        _tag_mirror_dirty()
        return {"FINISHED"} if removed else {"CANCELLED"}
