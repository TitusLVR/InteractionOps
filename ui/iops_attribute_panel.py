"""iOps Attributes panel: UIList over a WindowManager mirror, per-row value
fields that write to the selection, and the app handlers that keep both
fresh.

The mirror is UI-only state rebuilt from the mesh (attributes + vertex
groups) by the app handlers and by the operators (tag_mirror_dirty).
Panel draw() never writes RNA: it compares a read-only signature and, when
the mirror is stale, defers the rebuild to a zero-delay bpy.app.timers
callback (request_rebuild). The Python-side value cache is dirty-driven:
handlers mark it, draw() refreshes it. Every mesh read that happens
outside an operator touches the edit bmesh only while no modal operator
runs (see operators/mesh_attribute_editor.py).
"""
import time

import bpy
import bmesh
import gpu
import numpy as np
from bpy.app.handlers import persistent
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader

from ..operators import mesh_attribute_editor as mae
from .draw import (Role, draw_scope, get_theme, safe_handler_add,
                   safe_handler_remove)
from .hud import text as hud_text
from ..utils.attribute_editor_core import (
    HEATMAP_RAMP, TYPES, Row, format_value, list_rows, mixed_count,
    unique_name,
)

# Python-side state (never RNA) ---------------------------------------------
_CACHE = {"rows": {}, "dirty": True}
_LAST_DRAW = 0.0
_LAST_SIG = None
_DIRTY = True
_SYNCING = False
_UNDO_DEADLINE = 0.0
_UNDO_MESSAGE = "iOps Attribute Value"
_DRAW_GRACE = 1.0

_DOMAIN_ICON = {"POINT": "VERTEXSEL", "EDGE": "EDGESEL", "FACE": "FACESEL",
                "CORNER": "FACE_CORNER"}
_TYPE_NAMES = {"VGROUP": "Vertex Group"}
_DOMAIN_NAME = {"POINT": "Vertex", "EDGE": "Edge", "FACE": "Face",
                "CORNER": "Face Corner"}    # as in Blender's own list


def _type_name(data_type):
    """Blender's own display name for the data type (Float, Integer,
    Vector, Color, ...), never an abbreviation."""
    name = _TYPE_NAMES.get(data_type)
    if name is None:
        try:
            item = bpy.types.Attribute.bl_rna.properties["data_type"]                 .enum_items.get(data_type)
            name = item.name if item is not None else data_type.title()
        except (KeyError, AttributeError):
            name = data_type.title()
        _TYPE_NAMES[data_type] = name
    return name
_READONLY_HINT = "Edit in Object Mode (bmesh has no layer for this type)"
_NOUN = {"POINT": "vertices", "EDGE": "edges", "FACE": "faces",
         "CORNER": "faces"}
_NOUN_ONE = {"POINT": "Vertex", "EDGE": "Edge", "FACE": "Face",
             "CORNER": "Face"}


_PROP_SPLIT = 0.4           # Blender's own property-split ratio


def _split_row(layout, label, icon="NONE"):
    """Label in the left column (right-aligned, as Blender's property
    split draws it); returns the right column for the value widgets."""
    split = layout.split(factor=_PROP_SPLIT)
    left = split.row()
    left.alignment = "RIGHT"
    left.label(text=label, icon=icon)
    return split.row(align=True)


def _index_text(entry, edit):
    """Index of the element the value field belongs to: `12`, with the
    selection size when several are selected; `all (98)` in Object Mode;
    `none` when nothing is selected."""
    n = entry.get("selected", 0)
    if not edit:
        return f"all  ({n})"
    index = entry.get("index")
    if index is None or n == 0:
        return "none"
    text = str(index)
    if n > 1:
        text += f"  ({n} selected)"
    return text


def _modal_running(context):
    return mae.modal_running(context)


def _redraw_views():
    wm = bpy.context.window_manager
    if wm is None:
        return
    for win in wm.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


# ---------------------------------------------------------------------------
# Mirror
# ---------------------------------------------------------------------------
def _row_of(item):
    return Row(item.name, item.data_type, item.domain, item.kind,
               item.editable)


def active_row(context):
    st = context.window_manager.iops_attr
    if 0 <= st.index < len(st.mirror):
        return _row_of(st.mirror[st.index])
    return None


def _signature(context, obj):
    st = context.window_manager.iops_attr
    me = obj.data
    return (obj.name, context.mode,
            tuple((a.name, a.data_type, a.domain) for a in me.attributes),
            tuple(vg.name for vg in obj.vertex_groups),
            st.show_hidden, st.show_builtin, st.show_vgroups)


def _counts(me):
    return {"POINT": len(me.vertices), "EDGE": len(me.edges),
            "FACE": len(me.polygons), "CORNER": len(me.loops)}


def tag_mirror_dirty():
    global _DIRTY
    _DIRTY = True
    _CACHE["dirty"] = True
    try:
        rebuild_mirror(bpy.context)
    except Exception as exc:    # noqa: BLE001 - never break an operator
        print(f"IOPS attributes: mirror rebuild failed: {exc}")
    _redraw_views()


def rebuild_mirror(context, force=False):
    global _LAST_SIG, _DIRTY, _SYNCING
    if context.mode not in {"OBJECT", "EDIT_MESH"}:
        return
    st = context.window_manager.iops_attr
    obj = mae.active_mesh(context)
    if obj is None:
        if len(st.mirror):
            _SYNCING = True
            try:
                st.mirror.clear()
            finally:
                _SYNCING = False
        _LAST_SIG, _DIRTY = None, False
        return
    sig = _signature(context, obj)
    if not force and not _DIRTY and sig == _LAST_SIG:
        return
    _LAST_SIG, _DIRTY = sig, False
    me = obj.data
    rows = list_rows(
        ((a.name, a.data_type, a.domain) for a in me.attributes),
        (vg.name for vg in obj.vertex_groups),
        show_hidden=st.show_hidden, show_builtin=st.show_builtin,
        show_vgroups=st.show_vgroups,
        uv_names=tuple(uv.name for uv in me.uv_layers),
        color_names=tuple(c.name for c in me.color_attributes),
        edit_mode=(context.mode == "EDIT_MESH"))
    counts = _counts(me)
    active_name = ""
    if 0 <= st.index < len(st.mirror):
        active_name = st.mirror[st.index].name
    _SYNCING = True
    try:
        st.mirror.clear()
        new_index = -1
        for r in rows:
            it = st.mirror.add()
            it["name"] = r.name          # raw: skip the rename update
            it["_prev_name"] = r.name
            it.data_type = r.data_type
            it.domain = r.domain
            it.kind = r.kind
            it.editable = r.editable
            it.count = counts[r.domain]
            if r.name == active_name:
                new_index = len(st.mirror) - 1
        if new_index < 0:
            new_index = min(max(st.index, 0), max(0, len(st.mirror) - 1))
        st["index"] = new_index          # raw: no active sync from here
    finally:
        _SYNCING = False
    _CACHE["dirty"] = True


