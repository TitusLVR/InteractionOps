"""iOps Attributes — mesh attribute backends and operators.

Backends: bmesh layers in Edit Mode, `mesh.attributes` in Object Mode,
and `snapshot()` — the read path used by handlers: the edit bmesh in Edit
Mode (only while no modal operator runs, see modal_running() and the
crash notes in mesh_nonplanar_overlay.py), `foreach_get` over obj.data in
Object Mode. Draw callbacks never touch Python bmesh.
"""
import bpy
import bmesh
import numpy as np

from ..utils.attribute_editor_core import (
    DOMAINS, TYPES, Row, coerce, default_value, gradient, math_op,
    order_chain, randomize, select_predicate, smooth, unique_name,
)

__all__ = ["edit_meshes", "bm_seq", "bm_layer", "bm_selected_indices",
           "bm_active_index", "bm_read", "bm_write", "bm_values",
           "bm_write_values", "mesh_read_all", "mesh_write_all", "snapshot",
           "bm_all_values", "vgroup_index", "finish_edit", "modal_running",
           "DOMAINS", "Row",
           "default_value", "resolve_row", "apply_value", "active_mesh",
           "OPERATOR_CLASSES", "tool_supports"]


# ---------------------------------------------------------------------------
# bmesh backend (Edit Mode, operators only)
# ---------------------------------------------------------------------------
def edit_meshes(context):
    out = []
    for obj in context.objects_in_mode_unique_data:
        if obj.type == "MESH":
            bm = bmesh.from_edit_mesh(obj.data)
            out.append((obj, bm))
    return out


def bm_seq(bm, domain):
    if domain == "POINT":
        return bm.verts
    if domain == "EDGE":
        return bm.edges
    if domain == "FACE":
        return bm.faces
    return None


def _layers(bm, row):
    if row.domain == "CORNER":
        coll = bm.loops.layers
    else:
        coll = bm_seq(bm, row.domain).layers
    info = TYPES.get(row.data_type)
    if info is None or info.bm_layer is None:
        return None
    return getattr(coll, info.bm_layer, None)


def bm_layer(bm, row):
    if row.kind == "VGROUP":
        return bm.verts.layers.deform.verify()
    layers = _layers(bm, row)
    if layers is None:
        return None
    return layers.get(row.name)


def _lookup(bm, domain):
    seq = bm.faces if domain == "CORNER" else bm_seq(bm, domain)
    seq.ensure_lookup_table()
    seq.index_update()
    return seq


def bm_selected_indices(bm, domain):
    seq = _lookup(bm, domain)
    return [e.index for e in seq if e.select and not e.hide]


def bm_active_index(bm, domain):
    act = bm.select_history.active
    if act is None:
        return None
    want = {"POINT": bmesh.types.BMVert, "EDGE": bmesh.types.BMEdge,
            "FACE": bmesh.types.BMFace, "CORNER": bmesh.types.BMFace}[domain]
    if not isinstance(act, want):
        return None
    _lookup(bm, domain)
    return act.index


def _from_layer(value, row):
    if row.data_type == "STRING":
        return value.decode("utf-8", "replace") if isinstance(value, bytes) \
            else str(value)
    if TYPES[row.data_type].components > 1:
        return tuple(value)
    return value


def _to_layer(value, row):
    if row.data_type == "STRING":
        return value.encode("utf-8") if isinstance(value, str) else value
    if row.data_type == "BOOLEAN":
        return bool(value)
    if row.data_type in ("INT", "INT8"):
        return int(value)
    if TYPES[row.data_type].components > 1:
        return tuple(float(c) for c in value)
    return float(value)


def _elem_read(elem, layer, row, group_index):
    if row.kind == "VGROUP":
        return elem[layer].get(group_index, 0.0)
    if row.domain == "CORNER":
        return _from_layer(elem.loops[0][layer], row)
    return _from_layer(elem[layer], row)


def _elem_write(elem, layer, row, v, group_index):
    if row.kind == "VGROUP":
        elem[layer][group_index] = v
    elif row.domain == "CORNER":
        for loop in elem.loops:
            loop[layer] = v
    else:
        elem[layer] = v


def _prepare(bm, row):
    """(layer, lookup sequence) or (None, None). One index_update per
    call — callers that touch many elements go through here once."""
    layer = bm_layer(bm, row)
    if layer is None:
        return None, None
    return layer, _lookup(bm, row.domain)


def bm_read(bm, row, index, *, group_index=None):
    layer, seq = _prepare(bm, row)
    if layer is None:
        return None
    return _elem_read(seq[index], layer, row, group_index)


def bm_write(bm, row, indices, value, *, group_index=None):
    layer, seq = _prepare(bm, row)
    if layer is None:
        return 0
    v = float(value) if row.kind == "VGROUP" else _to_layer(value, row)
    n = 0
    for i in indices:
        _elem_write(seq[i], layer, row, v, group_index)
        n += 1
    return n


def bm_values(bm, row, indices, *, group_index=None):
    layer, seq = _prepare(bm, row)
    if layer is None:
        return [None] * len(indices)
    return [_elem_read(seq[i], layer, row, group_index) for i in indices]


def bm_write_values(bm, row, indices, values, *, group_index=None):
    layer, seq = _prepare(bm, row)
    if layer is None:
        return 0
    n = 0
    for i, v in zip(indices, values):
        v = float(v) if row.kind == "VGROUP" else _to_layer(v, row)
        _elem_write(seq[i], layer, row, v, group_index)
        n += 1
    return n


def bm_all_values(bm, row, *, group_index=None):
    """Values of every element of the row's domain, in index order."""
    layer, seq = _prepare(bm, row)
    if layer is None:
        return []
    return [_elem_read(e, layer, row, group_index) for e in seq]


def finish_edit(obj):
    bmesh.update_edit_mesh(obj.data, loop_triangles=False,
                           destructive=False)


# ---------------------------------------------------------------------------
# mesh.attributes backend (Object Mode)
# ---------------------------------------------------------------------------
_DATA_PROP = {
    "FLOAT_VECTOR": "vector", "FLOAT2": "vector",
    "FLOAT_COLOR": "color", "BYTE_COLOR": "color",
}


def _data_prop(attr):
    return _DATA_PROP.get(attr.data_type, "value")


