"""Edge Data widget — bevel weight, crease, sharp, seam, freestyle, clear.

First concrete widget for the GPU widget framework (ui/widgets), per
docs/superpowers/specs/2026-06-11-gpu-widget-system-design.md.

Value adapters (verified empirically on Blender 5.1.2):
- Bevel weight / crease are generic float EDGE attributes named
  "bevel_weight_edge" / "crease_edge". They do NOT exist on a fresh mesh;
  bmesh access is `bm.edges.layers.float.get(name)` and creation is
  `bm.edges.layers.float.new(name)`. A missing layer reads as 0.0.
- Sharp is the inverse of `edge.smooth` on BMEdge.
- Seam is `edge.seam` on BMEdge.
- Freestyle mark is a bool EDGE attribute "freestyle_edge" accessed via
  `bm.edges.layers.bool` (BMEdge has no `use_freestyle_mark` in 5.1; the
  native mark_freestyle_edge operator creates this same bool layer).

Binding contract (ui/widgets/controls.py):
- getters return (value, is_mixed); value None = nothing selected.
- setters write uniformly to ALL selected edges.
- bmesh is re-acquired with bmesh.from_edit_mesh() on EVERY call; only
  plain floats/bools/indices are kept between events.
"""
import bmesh

from ..ui.widgets import (Widget, Section, Slider, PresetRow, FlipBox,
                          ActionButton, Row)
from ..ui.widgets.controls import mixed_state

# Attribute/layer names verified against Blender 5.1.2 (see module docstring)
BEVEL_LAYER = "bevel_weight_edge"
CREASE_LAYER = "crease_edge"
FREESTYLE_LAYER = "freestyle_edge"

CLEAR_SCRIPT = "B:\\scripts\\iops_exec\\CLEAN_Edge_Data_Clear.py"


# ----------------------------------------------------------------------
# bmesh helpers — every entry point re-acquires bmesh, nothing is cached
# ----------------------------------------------------------------------
def _edit_meshes(context):
    """Mesh datablocks currently in edit mode (multi-object edit aware)."""
    objs = getattr(context, "objects_in_mode_unique_data", None)
    if objs:
        return [ob.data for ob in objs if ob.type == "MESH"]
    ob = getattr(context, "edit_object", None)
    if ob is not None and ob.type == "MESH":
        return [ob.data]
    return []


def _update(me):
    """Flush a non-destructive attribute-only bmesh edit back to the mesh."""
    bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)


def has_selected_edges(context):
    """Cheap any-selected-edge check (early exit on the first hit) — the
    enabled_get hook for presets/Clear, which the spec requires inert and
    grayed when nothing is selected."""
    for me in _edit_meshes(context):
        bm = bmesh.from_edit_mesh(me)
        for e in bm.edges:
            if e.select:
                return True
    return False


# ----------------------------------------------------------------------
# Float layer adapters (bevel weight, crease)
# ----------------------------------------------------------------------
def _selected_float_values(context, layer_name):
    """Yield the layer value of every selected edge; missing layer = 0.0."""
    for me in _edit_meshes(context):
        bm = bmesh.from_edit_mesh(me)
        lay = bm.edges.layers.float.get(layer_name)
        for e in bm.edges:
            if e.select:
                yield e[lay] if lay is not None else 0.0


def _get_edge_float(context, layer_name):
    return mixed_state(_selected_float_values(context, layer_name))


def _set_edge_float(context, layer_name, value):
    """Uniform write to all selected edges, creating the layer on demand."""
    value = float(value)
    for me in _edit_meshes(context):
        bm = bmesh.from_edit_mesh(me)
        lay = bm.edges.layers.float.get(layer_name)
        if lay is None:
            if value == 0.0:
                # Missing layer already reads as 0.0 — nothing to store
                continue
            lay = bm.edges.layers.float.new(layer_name)
        changed = False
        for e in bm.edges:
            if e.select:
                e[lay] = value
                changed = True
        if changed:
            _update(me)


def _snapshot_edge_float(context, layer_name):
    """Capture (mesh name, [(edge index, value)]) of the selected edges.
    Plain data only — used by the slider ESC/RMB exact restore."""
    token = []
    for me in _edit_meshes(context):
        bm = bmesh.from_edit_mesh(me)
        lay = bm.edges.layers.float.get(layer_name)
        items = [(e.index, e[lay] if lay is not None else 0.0)
                 for e in bm.edges if e.select]
        if items:
            token.append((me.name, items))
    return token