def _index_update(self, context):
    if _SYNCING:
        return
    row = active_row(context)
    obj = mae.active_mesh(context)
    if row is None or obj is None:
        return
    if row.kind == "VGROUP":
        vg = obj.vertex_groups.get(row.name)
        if vg is not None:
            obj.vertex_groups.active_index = vg.index
    else:
        idx = obj.data.attributes.find(row.name)
        if idx >= 0:
            obj.data.attributes.active_index = idx
    _CACHE["dirty"] = True
    sync_preview(context)


def _filter_update(self, context):
    tag_mirror_dirty()


def mirror_stale(context):
    """Read-only: does the mirror need a rebuild? Safe to call from draw."""
    obj = mae.active_mesh(context)
    if obj is None:
        return bool(len(context.window_manager.iops_attr.mirror))
    return _DIRTY or _signature(context, obj) != _LAST_SIG


def _rebuild_timer():
    tag_mirror_dirty()
    return None


def request_rebuild():
    """Deferred mirror rebuild (RNA write) from a context that must not
    write RNA, i.e. panel draw()."""
    if not bpy.app.timers.is_registered(_rebuild_timer):
        bpy.app.timers.register(_rebuild_timer, first_interval=0.0)


def _mirror_name_update(self, context):
    """Write-through rename from the UIList double-click editor."""
    if _SYNCING:
        return
    old = self.get("_prev_name", "")
    new = self.name.strip()
    if not old or not new or old == new:
        self["name"] = old
        return
    obj = mae.active_mesh(context)
    if obj is None:
        self["name"] = old
        return
    if self.kind == "VGROUP":
        vg = obj.vertex_groups.get(old)
        if vg is None:
            return
        new = unique_name(new, [g.name for g in obj.vertex_groups
                                if g.name != old])
        vg.name = new
    else:
        attr = obj.data.attributes.get(old)
        if attr is None:
            return
        new = unique_name(new, [a.name for a in obj.data.attributes
                                if a.name != old])
        attr.name = new
        if context.mode == "EDIT_MESH":
            mae.finish_edit(obj)
    self["name"] = new
    self["_prev_name"] = new
    if old in _CACHE["rows"]:
        _CACHE["rows"][new] = _CACHE["rows"].pop(old)
    _preview_renamed(old, new)
    tag_mirror_dirty()


# ---------------------------------------------------------------------------
# Value cache (active object, selected elements only)
# ---------------------------------------------------------------------------
def _editor_rows(context):
    """The value editor shows the active UIList row only."""
    act = active_row(context)
    return [act] if act is not None else []


def _panel_alive():
    return time.monotonic() - _LAST_DRAW < _DRAW_GRACE


def refresh_cache(context, force=False):
    """Refresh the per-row {value, mixed, first, selected} cache for the
    rows the editor shows. Edit Mode reads the active object's edit bmesh
    and is skipped while a modal operator runs."""
    if not force and not _CACHE["dirty"]:
        return
    obj = mae.active_mesh(context)
    if obj is None or context.mode not in {"OBJECT", "EDIT_MESH"}:
        _CACHE["rows"] = {}
        _CACHE["dirty"] = False
        return
    rows = _editor_rows(context)
    if context.mode != "EDIT_MESH":
        _CACHE["rows"] = {r.name: _object_entry(obj, r) for r in rows}
        _CACHE["dirty"] = False
        return
    if _modal_running(context):
        return                      # keep the last data, re-read later
    bm = bmesh.from_edit_mesh(obj.data)
    out = {}
    for r in rows:
        gi = mae.vgroup_index(obj, r.name) if r.kind == "VGROUP" else None
        if r.kind == "VGROUP" and gi is None:
            continue
        if mae.bm_layer(bm, r) is None:
            out[r.name] = {"value": None, "mixed": 0, "first": False,
                           "selected": 0, "index": None}
            continue
        idx = mae.bm_selected_indices(bm, r.domain)
        act = mae.bm_active_index(bm, r.domain)
        values = mae.bm_values(bm, r, idx, group_index=gi)
        if not idx:
            out[r.name] = {"value": None, "mixed": 0, "first": False,
                           "selected": 0, "index": None}
            continue
        if act is not None and act in idx:
            value, first, shown = values[idx.index(act)], False, act
        else:
            value, first, shown = values[0], True, idx[0]
        out[r.name] = {"value": value, "mixed": mixed_count(values),
                       "first": first, "selected": len(idx), "index": shown}
    _CACHE["rows"] = out
    _CACHE["dirty"] = False


def _object_entry(obj, row):
    """Object Mode: the first element's value and how many distinct
    values the whole mesh holds (numpy, no Python loop)."""
    empty = {"value": None, "mixed": 0, "first": False, "selected": 0,
             "index": None}
    snap = mae.snapshot(obj, row.name, row.domain, kind=row.kind)
    if snap is None:
        return empty
    vals = snap[1]
    n = len(vals)
    if n == 0:
        return empty
    data_type = "FLOAT" if row.kind == "VGROUP" else row.data_type
    first = vals[0]
    if data_type == "STRING":
        value = str(first)
        mixed = len(set(vals.tolist()))
    else:
        arr = np.asarray(vals)
        if arr.dtype.kind == "f":
            key = np.round(arr, 6)
        else:
            key = arr
        mixed = len(np.unique(key, axis=0)) if key.ndim > 1 \
            else len(np.unique(key))
        if data_type == "BOOLEAN":
            value = bool(first)
        elif data_type in ("INT", "INT8"):
            value = int(first)
        elif arr.ndim > 1:
            value = tuple(float(c) for c in first)
        else:
            value = float(first)
    return {"value": value, "mixed": int(mixed), "first": True,
            "selected": n, "index": None}