def mesh_read_all(me, name):
    attr = me.attributes[name]
    n = len(attr.data)
    if n == 0:
        return []
    if attr.data_type == "STRING":
        return [d.value for d in attr.data]
    comps = TYPES[attr.data_type].components
    prop = _data_prop(attr)
    if comps == 1:
        if attr.data_type == "BOOLEAN":
            buf = np.empty(n, bool)
        elif attr.data_type in ("INT", "INT8"):
            buf = np.empty(n, np.int32)
        else:
            buf = np.empty(n, np.float32)
        attr.data.foreach_get(prop, buf)
        return buf.tolist()
    dtype = np.int32 if attr.data_type.startswith("INT") else np.float32
    buf = np.empty(n * comps, dtype)
    attr.data.foreach_get(prop, buf)
    return [tuple(r) for r in buf.reshape(n, comps).tolist()]


def mesh_write_all(me, name, value):
    attr = me.attributes[name]
    n = len(attr.data)
    if n == 0:
        return 0
    if attr.data_type == "STRING":
        for d in attr.data:
            d.value = str(value)
        return n
    comps = TYPES[attr.data_type].components
    prop = _data_prop(attr)
    if comps == 1:
        if attr.data_type == "BOOLEAN":
            buf = np.full(n, bool(value), bool)
        elif attr.data_type in ("INT", "INT8"):
            buf = np.full(n, int(value), np.int32)
        else:
            buf = np.full(n, float(value), np.float32)
    else:
        dtype = np.int32 if attr.data_type.startswith("INT") else np.float32
        buf = np.tile(np.asarray(list(value)[:comps], dtype), n)
    attr.data.foreach_set(prop, buf)
    return n


def vgroup_index(obj, name):
    vg = obj.vertex_groups.get(name)
    return None if vg is None else vg.index


# ---------------------------------------------------------------------------
# snapshot — handler-safe read of positions, values, selection, hidden
# ---------------------------------------------------------------------------
# Edit Mode reads the edit bmesh. obj.to_mesh() returns the STALE mesh in
# edit mode and obj.update_from_editmode() fires a depsgraph update of its
# own (verified headless on 5.2.3), which would re-evaluate every modifier
# twice per edit. Python bmesh access is safe as long as no modal operator
# runs (see mesh_nonplanar_overlay.py): callers check modal_running()
# first and keep their previous data while one is active.
def modal_running(context=None):
    import bpy
    wm = (context.window_manager if context is not None
          else bpy.context.window_manager)
    if wm is None:
        return False
    for win in wm.windows:
        try:
            if len(win.modal_operators):
                return True
        except AttributeError:
            return False
    return False


def _bool_attr(me, name, n):
    attr = me.attributes.get(name)
    if attr is None or len(attr.data) != n:
        return np.zeros(n, bool)
    buf = np.empty(n, bool)
    attr.data.foreach_get("value", buf)
    return buf


def _world(pos, mw):
    m = np.asarray(mw, np.float32)
    return np.asarray(pos, np.float32).reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]