def _restore_edge_float(context, layer_name, token):
    """Put snapshot values back per edge index (drag gestures never change
    topology, so indices captured at drag start stay valid)."""
    if not token:
        return
    by_name = {me.name: me for me in _edit_meshes(context)}
    for name, items in token:
        me = by_name.get(name)
        if me is None:
            continue
        bm = bmesh.from_edit_mesh(me)
        lay = bm.edges.layers.float.get(layer_name)
        if lay is None:
            lay = bm.edges.layers.float.new(layer_name)
        bm.edges.ensure_lookup_table()
        count = len(bm.edges)
        for idx, v in items:
            if 0 <= idx < count:
                bm.edges[idx][lay] = v
        _update(me)


def get_bevel(context):
    return _get_edge_float(context, BEVEL_LAYER)


def set_bevel(context, value):
    _set_edge_float(context, BEVEL_LAYER, value)


def snapshot_bevel(context):
    return _snapshot_edge_float(context, BEVEL_LAYER)


def restore_bevel(context, token):
    _restore_edge_float(context, BEVEL_LAYER, token)


def get_crease(context):
    return _get_edge_float(context, CREASE_LAYER)


def set_crease(context, value):
    _set_edge_float(context, CREASE_LAYER, value)


def snapshot_crease(context):
    return _snapshot_edge_float(context, CREASE_LAYER)


def restore_crease(context, token):
    _restore_edge_float(context, CREASE_LAYER, token)


# ----------------------------------------------------------------------
# Flag adapters (sharp, seam, freestyle)
# ----------------------------------------------------------------------
def _selected_flag_values(context, read):
    """Yield read(edge) for every selected edge in every edit mesh."""
    for me in _edit_meshes(context):
        bm = bmesh.from_edit_mesh(me)
        for e in bm.edges:
            if e.select:
                yield read(e)


def get_sharp(context):
    # Sharp is the INVERSE of BMEdge.smooth
    return mixed_state(_selected_flag_values(context, lambda e: not e.smooth))


def set_sharp(context, value):
    value = bool(value)
    for me in _edit_meshes(context):
        bm = bmesh.from_edit_mesh(me)
        changed = False
        for e in bm.edges:
            if e.select:
                e.smooth = not value
                changed = True
        if changed:
            _update(me)


def get_seam(context):
    return mixed_state(_selected_flag_values(context, lambda e: e.seam))


def set_seam(context, value):
    value = bool(value)
    for me in _edit_meshes(context):
        bm = bmesh.from_edit_mesh(me)
        changed = False
        for e in bm.edges:
            if e.select:
                e.seam = value
                changed = True
        if changed:
            _update(me)


def get_freestyle(context):
    """Freestyle mark lives in the "freestyle_edge" bool layer; a mesh that
    was never marked has no layer at all — read that as False."""
    def values():
        for me in _edit_meshes(context):
            bm = bmesh.from_edit_mesh(me)
            lay = bm.edges.layers.bool.get(FREESTYLE_LAYER)
            for e in bm.edges:
                if e.select:
                    yield bool(e[lay]) if lay is not None else False
    return mixed_state(values())


def set_freestyle(context, value):
    value = bool(value)
    for me in _edit_meshes(context):
        bm = bmesh.from_edit_mesh(me)
        lay = bm.edges.layers.bool.get(FREESTYLE_LAYER)
        if lay is None:
            if not value:
                # Missing layer already reads as False — nothing to clear
                continue
            lay = bm.edges.layers.bool.new(FREESTYLE_LAYER)
        changed = False
        for e in bm.edges:
            if e.select:
                e[lay] = value
                changed = True
        if changed:
            _update(me)


# ----------------------------------------------------------------------
# Widget
# ----------------------------------------------------------------------
class EdgeDataWidget(Widget):
    """Persistent Edge Data panel: bevel weight + crease sliders with
    presets, sharp/seam/freestyle flip boxes and a Clear action."""

    name = "edge_data"
    title = "Edge Data"
    space = "VIEW_3D"

    def build(self):
        return [
            Section("Bevel Weight"),
            Slider(get=get_bevel, set=set_bevel, snap=0.125,
                   snapshot=snapshot_bevel, restore=restore_bevel),
            PresetRow([0, 0.25, 0.5, 1.0], set=set_bevel,
                      enabled_get=has_selected_edges),
            Section("Crease"),
            Slider(get=get_crease, set=set_crease, snap=0.125,
                   snapshot=snapshot_crease, restore=restore_crease),
            PresetRow([0, 0.5, 0.9, 1.0], set=set_crease,
                      enabled_get=has_selected_edges),
            Section("Flags"),
            Row([FlipBox("Sharp", get=get_sharp, set=set_sharp),
                 FlipBox("Seam", get=get_seam, set=set_seam),
                 FlipBox("Freestyle", get=get_freestyle, set=set_freestyle)]),
            ActionButton("Clear", op="iops.executor",
                         kwargs={"script": CLEAR_SCRIPT},
                         role="error",
                         enabled_get=has_selected_edges),
        ]

    def poll(self, context):
        return context.mode == "EDIT_MESH"