def _invalidate_cache():
    _CACHE["dirty"] = True


# ---------------------------------------------------------------------------
# Value fields: getters read the cache, setters write the selection
# ---------------------------------------------------------------------------
def _cached(item):
    return _CACHE["rows"].get(item.name, {}).get("value")


def _apply(item, value):
    context = bpy.context
    row = mae.resolve_row(context, item.name, item.kind)
    if row is None or not row.editable:
        return
    if mae.apply_value(context, row, value) == 0:
        return
    entry = _CACHE["rows"].setdefault(
        item.name, {"value": None, "mixed": 0, "first": False, "selected": 0})
    entry["value"] = value
    entry["mixed"] = 1
    _schedule_undo_push()
    _preview_invalidate()
    _redraw_views()


def _get_float(self):
    v = _cached(self)
    return float(v) if isinstance(v, (int, float)) else 0.0


def _set_float(self, value):
    _apply(self, float(value))


def _get_int(self):
    v = _cached(self)
    return int(v) if isinstance(v, (int, float)) else 0


def _set_int(self, value):
    _apply(self, int(value))


def _get_bool(self):
    return bool(_cached(self))


def _set_bool(self, value):
    _apply(self, bool(value))


def _get_vec(self, n):
    v = _cached(self)
    try:
        vals = [float(c) for c in v][:n]
    except TypeError:
        vals = []
    vals += [0.0] * (n - len(vals))
    return vals


def _get_vector(self):
    return _get_vec(self, 3)


def _set_vector(self, value):
    comps = TYPES.get(self.data_type, TYPES["FLOAT_VECTOR"]).components
    _apply(self, tuple(float(c) for c in value)[:comps])


def _get_color(self):
    v = _cached(self)
    vals = _get_vec(self, 4)
    if v is None or len(v) < 4:
        vals[3] = 1.0
    return vals


def _set_color(self, value):
    _apply(self, tuple(float(c) for c in value))


def _get_string(self):
    v = _cached(self)
    return v if isinstance(v, str) else ""


def _set_string(self, value):
    _apply(self, str(value))


def _undo_push_now():
    """bpy.app.timers callback: push once the last tick is 0.3 s old."""
    remaining = _UNDO_DEADLINE - time.monotonic()
    if remaining > 0.0:
        return remaining
    try:
        wm = bpy.context.window_manager
        win = wm.windows[0] if wm is not None and len(wm.windows) else None
        if win is not None:
            area = next((a for a in win.screen.areas if a.type == "VIEW_3D"),
                        None)
            override = {"window": win, "screen": win.screen}
            if area is not None:
                override["area"] = area
                region = next((r for r in area.regions
                               if r.type == "WINDOW"), None)
                if region is not None:
                    override["region"] = region
            with bpy.context.temp_override(**override):
                bpy.ops.ed.undo_push(message=_UNDO_MESSAGE)
        else:
            bpy.ops.ed.undo_push(message=_UNDO_MESSAGE)
    except RuntimeError as exc:
        print(f"IOPS attributes: undo push failed: {exc}")
    return None


def _schedule_undo_push(delay=0.3):
    global _UNDO_DEADLINE
    _UNDO_DEADLINE = time.monotonic() + delay
    if not bpy.app.timers.is_registered(_undo_push_now):
        bpy.app.timers.register(_undo_push_now, first_interval=delay)


# ---------------------------------------------------------------------------
# Viewport preview — follows the active UIList row while the `preview`
# toggle is on (default). Handlers collect CPU arrays (never from a draw
# callback, never while a modal runs); the POST_VIEW callback draws the
# fill batch, the POST_PIXEL callback the labels.  Nothing is drawn in the
# viewport corners: the heatmap range and the too-many note live in the
# Preview Settings sub-panel.
# The draw handlers live from register to unregister and return at once
# while there is nothing to show.
# ---------------------------------------------------------------------------
_PREVIEW = {"row": None, "handle_view": None, "handle_pixel": None,
            "geom": None, "batch": None, "dirty": True,
            "range": (0.0, 1.0), "too_many": False, "legend": ""}
_FILL_SHADER = None
_BG_SHADER = None
_LABEL_PAD = 3
_LABEL_BG = (0.0, 0.0, 0.0, 0.55)
_DEPTH_SHRINK = 0.005      # same trick as the non-planar overlay
_COLOUR_TYPES = {"FLOAT_COLOR", "BYTE_COLOR"}
_FILL_ALPHA = {"POINT": 1.0, "EDGE": 0.9, "FACE": 0.55, "CORNER": 0.55}


def _get_fill_shader():
    global _FILL_SHADER
    if _FILL_SHADER is None:
        info = gpu.types.GPUShaderCreateInfo()
        info.vertex_in(0, "VEC3", "pos")
        info.vertex_in(1, "VEC4", "color")
        iface = gpu.types.GPUStageInterfaceInfo("iops_attr_iface")
        iface.smooth("VEC4", "fcol")
        info.vertex_out(iface)
        info.fragment_out(0, "VEC4", "fragColor")
        info.push_constant("MAT4", "viewMat")
        info.push_constant("MAT4", "projMat")
        info.push_constant("FLOAT", "depthShrink")
        info.vertex_source(
            "void main() {\n"
            "  vec4 vp = viewMat * vec4(pos, 1.0);\n"
            "  vp.xyz *= (1.0 - depthShrink);\n"
            "  gl_Position = projMat * vp;\n"
            "  fcol = color;\n"
            "}\n")
        info.fragment_source("void main() { fragColor = fcol; }\n")
        _FILL_SHADER = gpu.shader.create_from_info(info)
    return _FILL_SHADER