def _positions(me, domain, mw):
    nv = len(me.vertices)
    co = np.empty(nv * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(nv, 3)
    if domain == "POINT":
        pos = co
    elif domain == "EDGE":
        ne = len(me.edges)
        ev = np.empty(ne * 2, np.int32)
        me.edges.foreach_get("vertices", ev)
        ev = ev.reshape(ne, 2)
        pos = (co[ev[:, 0]] + co[ev[:, 1]]) * 0.5
    else:
        nf = len(me.polygons)
        center = np.empty(nf * 3, np.float32)
        me.polygons.foreach_get("center", center)
        center = center.reshape(nf, 3)
        if domain == "FACE":
            pos = center
        else:
            nl = len(me.loops)
            lv = np.empty(nl, np.int32)
            me.loops.foreach_get("vertex_index", lv)
            lt = np.empty(nf, np.int32)
            me.polygons.foreach_get("loop_total", lt)
            face_of_loop = np.repeat(np.arange(nf, dtype=np.int32), lt)
            pos = co[lv] * 0.75 + center[face_of_loop] * 0.25
    return _world(pos, mw)


def _mesh_values(me, name, domain, kind, obj, n):
    if kind == "VGROUP":
        gi = vgroup_index(obj, name)
        w = np.zeros(n, np.float32)
        if gi is not None:
            for i, v in enumerate(me.vertices):
                for g in v.groups:
                    if g.group == gi:
                        w[i] = g.weight
                        break
        return w
    attr = me.attributes.get(name)
    if attr is None or attr.domain != domain or len(attr.data) != n:
        return None
    if attr.data_type == "STRING":
        return np.array([d.value for d in attr.data], dtype=object)
    comps = TYPES[attr.data_type].components
    prop = _data_prop(attr)
    if attr.data_type == "BOOLEAN":
        buf = np.empty(n, bool)
    elif attr.data_type.startswith("INT"):
        buf = np.empty(n * comps, np.int32)
    else:
        buf = np.empty(n * comps, np.float32)
    attr.data.foreach_get(prop, buf)
    return buf if comps == 1 else buf.reshape(n, comps)


def _snapshot_object(obj, name, domain, kind):
    me = obj.data
    counts = {"POINT": len(me.vertices), "EDGE": len(me.edges),
              "FACE": len(me.polygons), "CORNER": len(me.loops)}
    n = counts[domain]
    values = _mesh_values(me, name, domain, kind, obj, n)
    if values is None:
        return None
    pos = _positions(me, domain, obj.matrix_world) if n else \
        np.zeros((0, 3), np.float32)
    if domain == "CORNER":
        nf = len(me.polygons)
        lt = np.empty(nf, np.int32)
        me.polygons.foreach_get("loop_total", lt)
        rep = np.repeat(np.arange(nf, dtype=np.int32), lt)
        sel = _bool_attr(me, ".select_poly", nf)[rep]
        hid = _bool_attr(me, ".hide_poly", nf)[rep]
    else:
        suffix = {"POINT": "vert", "EDGE": "edge", "FACE": "poly"}[domain]
        sel = _bool_attr(me, ".select_" + suffix, n)
        hid = _bool_attr(me, ".hide_" + suffix, n)
    return pos, values, sel, hid


def _np_values(raw, row):
    if row.data_type == "STRING":
        return np.array(raw, dtype=object)
    if row.data_type == "BOOLEAN":
        return np.asarray(raw, bool)
    if row.data_type in ("INT", "INT8"):
        return np.asarray(raw, np.int32)
    comps = TYPES[row.data_type].components
    arr = np.asarray(raw, np.float32)
    return arr.reshape(-1, comps) if comps > 1 else arr


def _snapshot_edit(obj, name, domain, kind):
    me = obj.data
    if kind == "VGROUP":
        data_type = "VGROUP"
    else:
        attr = me.attributes.get(name)
        if attr is None or attr.domain != domain:
            return None
        data_type = attr.data_type
    row = Row(name, data_type, domain, kind, True)
    bm = bmesh.from_edit_mesh(me)
    layer = bm_layer(bm, row)
    if layer is None:
        return None
    gi = vgroup_index(obj, name) if kind == "VGROUP" else None
    if kind == "VGROUP":
        raw = [v[layer].get(gi, 0.0) for v in bm.verts]
    elif domain == "CORNER":
        raw = [loop[layer] for f in bm.faces for loop in f.loops]
    else:
        raw = [e[layer] for e in bm_seq(bm, domain)]
    if data_type == "STRING":
        raw = [r.decode("utf-8", "replace") if isinstance(r, bytes) else r
               for r in raw]
    values = _np_values(raw, row)
    if domain == "POINT":
        pos = [v.co for v in bm.verts]
        sel = [v.select for v in bm.verts]
        hid = [v.hide for v in bm.verts]
    elif domain == "EDGE":
        pos = [(e.verts[0].co + e.verts[1].co) * 0.5 for e in bm.edges]
        sel = [e.select for e in bm.edges]
        hid = [e.hide for e in bm.edges]
    elif domain == "FACE":
        pos = [f.calc_center_median() for f in bm.faces]
        sel = [f.select for f in bm.faces]
        hid = [f.hide for f in bm.faces]
    else:
        pos, sel, hid = [], [], []
        for f in bm.faces:
            c = f.calc_center_median()
            for loop in f.loops:
                pos.append(loop.vert.co * 0.75 + c * 0.25)
                sel.append(f.select)
                hid.append(f.hide)
    arr = (np.array([tuple(p) for p in pos], np.float32) if pos
           else np.zeros((0, 3), np.float32))
    return (_world(arr, obj.matrix_world), values,
            np.asarray(sel, bool), np.asarray(hid, bool))


def snapshot(obj, name, domain, *, kind="ATTR"):
    """(positions[n,3] world, values[n] or [n,c], selected[n], hidden[n])
    for the attribute `name` on `domain`, or None when the object is not
    a mesh or the attribute is missing. Edit Mode reads the edit bmesh:
    call only when modal_running() is False."""
    if obj is None or obj.type != "MESH":
        return None
    if obj.mode == "EDIT" and obj.data.is_editmode:
        return _snapshot_edit(obj, name, domain, kind)
    return _snapshot_object(obj, name, domain, kind)


# ---------------------------------------------------------------------------
# Hooks wired by ui/iops_attribute_panel.py at register time (no-ops until
# then, so the operators have no UI dependency).
# ---------------------------------------------------------------------------
def _tag_mirror_dirty():
    pass


def _rebuild_mirror_now(context):
    pass


def _set_active_row(context, name):
    pass


def _invalidate_cache():
    pass


def _notify(context, name=None):
    _invalidate_cache()
    _tag_mirror_dirty()
    if name is not None:
        _set_active_row(context, name)


# ---------------------------------------------------------------------------
# Row resolution and value application (shared by operators and the UI)
# ---------------------------------------------------------------------------
_DATA_TYPE_ITEMS = [(t, t, "") for t in TYPES if t != "VGROUP"]
_DOMAIN_ITEMS = [(d, d.capitalize(), "") for d in DOMAINS]
_KIND_ITEMS = [("ATTR", "Attribute", ""), ("VGROUP", "Vertex Group", "")]


def active_mesh(context):
    obj = context.active_object
    if obj is None or obj.type != "MESH":
        return None
    return obj


def resolve_row(context, name, kind="ATTR"):
    obj = active_mesh(context)
    if obj is None:
        return None
    if kind == "VGROUP":
        if obj.vertex_groups.get(name) is None:
            return None
        return Row(name, "VGROUP", "POINT", "VGROUP", True)
    attr = obj.data.attributes.get(name)
    if attr is None or attr.domain not in DOMAINS \
            or attr.data_type not in TYPES:
        return None
    edit = context.mode == "EDIT_MESH"
    info = TYPES[attr.data_type]
    editable = attr.data_type != "STRING" and (
        info.bm_layer is not None or not edit)
    return Row(name, attr.data_type, attr.domain, "ATTR", editable)


def _vgroup_set_all(obj, name, value, members_only=False):
    vg = obj.vertex_groups.get(name)
    if vg is None:
        return 0
    if members_only:
        gi = vg.index
        idx = [v.index for v in obj.data.vertices
               if any(g.group == gi for g in v.groups)]
    else:
        idx = list(range(len(obj.data.vertices)))
    if idx:
        vg.add(idx, float(value), "REPLACE")
    return len(idx)


def _edit_indices(bm, domain, target):
    seq = _lookup(bm, domain)
    if target == "SELECTED":
        return [e.index for e in seq if e.select and not e.hide]
    if target == "UNSELECTED":
        return [e.index for e in seq if not e.select and not e.hide]
    return [e.index for e in seq if not e.hide]


def apply_value(context, row, value, target="SELECTED",
                members_only=False):
    """Write `value` to the row's elements: Edit Mode → the target set on
    every edit mesh carrying the row; Object Mode → every element of the
    active object. Returns the number of elements written."""
    n = 0
    if context.mode == "EDIT_MESH":
        for obj, bm in edit_meshes(context):
            gi = None
            if row.kind == "VGROUP":
                gi = vgroup_index(obj, row.name)
                if gi is None:
                    continue
            elif bm_layer(bm, row) is None:
                continue
            attr = obj.data.attributes.get(row.name)
            if row.kind == "ATTR" and (attr is None
                                       or attr.domain != row.domain
                                       or attr.data_type != row.data_type):
                continue
            idx = _edit_indices(bm, row.domain, target)
            if not idx:
                continue
            n += bm_write(bm, row, idx, value, group_index=gi)
            finish_edit(obj)
        return n
    obj = active_mesh(context)
    if obj is None:
        return 0
    if row.kind == "VGROUP":
        return _vgroup_set_all(obj, row.name, value, members_only)
    if row.name not in obj.data.attributes:
        return 0
    return mesh_write_all(obj.data, row.name, value)


class _ValueProps:
    """Mixin: one property per widget kind + the picker."""
    value_float: bpy.props.FloatProperty(name="Value", precision=3)
    value_int: bpy.props.IntProperty(name="Value")
    value_bool: bpy.props.BoolProperty(name="Value")
    value_vector: bpy.props.FloatVectorProperty(name="Value", size=3,
                                                precision=3)
    value_color: bpy.props.FloatVectorProperty(name="Value", size=4,
                                               subtype="COLOR", min=0.0,
                                               max=1.0,
                                               default=(0, 0, 0, 1))
    value_string: bpy.props.StringProperty(name="Value")

    def value_for(self, row):
        info = TYPES[row.data_type]
        w = info.widget
        if w == "FLOAT":
            return float(self.value_float)
        if w == "INT":
            return int(self.value_int)
        if w == "BOOL":
            return bool(self.value_bool)
        if w == "VECTOR":
            return tuple(self.value_vector)[:info.components]
        if w == "COLOR":
            return tuple(self.value_color)
        if w == "STRING":
            return self.value_string
        return None

    def draw_value(self, layout, row):
        w = TYPES[row.data_type].widget
        prop = {"FLOAT": "value_float", "INT": "value_int",
                "BOOL": "value_bool", "VECTOR": "value_vector",
                "COLOR": "value_color", "STRING": "value_string"}.get(w)
        if prop is None:
            layout.label(text="Type is read-only", icon="LOCKED")
        else:
            layout.prop(self, prop)


class _RowProps:
    row_name: bpy.props.StringProperty(name="Attribute",
                                       options={"HIDDEN"})
    row_kind: bpy.props.EnumProperty(name="Kind", items=_KIND_ITEMS,
                                     default="ATTR", options={"HIDDEN"})

    def row(self, context):
        return resolve_row(context, self.row_name, self.row_kind)


def _poll_mesh(context):
    return (active_mesh(context) is not None
            and context.mode in {"OBJECT", "EDIT_MESH"})


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------
class IOPS_OT_AttrSetValue(_RowProps, _ValueProps, bpy.types.Operator):
    """Write the value to the selected elements (Edit Mode) or to every
    element (Object Mode)"""
    bl_idname = "iops.attr_set_value"
    bl_label = "Set Attribute Value"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    @classmethod
    def poll(cls, context):
        return _poll_mesh(context)

    def execute(self, context):
        row = self.row(context)
        if row is None:
            self.report({"WARNING"}, f"Attribute '{self.row_name}' not found")
            return {"CANCELLED"}
        if not row.editable:
            self.report({"WARNING"}, "Edit in Object Mode (bmesh has no "
                        "layer for this type)")
            return {"CANCELLED"}
        value = self.value_for(row)
        if value is None:
            return {"CANCELLED"}
        n = apply_value(context, row, value)
        if n == 0:
            self.report({"WARNING"}, "Nothing selected")
            return {"CANCELLED"}
        _notify(context)
        return {"FINISHED"}


class IOPS_OT_AttrFill(_RowProps, _ValueProps, bpy.types.Operator):
    """Write a value, or the type's default, to the selected, unselected
    or all elements"""
    bl_idname = "iops.attr_fill"
    bl_label = "Set on Selection"
    bl_options = {"REGISTER", "UNDO"}

    reset: bpy.props.BoolProperty(name="Reset to Default", default=False)
    target: bpy.props.EnumProperty(
        name="Target",
        items=[("SELECTED", "Selected", ""), ("UNSELECTED", "Unselected", ""),
               ("ALL", "All", "")],
        default="SELECTED")

    @classmethod
    def poll(cls, context):
        return _poll_mesh(context)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        row = self.row(context)
        layout.prop(self, "reset")
        if context.mode == "EDIT_MESH":
            layout.prop(self, "target")
        if row is not None and not self.reset:
            self.draw_value(layout, row)

    def execute(self, context):
        row = self.row(context)
        if row is None or not row.editable:
            self.report({"WARNING"}, "Attribute not editable here")
            return {"CANCELLED"}
        if self.reset:
            value = 0.0 if row.kind == "VGROUP" else \
                default_value(row.data_type)
        else:
            value = self.value_for(row)
        if value is None:
            return {"CANCELLED"}
        target = self.target if context.mode == "EDIT_MESH" else "ALL"
        n = apply_value(context, row, value, target,
                        members_only=self.reset)
        if n == 0:
            self.report({"WARNING"}, "No elements to write")
            return {"CANCELLED"}
        _notify(context)
        return {"FINISHED"}


class IOPS_OT_AttrNew(_ValueProps, bpy.types.Operator):
    """Create a new attribute on the active mesh"""
    bl_idname = "iops.attr_new"
    bl_label = "New Attribute"
    bl_options = {"REGISTER", "UNDO"}

    name: bpy.props.StringProperty(name="Name", default="Attribute")
    data_type: bpy.props.EnumProperty(name="Type", items=_DATA_TYPE_ITEMS,
                                      default="FLOAT")
    domain: bpy.props.EnumProperty(name="Domain", items=_DOMAIN_ITEMS,
                                   default="POINT")

    @classmethod
    def poll(cls, context):
        return _poll_mesh(context)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "name")
        layout.prop(self, "data_type")
        layout.prop(self, "domain")
        if context.mode == "OBJECT":
            self.draw_value(layout, Row("", self.data_type, self.domain,
                                        "ATTR", True))

    def execute(self, context):
        obj = active_mesh(context)
        me = obj.data
        name = unique_name(self.name.strip() or "Attribute",
                           [a.name for a in me.attributes])
        attr = me.attributes.new(name, self.data_type, self.domain)
        if attr is None:
            self.report({"ERROR"}, "Could not create the attribute")
            return {"CANCELLED"}
        name = attr.name
        if context.mode == "OBJECT":
            row = Row(name, self.data_type, self.domain, "ATTR", True)
            value = self.value_for(row)
            if value is not None and value != default_value(self.data_type):
                mesh_write_all(me, name, value)
        elif context.mode == "EDIT_MESH":
            finish_edit(obj)
        me.attributes.active = attr
        _notify(context, name)
        return {"FINISHED"}