def preview_on():
    """Something is being previewed (toggle on and an active row)."""
    return _PREVIEW["row"] is not None


def _preview_wanted():
    st = getattr(bpy.context.window_manager, "iops_attr", None)
    return st is not None and st.preview


def sync_preview(context, *, collect=False):
    """Point the preview at the active UIList row (nothing when the toggle
    is off) and refresh its arrays when the target changed, when `collect`
    asks for it (mesh data changed) or when settings marked it dirty."""
    st = context.window_manager.iops_attr
    row = active_row(context) if st.preview else None
    if row != _PREVIEW["row"]:
        if row is None:
            disable_preview()
            return
        _PREVIEW["row"] = row
        _PREVIEW["dirty"] = True
    if row is not None and (collect or _PREVIEW["dirty"]):
        if _modal_running(context):
            # Box / circle / lasso select: the depsgraph event fires while
            # the modal operator is still listed and no second event follows
            # once it ends, so collect from a timer after the modal is gone.
            _PREVIEW["dirty"] = True
            if not bpy.app.timers.is_registered(_deferred_collect):
                bpy.app.timers.register(_deferred_collect,
                                        first_interval=0.05)
            return
        preview_collect(context)


def _deferred_collect():
    """bpy.app.timers callback: collect once no modal operator runs."""
    context = bpy.context
    if _PREVIEW["row"] is None or not _PREVIEW["dirty"]:
        return None
    if _modal_running(context):
        return 0.05
    try:
        preview_collect(context)
    except Exception as exc:    # noqa: BLE001
        print(f"IOPS attributes: deferred preview collect failed: {exc}")
        _PREVIEW["dirty"] = False
    return None


def preview_row_name():
    row = _PREVIEW["row"]
    return row.name if row is not None else None


def _preview_invalidate():
    _PREVIEW["dirty"] = True


def _preview_renamed(old, new):
    row = _PREVIEW["row"]
    if row is not None and row.name == old:
        _PREVIEW["row"] = row._replace(name=new)


def _max_labels():
    try:
        return int(bpy.context.preferences.addons["InteractionOps"]
                   .preferences.attr_preview_max_labels)
    except (KeyError, AttributeError):
        return 2000


def _scalars(vals, data_type):
    if data_type in _COLOUR_TYPES:
        v = np.asarray(vals, np.float32).reshape(len(vals), 4)
        return v[:, 0] * 0.2126 + v[:, 1] * 0.7152 + v[:, 2] * 0.0722
    if data_type == "STRING":
        return np.zeros(len(vals), np.float32)
    v = np.asarray(vals)
    if v.ndim > 1:
        return np.sqrt((v.astype(np.float32) ** 2).sum(axis=1))
    return v.astype(np.float32)


def _ramp_colors(t):
    """Vectorised HEATMAP_RAMP lookup, t in [0, 1] → (n, 3)."""
    ramp = np.asarray(HEATMAP_RAMP, np.float32)
    xs = np.linspace(0.0, 1.0, len(ramp))
    t = np.clip(np.asarray(t, np.float32), 0.0, 1.0)
    return np.stack([np.interp(t, xs, ramp[:, c]) for c in range(3)],
                    axis=1).astype(np.float32)


def _colors(vals, scalar, lo, hi, mode, data_type, alpha):
    n = len(scalar)
    if mode == "COLOUR" and data_type in _COLOUR_TYPES:
        rgb = np.asarray(vals, np.float32).reshape(n, 4)[:, :3]
    elif mode == "GREYSCALE" and data_type in _COLOUR_TYPES:
        rgb = np.repeat(np.asarray(scalar, np.float32).reshape(n, 1), 3,
                        axis=1)
    else:
        if hi - lo <= 1e-12:
            t = np.full(n, 0.5, np.float32)
        else:
            t = (scalar - lo) / (hi - lo)
        rgb = _ramp_colors(t)
    out = np.empty((n, 4), np.float32)
    out[:, :3] = np.clip(rgb, 0.0, 1.0)
    out[:, 3] = alpha
    return out


def _py_value(v, data_type):
    if data_type == "BOOLEAN":
        return bool(v)
    if data_type in ("INT", "INT8"):
        return int(v)
    if data_type == "STRING":
        return str(v)
    try:
        return tuple(float(c) for c in v)
    except TypeError:
        return float(v)


def _topology(obj):
    """World vertex positions and fill topology: (vpos, edges, loop_vert,
    loop_face, tri_loops)."""
    mw = np.asarray(obj.matrix_world, np.float32)
    if obj.mode == "EDIT" and obj.data.is_editmode:
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.verts.index_update()
        bm.edges.index_update()
        bm.faces.index_update()
        vpos = np.array([tuple(v.co) for v in bm.verts], np.float32) \
            if len(bm.verts) else np.zeros((0, 3), np.float32)
        edges = np.array([(e.verts[0].index, e.verts[1].index)
                          for e in bm.edges], np.int32).reshape(-1, 2)
        loop_vert, loop_face, loop_index = [], [], {}
        for f in bm.faces:
            for lo in f.loops:
                loop_index[lo] = len(loop_vert)
                loop_vert.append(lo.vert.index)
                loop_face.append(f.index)
        tris = np.array([[loop_index[lo] for lo in loops]
                         for loops in bm.calc_loop_triangles()],
                        np.int32).reshape(-1, 3)
        loop_vert = np.asarray(loop_vert, np.int32)
        loop_face = np.asarray(loop_face, np.int32)
    else:
        me = obj.data
        nv, ne, nl = len(me.vertices), len(me.edges), len(me.loops)
        vpos = np.empty(nv * 3, np.float32)
        me.vertices.foreach_get("co", vpos)
        vpos = vpos.reshape(nv, 3)
        edges = np.empty(ne * 2, np.int32)
        me.edges.foreach_get("vertices", edges)
        edges = edges.reshape(ne, 2)
        loop_vert = np.empty(nl, np.int32)
        me.loops.foreach_get("vertex_index", loop_vert)
        nf = len(me.polygons)
        lt = np.empty(nf, np.int32)
        me.polygons.foreach_get("loop_total", lt)
        loop_face = np.repeat(np.arange(nf, dtype=np.int32), lt)
        nt = len(me.loop_triangles)
        tris = np.empty(nt * 3, np.int32)
        me.loop_triangles.foreach_get("loops", tris)
        tris = tris.reshape(nt, 3)
    vpos = vpos @ mw[:3, :3].T + mw[:3, 3]
    return vpos, edges, loop_vert, loop_face, tris


def _fill_geometry(obj, domain, pos, colors, visible):
    """(primitive, positions (m,3), colours (m,4)) for the fill batch."""
    if domain == "POINT":
        return ("POINTS", pos[visible], colors[visible])
    vpos, edges, loop_vert, loop_face, tris = _topology(obj)
    if domain == "EDGE":
        e = edges[visible]
        p = vpos[e.reshape(-1)]
        c = np.repeat(colors[visible], 2, axis=0)
        return ("LINES", p, c)
    tri_face = loop_face[tris[:, 0]] if len(tris) else np.zeros(0, np.int32)
    if domain == "FACE":
        keep = visible[tri_face] if len(tris) else np.zeros(0, bool)
        t = tris[keep]
        p = vpos[loop_vert[t.reshape(-1)]]
        c = np.repeat(colors[tri_face[keep]], 3, axis=0)
        return ("TRIS", p, c)
    keep = visible[tris[:, 0]] if len(tris) else np.zeros(0, bool)
    t = tris[keep]
    p = vpos[loop_vert[t.reshape(-1)]]
    c = colors[t.reshape(-1)]
    return ("TRIS", p, c)


def preview_collect(context):
    """Handler-side: rebuild the CPU arrays for the previewed row."""
    row = _PREVIEW["row"]
    if row is None:
        return
    obj = mae.active_mesh(context)
    if obj is None or context.mode not in {"OBJECT", "EDIT_MESH"}:
        disable_preview()
        return
    if context.mode == "EDIT_MESH" and _modal_running(context):
        return
    snap = mae.snapshot(obj, row.name, row.domain, kind=row.kind)
    if snap is None:
        disable_preview()
        return
    pos, vals, sel, hid = snap
    st = context.window_manager.iops_attr
    data_type = "FLOAT" if row.kind == "VGROUP" else row.data_type
    visible = ~hid
    if st.preview_selected_only and context.mode == "EDIT_MESH":
        visible &= sel
    scalar = _scalars(vals, data_type)
    if visible.any():
        lo, hi = float(scalar[visible].min()), float(scalar[visible].max())
    else:
        lo, hi = 0.0, 1.0
    fill_mode = _fill_mode(st, data_type)
    colors = _colors(vals, scalar, lo, hi, fill_mode or "HEATMAP",
                     data_type, _FILL_ALPHA[row.domain])
    too_many = int(visible.sum()) > _max_labels()
    labels = None
    if st.preview_labels and not too_many:
        labels = [format_value(_py_value(v, data_type), data_type,
                               st.preview_decimals) for v in vals]
        labels = [lb for lb, keep in zip(labels, visible) if keep]
    fill = None
    if fill_mode is not None:
        fill = _fill_geometry(obj, row.domain, pos, colors, visible)
    _PREVIEW["geom"] = {
        "domain": row.domain, "fill_mode": fill_mode,
        "labels_on": bool(st.preview_labels),
        "pos": pos[visible], "sel": sel[visible], "colors": colors,
        "scalar": scalar, "labels": labels, "fill": fill,
    }
    _PREVIEW["range"] = (lo, hi)
    _PREVIEW["too_many"] = too_many
    _PREVIEW["legend"] = (
        f"{row.name}: {format_value(lo, 'FLOAT', st.preview_decimals)} … "
        f"{format_value(hi, 'FLOAT', st.preview_decimals)}")
    _PREVIEW["batch"] = None
    _PREVIEW["dirty"] = False
    _redraw_views()


def _fill_mode(st, data_type):
    """Which fill the checkboxes ask for: the fills are exclusive, so
    Heatmap wins over Colour over Greyscale. Colour / Greyscale only
    apply to colour attributes (their checkboxes are disabled otherwise)."""
    if st.preview_heatmap:
        return "HEATMAP"
    if data_type in _COLOUR_TYPES:
        if st.preview_colour:
            return "COLOUR"
        if st.preview_greyscale:
            return "GREYSCALE"
    return None


def _overlays_hidden(context):
    space = context.space_data
    return space is not None and hasattr(space, "overlay") \
        and not space.overlay.show_overlays


def _draw_view():
    geom = _PREVIEW["geom"]
    if geom is None or geom["fill"] is None:
        return
    context = bpy.context
    if _overlays_hidden(context):
        return
    kind, pos, col = geom["fill"]
    if len(pos) == 0:
        return
    shader = _get_fill_shader()
    if _PREVIEW["batch"] is None:
        _PREVIEW["batch"] = batch_for_shader(
            shader, kind, {"pos": pos.tolist(), "color": col.tolist()})
    rv3d = context.region_data
    if rv3d is None:
        return
    shader.bind()
    shader.uniform_float("viewMat", rv3d.view_matrix)
    shader.uniform_float("projMat", rv3d.window_matrix)
    shader.uniform_float("depthShrink", _DEPTH_SHRINK)
    with draw_scope(blend="ALPHA", depth="LESS_EQUAL", line_width=2.0,
                    point_size=8.0):
        _PREVIEW["batch"].draw(shader)


def _clipped(rv3d, p):
    if not rv3d.use_clip_planes:
        return False
    for plane in rv3d.clip_planes:
        if plane[0] * p[0] + plane[1] * p[1] + plane[2] * p[2] + plane[3] < 0:
            return True
    return False