class IOPS_OT_AttrRemove(_RowProps, bpy.types.Operator):
    """Remove the attribute or vertex group"""
    bl_idname = "iops.attr_remove"
    bl_label = "Remove Attribute"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _poll_mesh(context)

    def execute(self, context):
        obj = active_mesh(context)
        if self.row_kind == "VGROUP":
            vg = obj.vertex_groups.get(self.row_name)
            if vg is None:
                return {"CANCELLED"}
            obj.vertex_groups.remove(vg)
        else:
            attr = obj.data.attributes.get(self.row_name)
            if attr is None:
                return {"CANCELLED"}
            try:
                obj.data.attributes.remove(attr)
            except RuntimeError as exc:
                self.report({"WARNING"}, f"Cannot remove '{self.row_name}': "
                            f"{exc}")
                return {"CANCELLED"}
            if context.mode == "EDIT_MESH":
                finish_edit(obj)
        _notify(context)
        return {"FINISHED"}


class IOPS_OT_AttrDuplicate(_RowProps, bpy.types.Operator):
    """Duplicate the attribute with its data"""
    bl_idname = "iops.attr_duplicate"
    bl_label = "Duplicate Attribute"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _poll_mesh(context)

    def execute(self, context):
        obj = active_mesh(context)
        me = obj.data
        if self.row_kind == "VGROUP":
            src = obj.vertex_groups.get(self.row_name)
            if src is None:
                return {"CANCELLED"}
            if context.mode == "EDIT_MESH":
                self.report({"WARNING"}, "Duplicate vertex groups in Object "
                            "Mode")
                return {"CANCELLED"}
            new_name = unique_name(f"{src.name}.copy",
                                   [g.name for g in obj.vertex_groups])
            dst = obj.vertex_groups.new(name=new_name)
            gi = src.index
            for v in me.vertices:
                for g in v.groups:
                    if g.group == gi:
                        dst.add([v.index], g.weight, "REPLACE")
            _notify(context, new_name)
            return {"FINISHED"}
        attr = me.attributes.get(self.row_name)
        if attr is None:
            return {"CANCELLED"}
        new_name = unique_name(f"{attr.name}.copy",
                               [a.name for a in me.attributes])
        data_type, domain = attr.data_type, attr.domain
        if context.mode == "EDIT_MESH":
            row = Row(attr.name, data_type, domain, "ATTR", True)
            bm = bmesh.from_edit_mesh(me)
            layers = _layers(bm, row)
            if layers is None:
                self.report({"WARNING"}, "Duplicate this type in Object Mode")
                return {"CANCELLED"}
            layers.new(new_name)
            layers = _layers(bm, row)      # new() may invalidate refs
            layers[new_name].copy_from(layers[attr.name])
            finish_edit(obj)
        else:
            values = mesh_read_all(me, attr.name)
            try:
                new = me.attributes.new(new_name, data_type, domain)
            except RuntimeError as exc:
                self.report({"WARNING"}, f"Cannot duplicate: {exc}")
                return {"CANCELLED"}
            if new is None:
                self.report({"WARNING"}, "Cannot duplicate this attribute")
                return {"CANCELLED"}
            new_name = new.name
            if values:
                _write_values_object(me, new_name, values)
        _notify(context, new_name)
        return {"FINISHED"}


def _write_values_object(me, name, values):
    attr = me.attributes[name]
    if attr.data_type == "STRING":
        for d, v in zip(attr.data, values):
            d.value = v
        return
    comps = TYPES[attr.data_type].components
    prop = _data_prop(attr)
    if comps == 1:
        if attr.data_type == "BOOLEAN":
            buf = np.asarray(values, bool)
        elif attr.data_type in ("INT", "INT8"):
            buf = np.asarray(values, np.int32)
        else:
            buf = np.asarray(values, np.float32)
    else:
        dtype = np.int32 if attr.data_type.startswith("INT") else np.float32
        buf = np.asarray(values, dtype).reshape(-1)
    attr.data.foreach_set(prop, buf)


class IOPS_OT_AttrConvert(_RowProps, bpy.types.Operator):
    """Convert the attribute's type and domain (Object Mode)"""
    bl_idname = "iops.attr_convert"
    bl_label = "Convert Attribute"
    bl_options = {"REGISTER", "UNDO"}

    data_type: bpy.props.EnumProperty(name="Type", items=_DATA_TYPE_ITEMS,
                                      default="FLOAT")
    domain: bpy.props.EnumProperty(name="Domain", items=_DOMAIN_ITEMS,
                                   default="POINT")

    @classmethod
    def poll(cls, context):
        return active_mesh(context) is not None and context.mode == "OBJECT"

    def invoke(self, context, event):
        attr = active_mesh(context).data.attributes.get(self.row_name)
        if attr is not None:
            self.data_type = attr.data_type
            self.domain = attr.domain
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        obj = active_mesh(context)
        attr = obj.data.attributes.get(self.row_name)
        if attr is None or self.row_kind != "ATTR":
            return {"CANCELLED"}
        obj.data.attributes.active = attr
        try:
            bpy.ops.geometry.attribute_convert(mode="GENERIC",
                                               domain=self.domain,
                                               data_type=self.data_type)
        except RuntimeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        _notify(context, self.row_name)
        return {"FINISHED"}


class IOPS_OT_AttrRefresh(bpy.types.Operator):
    """Rebuild the attribute list from the mesh"""
    bl_idname = "iops.attr_refresh"
    bl_label = "Refresh Attributes"

    def execute(self, context):
        _invalidate_cache()
        _rebuild_mirror_now(context)
        return {"FINISHED"}


OPERATOR_CLASSES = (
    IOPS_OT_AttrSetValue,
    IOPS_OT_AttrFill,
    IOPS_OT_AttrNew,
    IOPS_OT_AttrRemove,
    IOPS_OT_AttrDuplicate,
    IOPS_OT_AttrConvert,
    IOPS_OT_AttrRefresh,
)


# ---------------------------------------------------------------------------
# Tools: type matrix, per-mesh targets, operators
# ---------------------------------------------------------------------------
_TOOL_RULES = {
    # tool: (allowed domains, bool allowed, vectors allowed)
    "GRADIENT": (("POINT", "EDGE"), False, True),
    "MATH": (DOMAINS, True, True),
    "SMOOTH": (DOMAINS[:3], False, True),
    "RANDOMIZE": (DOMAINS, True, True),
    "COPY": (DOMAINS, True, True),
    "SELECT": (DOMAINS, True, True),
}


def tool_supports(tool, row):
    """None when `tool` can run on `row`, else the reason (tooltip)."""
    info = TYPES.get(row.data_type)
    if info is None or row.data_type == "STRING" or info.widget == "READONLY":
        return "Not available for this attribute type"
    if info.bm_layer is None:
        return _READONLY_REASON
    domains, allow_bool, allow_vec = _TOOL_RULES[tool]
    if row.domain not in domains:
        return f"{tool.title()} works on {' / '.join(d.lower() for d in domains)} attributes"
    if row.data_type == "BOOLEAN" and not allow_bool:
        return "Not available for boolean attributes"
    if info.components > 1 and not allow_vec:
        return "Not available for vector attributes"
    return None


_READONLY_REASON = "Edit in Object Mode (bmesh has no layer for this type)"


def _is_int_row(row):
    return row.data_type in ("INT", "INT8")


def _finalize(values, row):
    """Round INT results, keep vectors as tuples."""
    if _is_int_row(row):
        return [int(round(v)) for v in values]
    if row.data_type == "BOOLEAN":
        return [bool(v) for v in values]
    return values


def _edit_targets(context, row):
    """[(obj, bm, selected indices, group_index)] for every edit mesh that
    carries `row`."""
    out = []
    for obj, bm in edit_meshes(context):
        gi = None
        if row.kind == "VGROUP":
            gi = vgroup_index(obj, row.name)
            if gi is None:
                continue
        else:
            attr = obj.data.attributes.get(row.name)
            if attr is None or attr.domain != row.domain \
                    or attr.data_type != row.data_type \
                    or bm_layer(bm, row) is None:
                continue
        idx = bm_selected_indices(bm, row.domain)
        out.append((obj, bm, idx, gi))
    return out