def _draw_pixel():
    geom = _PREVIEW["geom"]
    if geom is None:
        return
    context = bpy.context
    if _overlays_hidden(context):
        return
    region, rv3d = context.region, context.region_data
    if region is None or rv3d is None:
        return
    theme = get_theme(context)
    st = context.window_manager.iops_attr
    size = st.preview_text_size
    labels = geom["labels"]
    if labels is not None:
        pos, sel = geom["pos"], geom["sel"]
        placed = []
        rects = []
        for i, text in enumerate(labels):
            p = pos[i]
            if _clipped(rv3d, p):
                continue
            xy = view3d_utils.location_3d_to_region_2d(region, rv3d, p)
            if xy is None:
                continue
            x, y = int(xy[0]) + 4, int(xy[1]) + 4
            w, h = hud_text.measure(text, theme=theme, size_px=size)
            placed.append((text, x, y, bool(sel[i])))
            rects.append((x - _LABEL_PAD, y - _LABEL_PAD,
                          x + w + _LABEL_PAD, y + h + _LABEL_PAD))
        _draw_label_backgrounds(rects)
        for text, x, y, active in placed:
            role = Role.ACTIVE_POINT if active else Role.HUD_LABEL
            hud_text.draw(text, x, y, theme=theme, role=role, size_px=size)


def _draw_label_backgrounds(rects):
    """One batch of translucent boxes behind the labels (readability)."""
    global _BG_SHADER
    n = len(rects)
    if n == 0:
        return
    if _BG_SHADER is None:
        _BG_SHADER = gpu.shader.from_builtin("UNIFORM_COLOR")
    r = np.asarray(rects, dtype=np.float32)
    quad = np.empty((n, 4, 2), dtype=np.float32)
    quad[:, 0] = r[:, [0, 1]]
    quad[:, 1] = r[:, [2, 1]]
    quad[:, 2] = r[:, [2, 3]]
    quad[:, 3] = r[:, [0, 3]]
    tris = (np.arange(n, dtype=np.int32)[:, None, None] * 4
            + np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int32)[None])
    batch = batch_for_shader(_BG_SHADER, "TRIS",
                             {"pos": quad.reshape(-1, 2).tolist()},
                             indices=tris.reshape(-1, 3).tolist())
    _BG_SHADER.bind()
    _BG_SHADER.uniform_float("color", _LABEL_BG)
    with draw_scope(blend="ALPHA"):
        batch.draw(_BG_SHADER)


def _install_preview_handlers():
    if _PREVIEW["handle_view"] is not None:
        return
    try:
        _PREVIEW["handle_view"] = safe_handler_add(
            bpy.types.SpaceView3D, _draw_view, (), "WINDOW", "POST_VIEW")
        _PREVIEW["handle_pixel"] = safe_handler_add(
            bpy.types.SpaceView3D, _draw_pixel, (), "WINDOW", "POST_PIXEL")
    except Exception as exc:    # noqa: BLE001 - no GPU (background)
        print(f"IOPS attributes: preview handlers unavailable: {exc}")


def _remove_preview_handlers():
    for key in ("handle_view", "handle_pixel"):
        if _PREVIEW[key] is not None:
            safe_handler_remove(_PREVIEW[key], bpy.types.SpaceView3D,
                                "WINDOW")
            _PREVIEW[key] = None


def disable_preview():
    """Drop the previewed row and its arrays; the handlers stay installed
    and draw nothing. `sync_preview` picks the active row up again while
    the toggle is on."""
    _PREVIEW.update(row=None, geom=None, batch=None, dirty=True,
                    range=(0.0, 1.0), too_many=False, legend="")
    _redraw_views()


def _preview_toggle_update(self, context):
    sync_preview(context)


def _preview_settings_update(self, context):
    _PREVIEW["dirty"] = True
    if preview_on() and not _modal_running(context):
        preview_collect(context)


class IOPS_PT_attributes_preview(bpy.types.Panel):
    bl_label = "Preview Settings"
    bl_idname = "IOPS_PT_attributes_preview"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "iOps"
    bl_parent_id = "IOPS_PT_attributes_panel"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        st = context.window_manager.iops_attr
        layout.active = st.preview
        act = active_row(context)
        colour = act is not None and act.data_type in _COLOUR_TYPES
        col = layout.column(heading="Show", align=True)
        col.prop(st, "preview_labels")
        col.prop(st, "preview_heatmap")
        sub = col.column(align=True)
        sub.enabled = colour            # colour attributes only
        sub.prop(st, "preview_colour")
        sub.prop(st, "preview_greyscale")
        sel_row = layout.row()
        sel_row.enabled = context.mode == "EDIT_MESH"   # Object Mode: all
        sel_row.prop(st, "preview_selected_only")
        layout.prop(st, "preview_decimals")
        layout.prop(st, "preview_text_size")
        geom = _PREVIEW["geom"]
        if geom is not None and geom["fill_mode"] == "HEATMAP":
            lo, hi = _PREVIEW["range"]
            _split_row(layout, "Range").label(
                text=f"{format_value(lo, 'FLOAT', st.preview_decimals)} … "
                     f"{format_value(hi, 'FLOAT', st.preview_decimals)}")
        if _PREVIEW["too_many"]:
            layout.label(text=f"Too many elements for labels "
                              f"(> {_max_labels()})", icon="ERROR")
        try:
            prefs = context.preferences.addons["InteractionOps"].preferences
            layout.prop(prefs, "attr_preview_max_labels")
        except KeyError:
            pass