def _map_values(self, context, row, fn):
    """Apply fn(values, row) -> values on the selection (Edit Mode) or on
    every element (Object Mode). Returns elements written."""
    n = 0
    if context.mode == "EDIT_MESH":
        for obj, bm, idx, gi in _edit_targets(context, row):
            if not idx:
                continue
            values = bm_values(bm, row, idx, group_index=gi)
            new = _finalize(fn(values, row), row)
            n += bm_write_values(bm, row, idx, new, group_index=gi)
            finish_edit(obj)
        return n
    obj = active_mesh(context)
    if obj is None:
        return 0
    if row.kind == "VGROUP":
        # members only: a tool must not grow the group's membership
        gi = vgroup_index(obj, row.name)
        me = obj.data
        members, values = [], []
        for v in me.vertices:
            for g in v.groups:
                if g.group == gi:
                    members.append(v.index)
                    values.append(g.weight)
                    break
        if not members:
            return 0
        new = fn(values, row)
        vg = obj.vertex_groups[row.name]
        for i, w in zip(members, new):
            vg.add([i], float(w), "REPLACE")
        return len(new)
    values = mesh_read_all(obj.data, row.name)
    if not values:
        return 0
    new = _finalize(fn(values, row), row)
    _write_values_object(obj.data, row.name, new)
    return len(new)


class _ToolBase(_RowProps):
    TOOL = ""

    @classmethod
    def poll(cls, context):
        return _poll_mesh(context)

    def check_row(self, context):
        row = self.row(context)
        if row is None:
            self.report({"WARNING"}, f"Attribute '{self.row_name}' not found")
            return None
        reason = tool_supports(self.TOOL, row)
        if reason is not None:
            self.report({"WARNING"}, reason)
            return None
        return row

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class IOPS_OT_AttrGradient(_ToolBase, bpy.types.Operator):
    """Interpolate the attribute along the selected chain of vertices,
    between the chain's end values or two typed values"""
    bl_idname = "iops.attr_gradient"
    bl_label = "Gradient on Chain"
    bl_options = {"REGISTER", "UNDO"}
    TOOL = "GRADIENT"

    mode: bpy.props.EnumProperty(
        name="Mode", items=[("LINEAR", "Linear", ""),
                            ("EASE_IN_OUT", "Ease In/Out", "")],
        default="LINEAR")
    use_typed: bpy.props.BoolProperty(name="Typed Ends", default=False)
    value_start: bpy.props.FloatProperty(name="Start", default=0.0)
    value_end: bpy.props.FloatProperty(name="End", default=1.0)

    @classmethod
    def poll(cls, context):
        return _poll_mesh(context) and context.mode == "EDIT_MESH"

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "mode")
        layout.prop(self, "use_typed")
        col = layout.column()
        col.enabled = self.use_typed
        col.prop(self, "value_start")
        col.prop(self, "value_end")

    def execute(self, context):
        row = self.check_row(context)
        if row is None:
            return {"CANCELLED"}
        written = 0
        for obj, bm, _idx, gi in _edit_targets(context, row):
            bm.verts.ensure_lookup_table()
            bm.verts.index_update()
            verts = [v.index for v in bm.verts if v.select and not v.hide]
            edges = [(e.verts[0].index, e.verts[1].index)
                     for e in bm.edges if e.select and not e.hide]
            chain = order_chain(verts, edges)
            if chain is None:
                continue
            if row.domain == "EDGE":
                bm.edges.ensure_lookup_table()
                bm.edges.index_update()
                by_pair = {frozenset((a, b)): i for (a, b), i in zip(
                    edges, [e.index for e in bm.edges
                            if e.select and not e.hide])}
                pairs = list(zip(chain, chain[1:]))
                closing = frozenset((chain[-1], chain[0]))
                if len(chain) > 2 and closing in by_pair:
                    pairs.append((chain[-1], chain[0]))
                targets = [by_pair[frozenset(p)] for p in pairs
                           if frozenset(p) in by_pair]
            else:
                targets = chain
            if not targets:
                continue
            if self.use_typed:
                v0, v1 = float(self.value_start), float(self.value_end)
                if TYPES[row.data_type].components > 1:
                    comps = TYPES[row.data_type].components
                    v0, v1 = (v0,) * comps, (v1,) * comps
            else:
                v0 = bm_read(bm, row, targets[0], group_index=gi)
                v1 = bm_read(bm, row, targets[-1], group_index=gi)
            values = _finalize(gradient(len(targets), v0, v1, self.mode),
                               row)
            written += bm_write_values(bm, row, targets, values,
                                       group_index=gi)
            finish_edit(obj)
        if written == 0:
            self.report({"WARNING"}, "Select a single chain of vertices")
            return {"CANCELLED"}
        _notify(context)
        return {"FINISHED"}


class IOPS_OT_AttrMath(_ToolBase, bpy.types.Operator):
    """Add, multiply, clamp, invert, remap or round the attribute on the
    selection"""
    bl_idname = "iops.attr_math"
    bl_label = "Attribute Math"
    bl_options = {"REGISTER", "UNDO"}
    TOOL = "MATH"

    op: bpy.props.EnumProperty(
        name="Operation",
        items=[("ADD", "Add", "value + A"),
               ("MULTIPLY", "Multiply", "value * A"),
               ("CLAMP", "Clamp", "clamp to A..B"),
               ("INVERT", "Invert", "1 - value (floats), not (bools)"),
               ("REMAP", "Remap", "min..max of the selection to A..B"),
               ("ROUND", "Round", "round to A decimals")],
        default="ADD")
    a: bpy.props.FloatProperty(name="A", default=1.0)
    b: bpy.props.FloatProperty(name="B", default=1.0)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "op")
        if self.op != "INVERT":
            layout.prop(self, "a")
        if self.op in {"CLAMP", "REMAP"}:
            layout.prop(self, "b")

    def execute(self, context):
        row = self.check_row(context)
        if row is None:
            return {"CANCELLED"}
        if row.data_type == "BOOLEAN" and self.op != "INVERT":
            self.report({"WARNING"}, "Booleans support Invert only")
            return {"CANCELLED"}
        n = _map_values(self, context, row,
                        lambda vals, r: math_op(vals, self.op, self.a,
                                                self.b))
        if n == 0:
            self.report({"WARNING"}, "Nothing selected")
            return {"CANCELLED"}
        _notify(context)
        return {"FINISHED"}


def _neighbours(bm, domain, idx):
    """Neighbour lists (positions within idx) for the selected elements."""
    pos = {i: k for k, i in enumerate(idx)}
    seq = _lookup(bm, domain)
    out = []
    for i in idx:
        e = seq[i]
        if domain == "POINT":
            nb = (edge.other_vert(e).index for edge in e.link_edges)
        elif domain == "EDGE":
            nb = (le.index for v in e.verts for le in v.link_edges
                  if le is not e)
        else:
            nb = (lf.index for edge in e.edges for lf in edge.link_faces
                  if lf is not e)
        out.append([pos[j] for j in nb if j in pos])
    return out


class IOPS_OT_AttrSmooth(_ToolBase, bpy.types.Operator):
    """Laplacian-smooth the attribute over the selected elements"""
    bl_idname = "iops.attr_smooth"
    bl_label = "Smooth Attribute"
    bl_options = {"REGISTER", "UNDO"}
    TOOL = "SMOOTH"

    iterations: bpy.props.IntProperty(name="Iterations", default=1, min=1,
                                      max=100)
    factor: bpy.props.FloatProperty(name="Factor", default=0.5, min=0.0,
                                    max=1.0)

    @classmethod
    def poll(cls, context):
        return _poll_mesh(context) and context.mode == "EDIT_MESH"

    def execute(self, context):
        row = self.check_row(context)
        if row is None:
            return {"CANCELLED"}
        n = 0
        for obj, bm, idx, gi in _edit_targets(context, row):
            if not idx:
                continue
            values = bm_values(bm, row, idx, group_index=gi)
            nb = _neighbours(bm, row.domain, idx)
            new = _finalize(smooth(values, nb, self.iterations, self.factor),
                            row)
            n += bm_write_values(bm, row, idx, new, group_index=gi)
            finish_edit(obj)
        if n == 0:
            self.report({"WARNING"}, "Nothing selected")
            return {"CANCELLED"}
        _notify(context)
        return {"FINISHED"}


class IOPS_OT_AttrRandomize(_ToolBase, bpy.types.Operator):
    """Fill the selection with seeded random values"""
    bl_idname = "iops.attr_randomize"
    bl_label = "Randomize Attribute"
    bl_options = {"REGISTER", "UNDO"}
    TOOL = "RANDOMIZE"

    lo: bpy.props.FloatProperty(name="Min", default=0.0)
    hi: bpy.props.FloatProperty(name="Max", default=1.0)
    seed: bpy.props.IntProperty(name="Seed", default=0)

    def execute(self, context):
        row = self.check_row(context)
        if row is None:
            return {"CANCELLED"}
        dt = "FLOAT" if row.kind == "VGROUP" else row.data_type
        n = _map_values(self, context, row,
                        lambda vals, r: randomize(len(vals), self.lo, self.hi,
                                                  self.seed, dt))
        if n == 0:
            self.report({"WARNING"}, "Nothing selected")
            return {"CANCELLED"}
        _notify(context)
        return {"FINISHED"}


class IOPS_OT_AttrCopy(_ToolBase, bpy.types.Operator):
    """Copy (or swap) values into another attribute of the same domain,
    converting between float / int / bool and vector components"""
    bl_idname = "iops.attr_copy"
    bl_label = "Copy / Swap Attribute"
    bl_options = {"REGISTER", "UNDO"}
    TOOL = "COPY"

    target_name: bpy.props.StringProperty(name="Target")
    component: bpy.props.IntProperty(name="Component", default=0, min=0,
                                     max=3)
    swap: bpy.props.BoolProperty(name="Swap", default=False)

    def draw(self, context):
        layout = self.layout
        obj = active_mesh(context)
        src = self.row(context)
        layout.prop_search(self, "target_name", obj.data, "attributes")
        if src is not None and TYPES[src.data_type].components > 1:
            layout.prop(self, "component")
        layout.prop(self, "swap")

    def execute(self, context):
        src = self.check_row(context)
        dst = resolve_row(context, self.target_name, "ATTR")
        if src is None or dst is None:
            self.report({"WARNING"}, "Pick a target attribute")
            return {"CANCELLED"}
        if dst.domain != src.domain:
            self.report({"WARNING"}, "Source and target domains differ")
            return {"CANCELLED"}
        if tool_supports("COPY", dst) is not None:
            self.report({"WARNING"}, f"Cannot convert {src.data_type} to "
                        f"{dst.data_type}")
            return {"CANCELLED"}
        st, dt = ("FLOAT" if src.kind == "VGROUP" else src.data_type,
                  dst.data_type)
        probe = coerce(default_value(st), st, dt, self.component)
        if probe is None or (self.swap and coerce(default_value(dt), dt, st,
                                                  self.component) is None):
            self.report({"WARNING"}, f"Cannot convert {st} to {dt}")
            return {"CANCELLED"}
        n = 0
        if context.mode == "EDIT_MESH":
            for obj, bm, idx, gi in _edit_targets(context, src):
                if not idx or bm_layer(bm, dst) is None:
                    continue
                a = bm_values(bm, src, idx, group_index=gi)
                b = bm_values(bm, dst, idx) if self.swap else None
                n += bm_write_values(bm, dst, idx, _finalize(
                    [coerce(v, st, dt, self.component) for v in a], dst))
                if self.swap:
                    bm_write_values(bm, src, idx, _finalize(
                        [coerce(v, dt, st, self.component) for v in b],
                        src), group_index=gi)
                finish_edit(obj)
        else:
            obj = active_mesh(context)
            me = obj.data
            a = mesh_read_all(me, src.name)
            b = mesh_read_all(me, dst.name) if self.swap else None
            if a:
                _write_values_object(me, dst.name, _finalize(
                    [coerce(v, st, dt, self.component) for v in a], dst))
                if self.swap:
                    _write_values_object(me, src.name, _finalize(
                        [coerce(v, dt, st, self.component) for v in b],
                        src))
                n = len(a)
        if n == 0:
            self.report({"WARNING"}, "Nothing to copy")
            return {"CANCELLED"}
        _notify(context)
        return {"FINISHED"}