# ---------------------------------------------------------------------------
# Property groups
# ---------------------------------------------------------------------------
class IOPS_AttrMirrorItem(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty(update=_mirror_name_update)
    data_type: bpy.props.StringProperty()
    domain: bpy.props.StringProperty()
    kind: bpy.props.StringProperty(default="ATTR")
    editable: bpy.props.BoolProperty(default=True)
    count: bpy.props.IntProperty()
    value_float: bpy.props.FloatProperty(
        name="Value", precision=3, get=_get_float, set=_set_float)
    value_int: bpy.props.IntProperty(
        name="Value", get=_get_int, set=_set_int)
    value_bool: bpy.props.BoolProperty(
        name="Value", get=_get_bool, set=_set_bool)
    value_vector: bpy.props.FloatVectorProperty(
        name="Value", size=3, precision=3, get=_get_vector, set=_set_vector)
    value_color: bpy.props.FloatVectorProperty(
        name="Value", size=4, subtype="COLOR", min=0.0, max=1.0,
        get=_get_color, set=_set_color)
    value_string: bpy.props.StringProperty(
        name="Value", get=_get_string, set=_set_string)


class IOPS_AttrState(bpy.types.PropertyGroup):
    mirror: bpy.props.CollectionProperty(type=IOPS_AttrMirrorItem)
    index: bpy.props.IntProperty(default=0, update=_index_update)
    show_hidden: bpy.props.BoolProperty(
        name="Hidden", description="Show attributes whose name starts "
        "with a dot", default=False, update=_filter_update)
    show_builtin: bpy.props.BoolProperty(
        name="Built-in", description="Show position, crease, bevel weight, "
        "sharp, material index, UV maps and colour attributes",
        default=False, update=_filter_update)
    show_vgroups: bpy.props.BoolProperty(
        name="Vertex Groups", description="List vertex groups as rows",
        default=True, update=_filter_update)
    preview: bpy.props.BoolProperty(
        name="Preview", description="Draw the active attribute in the "
        "viewport (labels, greyscale, colour or heatmap, see the Preview "
        "sub-panel)", default=True, update=_preview_toggle_update)
    preview_labels: bpy.props.BoolProperty(
        name="Labels", description="Value as text next to each element",
        default=True, update=_preview_settings_update)
    preview_heatmap: bpy.props.BoolProperty(
        name="Heatmap", description="Value through a blue-to-red ramp "
        "from the mesh minimum to its maximum",
        default=False, update=_preview_settings_update)
    preview_colour: bpy.props.BoolProperty(
        name="Colour", description="Colour attribute as stored (fills "
        "are exclusive: Heatmap wins, then Colour, then Greyscale). "
        "Colour attributes only",
        default=False, update=_preview_settings_update)
    preview_greyscale: bpy.props.BoolProperty(
        name="Greyscale", description="Colour attribute as luminance. "
        "Colour attributes only",
        default=False, update=_preview_settings_update)
    preview_selected_only: bpy.props.BoolProperty(
        name="Selected Only",
        description="In Edit Mode preview only the selected elements; "
        "the heatmap range is taken over the selection too",
        default=False, update=_preview_settings_update)
    preview_decimals: bpy.props.IntProperty(
        name="Decimals", default=2, min=0, max=6,
        update=_preview_settings_update)
    preview_text_size: bpy.props.IntProperty(
        name="Text Size", description="Label size in pixels",
        default=13, min=8, max=48, subtype="PIXEL")


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
def _value_prop(data_type):
    w = TYPES[data_type].widget
    return {"FLOAT": "value_float", "INT": "value_int", "BOOL": "value_bool",
            "VECTOR": "value_vector", "COLOR": "value_color",
            "STRING": "value_string"}.get(w)


class IOPS_UL_Attributes(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname):
        row = layout.row(align=True)
        name_row = row.row(align=True)
        name_row.enabled = item.editable or item.kind == "VGROUP"
        name_row.prop(item, "name", text="", emboss=False,
                      icon=_DOMAIN_ICON.get(item.domain, "DOT"))
        right = row.row(align=True)
        right.alignment = "RIGHT"
        right.active = False            # dimmed like the native list
        tag = f"{_DOMAIN_NAME.get(item.domain, '')} - "               f"{_type_name(item.data_type)}"
        if not item.editable and item.kind == "ATTR":
            right.label(text=tag, icon="LOCKED")
        else:
            right.label(text=tag)
        if context.mode == "OBJECT":
            right.label(text=str(item.count))


class IOPS_MT_attr_specials(bpy.types.Menu):
    bl_idname = "IOPS_MT_attr_specials"
    bl_label = "Attribute Tools"

    def draw(self, context):
        layout = self.layout
        row = active_row(context)
        if row is None:
            layout.label(text="No active attribute")
            return
        edit = context.mode == "EDIT_MESH"
        col = layout.column()
        col.enabled = row.editable
        op = col.operator("iops.attr_fill",
                          text="Set on Selection..." if edit else "Set All...")
        op.row_name, op.row_kind, op.reset = row.name, row.kind, False
        op = col.operator("iops.attr_fill",
                          text="Reset on Selection" if edit else "Reset All")
        op.row_name, op.row_kind, op.reset = row.name, row.kind, True
        layout.separator()
        sub = layout.column()
        sub.enabled = row.kind == "ATTR" and not edit
        op = sub.operator("iops.attr_convert", text="Convert Type / Domain...")
        op.row_name, op.row_kind = row.name, row.kind
        draw_tools_menu(layout, context, row)


_TOOL_ITEMS = (
    ("GRADIENT", "iops.attr_gradient", "Gradient on Chain...", True),
    ("MATH", "iops.attr_math", "Math...", False),
    ("SMOOTH", "iops.attr_smooth", "Smooth...", True),
    ("RANDOMIZE", "iops.attr_randomize", "Randomize...", False),
    ("COPY", "iops.attr_copy", "Copy / Swap...", False),
    ("SELECT", "iops.attr_select_by_value", "Select by Value...", True),
)


def draw_tools_menu(layout, context, row):
    edit = context.mode == "EDIT_MESH"
    layout.separator()
    for tool, idname, text, edit_only in _TOOL_ITEMS:
        reason = mae.tool_supports(tool, row)
        if reason is None and edit_only and not edit:
            reason = "Edit Mode only"
        sub = layout.row()
        sub.enabled = reason is None
        op = sub.operator(idname, text=text)
        op.row_name, op.row_kind = row.name, row.kind
    layout.separator()
    op = layout.operator("iops.attr_from_vgroup", text="Vertex Group to Attribute...")
    if row.kind == "VGROUP":
        op.group_name = row.name
    sub = layout.row()
    sub.enabled = (row.kind == "ATTR" and row.domain == "POINT"
                   and row.data_type in {"FLOAT", "INT", "INT8", "BOOLEAN"})
    op = sub.operator("iops.attr_to_vgroup", text="Attribute to Vertex Group...")
    op.row_name, op.row_kind = row.name, row.kind


class IOPS_PT_attributes_panel(bpy.types.Panel):
    bl_label = "iOps Attributes"
    bl_idname = "IOPS_PT_attributes_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "iOps"

    @classmethod
    def poll(cls, context):
        return (context.mode in {"OBJECT", "EDIT_MESH"}
                and mae.active_mesh(context) is not None)

    def draw(self, context):
        global _LAST_DRAW
        _LAST_DRAW = time.monotonic()
        layout = self.layout
        st = context.window_manager.iops_attr
        try:
            if mirror_stale(context):
                request_rebuild()           # RNA write deferred to a timer
            elif not _modal_running(context):
                refresh_cache(context)      # Python cache only, dirty-driven
                sync_preview(context)       # follows the active row
        except Exception as exc:    # noqa: BLE001 - keep the panel drawing
            layout.label(text=f"Attribute read failed: {exc}", icon="ERROR")

        outer = layout.box()
        frow = outer.row(align=True)
        frow.prop(st, "show_hidden", toggle=True)
        frow.prop(st, "show_builtin", toggle=True)
        frow.prop(st, "show_vgroups", toggle=True)

        act = active_row(context)
        row = outer.row()
        row.template_list("IOPS_UL_Attributes", "", st, "mirror", st,
                          "index", rows=5)
        col = row.column(align=True)
        col.operator("iops.attr_new", text="", icon="ADD")
        sub = col.column(align=True)
        sub.enabled = act is not None
        if act is not None:
            op = sub.operator("iops.attr_remove", text="", icon="REMOVE")
            op.row_name, op.row_kind = act.name, act.kind
            op = sub.operator("iops.attr_duplicate", text="",
                              icon="DUPLICATE")
            op.row_name, op.row_kind = act.name, act.kind
        else:
            sub.operator("iops.attr_remove", text="", icon="REMOVE")
            sub.operator("iops.attr_duplicate", text="", icon="DUPLICATE")
        col.separator()
        col.operator("iops.attr_refresh", text="", icon="FILE_REFRESH")
        col.menu("IOPS_MT_attr_specials", text="", icon="DOWNARROW_HLT")

        self._draw_editor(context, outer.box(), st, act)
        layout.prop(st, "preview", text="Preview", toggle=True,
                    icon="HIDE_OFF" if st.preview else "HIDE_ON")

    def _draw_editor(self, context, layout, st, act):
        if act is None:
            layout.label(text="No active attribute")
            return
        edit = context.mode == "EDIT_MESH"
        item = st.mirror[st.index]
        entry = _CACHE["rows"].get(act.name, {})
        info = _split_row(layout, "Type")
        info.label(text=_NOUN_ONE[act.domain],
                   icon=_DOMAIN_ICON.get(act.domain, "DOT"))
        info.label(text=f"Index  {_index_text(entry, edit)}")
        prop = _value_prop(act.data_type)
        line = _split_row(layout, act.name,
                          icon="LOCKED" if not act.editable else "NONE")
        field = line.row(align=True)
        if prop is None:
            field.label(text="read-only")
            return
        selected = entry.get("selected", 0)
        field.enabled = bool(act.editable) and (not edit or selected > 0)
        field.prop(item, prop, text="")


# ---------------------------------------------------------------------------
# Handlers and registration
# ---------------------------------------------------------------------------
@persistent
def _resync(*_args):
    global _DIRTY
    ctx = bpy.context
    if ctx.window_manager is None or not hasattr(ctx.window_manager,
                                                 "iops_attr"):
        return
    if not (_panel_alive() or _preview_wanted() or _DIRTY):
        return
    try:
        if ctx.mode not in {"OBJECT", "EDIT_MESH"} \
                or mae.active_mesh(ctx) is None:
            rebuild_mirror(ctx)     # clears the list; nothing else to do
            if preview_on():
                disable_preview()
            _DIRTY = False
            return
        rebuild_mirror(ctx)
        _CACHE["dirty"] = True
        if _panel_alive() and not _modal_running(ctx):
            refresh_cache(ctx)
        sync_preview(ctx, collect=True)
    except Exception as exc:    # noqa: BLE001
        print(f"IOPS attributes: resync failed: {exc}")


@persistent
def _force_resync(*_args):
    global _DIRTY
    _DIRTY = True
    _CACHE["dirty"] = True
    _resync()


_HANDLERS = (
    (bpy.app.handlers.depsgraph_update_post, _resync),
    (bpy.app.handlers.undo_post, _force_resync),
    (bpy.app.handlers.redo_post, _force_resync),
    (bpy.app.handlers.load_post, _force_resync),
)

UI_CLASSES = (
    IOPS_AttrMirrorItem,     # CollectionProperty target first
    IOPS_AttrState,          # PointerProperty target before the panel
    IOPS_UL_Attributes,
    IOPS_MT_attr_specials,
    IOPS_PT_attributes_panel,
    IOPS_PT_attributes_preview,
)


def register_attribute_ui():
    bpy.types.WindowManager.iops_attr = bpy.props.PointerProperty(
        type=IOPS_AttrState)
    mae._tag_mirror_dirty = tag_mirror_dirty
    mae._rebuild_mirror_now = lambda context: rebuild_mirror(context,
                                                             force=True)
    mae._set_active_row = _set_active_row
    mae._invalidate_cache = _invalidate_cache
    for handler_list, fn in _HANDLERS:
        if fn not in handler_list:
            handler_list.append(fn)
    _install_preview_handlers()


def _set_active_row(context, name):
    st = context.window_manager.iops_attr
    rebuild_mirror(context, force=True)
    idx = st.mirror.find(name)
    if idx >= 0:
        st.index = idx


def unregister_attribute_ui():
    disable_preview()
    _remove_preview_handlers()
    for fn in (_undo_push_now, _rebuild_timer, _deferred_collect):
        if bpy.app.timers.is_registered(fn):
            bpy.app.timers.unregister(fn)
    for handler_list, fn in _HANDLERS:
        if fn in handler_list:
            handler_list.remove(fn)
    mae._tag_mirror_dirty = lambda: None
    mae._rebuild_mirror_now = lambda context: None
    mae._set_active_row = lambda context, name: None
    mae._invalidate_cache = lambda: None
    _CACHE["rows"] = {}
    try:
        del bpy.types.WindowManager.iops_attr
    except AttributeError:
        pass