class IOPS_OT_AttrFromVGroup(bpy.types.Operator):
    """Copy a vertex group's weights into a float attribute (non-destructive)"""
    bl_idname = "iops.attr_from_vgroup"
    bl_label = "Vertex Group to Attribute"
    bl_options = {"REGISTER", "UNDO"}

    group_name: bpy.props.StringProperty(name="Vertex Group")
    target_name: bpy.props.StringProperty(name="Attribute", default="")

    @classmethod
    def poll(cls, context):
        return _poll_mesh(context)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        obj = active_mesh(context)
        self.layout.prop_search(self, "group_name", obj, "vertex_groups")
        self.layout.prop(self, "target_name")

    def execute(self, context):
        obj = active_mesh(context)
        me = obj.data
        gi = vgroup_index(obj, self.group_name)
        if gi is None:
            self.report({"WARNING"}, "Pick a vertex group")
            return {"CANCELLED"}
        # attribute names share a namespace with vertex groups: "marks"
        # cannot be both, so the default target is "<group>.attr"
        name = self.target_name.strip() or f"{self.group_name}.attr"
        attr = me.attributes.get(name)
        if attr is None:
            attr = me.attributes.new(name, "FLOAT", "POINT")
            name = attr.name
        elif attr.domain != "POINT" or attr.data_type != "FLOAT":
            self.report({"WARNING"}, f"'{name}' is not a float point "
                        "attribute")
            return {"CANCELLED"}
        row = Row(name, "FLOAT", "POINT", "ATTR", True)
        if context.mode == "EDIT_MESH":
            bm = bmesh.from_edit_mesh(me)
            deform = bm.verts.layers.deform.verify()
            layer = bm_layer(bm, row)
            for v in bm.verts:
                v[layer] = v[deform].get(gi, 0.0)
            finish_edit(obj)
        else:
            weights = [0.0] * len(me.vertices)
            for v in me.vertices:
                for g in v.groups:
                    if g.group == gi:
                        weights[v.index] = g.weight
            _write_values_object(me, name, weights)
        _notify(context, name)
        return {"FINISHED"}


class IOPS_OT_AttrToVGroup(_RowProps, bpy.types.Operator):
    """Copy a float / int point attribute into a vertex group, weights
    clamped to 0..1 (non-destructive)"""
    bl_idname = "iops.attr_to_vgroup"
    bl_label = "Attribute to Vertex Group"
    bl_options = {"REGISTER", "UNDO"}

    group_name: bpy.props.StringProperty(name="Vertex Group", default="")

    @classmethod
    def poll(cls, context):
        return _poll_mesh(context)

    def invoke(self, context, event):
        if not self.group_name:
            self.group_name = self.row_name
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        obj = active_mesh(context)
        me = obj.data
        row = self.row(context)
        if row is None or row.kind != "ATTR" or row.domain != "POINT" \
                or row.data_type not in ("FLOAT", "INT", "INT8", "BOOLEAN"):
            self.report({"WARNING"}, "Needs a float / int / bool point "
                        "attribute")
            return {"CANCELLED"}
        name = self.group_name.strip() or row.name
        vg = obj.vertex_groups.get(name)
        if vg is None:
            vg = obj.vertex_groups.new(name=name)
            name = vg.name
        gi = vg.index
        if context.mode == "EDIT_MESH":
            bm = bmesh.from_edit_mesh(me)
            layer = bm_layer(bm, row)
            if layer is None:
                return {"CANCELLED"}
            deform = bm.verts.layers.deform.verify()
            for v in bm.verts:
                v[deform][gi] = min(max(float(v[layer]), 0.0), 1.0)
            finish_edit(obj)
        else:
            values = mesh_read_all(me, row.name)
            for i, v in enumerate(values):
                vg.add([i], min(max(float(v), 0.0), 1.0), "REPLACE")
        _notify(context)
        return {"FINISHED"}


class IOPS_OT_AttrSelectByValue(_ToolBase, bpy.types.Operator):
    """Select the elements whose attribute value matches"""
    bl_idname = "iops.attr_select_by_value"
    bl_label = "Select by Attribute Value"
    bl_options = {"REGISTER", "UNDO"}
    TOOL = "SELECT"

    op: bpy.props.EnumProperty(
        name="Condition",
        items=[("EQUAL", "Equal", ""), ("NOT_EQUAL", "Not Equal", ""),
               ("LESS", "Less Than", ""), ("GREATER", "Greater Than", ""),
               ("RANGE", "In Range", ""),
               ("ACTIVE", "Equal to Active", "")],
        default="EQUAL")
    value: bpy.props.FloatProperty(name="Value", default=0.0)
    hi: bpy.props.FloatProperty(name="Max", default=1.0)
    tol: bpy.props.FloatProperty(name="Tolerance", default=1e-4, min=0.0,
                                 precision=5)
    extend: bpy.props.BoolProperty(name="Extend", default=False)

    @classmethod
    def poll(cls, context):
        return _poll_mesh(context) and context.mode == "EDIT_MESH"

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "op")
        if self.op not in {"ACTIVE"}:
            layout.prop(self, "value")
        if self.op == "RANGE":
            layout.prop(self, "hi")
        if self.op in {"EQUAL", "NOT_EQUAL", "ACTIVE"}:
            layout.prop(self, "tol")
        layout.prop(self, "extend")

    def execute(self, context):
        row = self.check_row(context)
        if row is None:
            return {"CANCELLED"}
        if row.data_type == "BOOLEAN" and self.op not in {"EQUAL",
                                                          "NOT_EQUAL",
                                                          "ACTIVE"}:
            self.report({"WARNING"}, "Booleans support Equal / Not Equal")
            return {"CANCELLED"}
        count = 0
        for obj, bm, _idx, gi in _edit_targets(context, row):
            if self.op == "ACTIVE":
                act = bm_active_index(bm, row.domain)
                if act is None:
                    continue
                ref = bm_read(bm, row, act, group_index=gi)
                pred = select_predicate("EQUAL", ref, self.tol)
            else:
                ref = (bool(self.value) if row.data_type == "BOOLEAN"
                       else self.value)
                pred = select_predicate(self.op, ref, self.tol, self.hi)
            layer, seq = _prepare(bm, row)
            if layer is None:
                continue
            if not self.extend:
                for coll in (bm.faces, bm.edges, bm.verts):
                    for e in coll:
                        e.select = False
            for e in seq:
                if e.hide:
                    continue
                if pred(_elem_read(e, layer, row, gi)):
                    e.select = True
                    count += 1
            bm.select_flush_mode()
            finish_edit(obj)
        _notify(context)
        self.report({"INFO"}, f"{count} selected")
        return {"FINISHED"}


TOOL_CLASSES = (
    IOPS_OT_AttrGradient,
    IOPS_OT_AttrMath,
    IOPS_OT_AttrSmooth,
    IOPS_OT_AttrRandomize,
    IOPS_OT_AttrCopy,
    IOPS_OT_AttrFromVGroup,
    IOPS_OT_AttrToVGroup,
    IOPS_OT_AttrSelectByValue,
)
OPERATOR_CLASSES = OPERATOR_CLASSES + TOOL_CLASSES
