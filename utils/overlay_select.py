"""Shift-click on an overlay toggle (Non-Planar, Z-Fight, Hidden Faces):
select the faces the overlay would flag instead of toggling it.

The overlays draw the EVALUATED mesh; the selection works on the ORIGINAL
mesh (no modifiers), whose polygon indices are the ones the user edits.
Callers compute `{object: polygon indices}` on the original meshes and
hand it to `select_flagged`. Operator context only (uses bmesh in Edit
Mode, writes mesh selection in Object Mode).
"""
import bmesh
import bpy
import numpy as np


def _edit_objects(context):
    objs = [o for o in (getattr(context, "objects_in_mode", None) or ())
            if o.type == 'MESH']
    if not objs and context.edit_object is not None:
        objs = [context.edit_object]
    return objs


def _select_in_edit_mode(context, flagged) -> int:
    """Deselect everything in every edit object, select the flagged faces,
    switch to face select mode."""
    context.tool_settings.mesh_select_mode = (False, False, True)
    total = 0
    for obj in _edit_objects(context):
        me = obj.data
        bm = bmesh.from_edit_mesh(me)
        for seq in (bm.verts, bm.edges, bm.faces):
            for elem in seq:
                elem.select = False
        bm.select_history.clear()
        bm.select_mode = {'FACE'}
        indices = flagged.get(obj)
        if indices is not None and len(indices):
            bm.faces.ensure_lookup_table()
            n_face = len(bm.faces)
            for i in indices.tolist():
                if i < n_face:
                    face = bm.faces[i]
                    if not face.hide:
                        face.select_set(True)
                        total += 1
        bm.select_flush_mode()
        bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)
    return total


def _write_mesh_selection(me, indices):
    """Select exactly polygons `indices` (and their edges and vertices) in
    the mesh data, so they are selected on entering Edit Mode."""
    n_poly = len(me.polygons)
    poly_sel = np.zeros(n_poly, bool)
    poly_sel[indices[indices < n_poly]] = True
    loop_start = np.empty(n_poly, np.int32)
    me.polygons.foreach_get("loop_start", loop_start)
    loop_total = np.empty(n_poly, np.int32)
    me.polygons.foreach_get("loop_total", loop_total)
    loop_sel = np.repeat(poly_sel, loop_total)
    loop_verts = np.empty(len(me.loops), np.int32)
    me.loops.foreach_get("vertex_index", loop_verts)
    loop_edges = np.empty(len(me.loops), np.int32)
    me.loops.foreach_get("edge_index", loop_edges)
    vert_sel = np.zeros(len(me.vertices), bool)
    vert_sel[loop_verts[loop_sel]] = True
    edge_sel = np.zeros(len(me.edges), bool)
    edge_sel[loop_edges[loop_sel]] = True
    me.vertices.foreach_set("select", vert_sel)
    me.edges.foreach_set("select", edge_sel)
    me.polygons.foreach_set("select", poly_sel)
    me.update()


def _select_in_object_mode(context, flagged) -> int:
    """Objects owning flagged faces become the selection; their flagged
    faces are written as the mesh selection."""
    for obj in context.selected_objects:
        obj.select_set(False)
    total = 0
    by_mesh = {}
    owners = []
    for obj, indices in flagged.items():
        if not len(indices):
            continue
        owners.append(obj)
        total += len(indices)
        prev = by_mesh.get(obj.data)
        by_mesh[obj.data] = (indices if prev is None
                             else np.union1d(prev, indices))
    for me, indices in by_mesh.items():
        if me.library is not None or me.override_library is not None:
            continue   # linked or overridden data can't keep a selection
        _write_mesh_selection(me, np.asarray(indices, np.int64))
    for obj in owners:
        try:
            obj.select_set(True)
        except RuntimeError:
            pass   # not in the view layer
    if owners:
        active = context.view_layer.objects.active
        if active not in owners:
            context.view_layer.objects.active = owners[0]
    return total


def select_flagged(context, flagged, label) -> int:
    """Select `flagged` ({object: original-mesh polygon indices}) in the
    current mode and push one undo step. Returns the face count."""
    if context.mode == 'EDIT_MESH':
        total = _select_in_edit_mode(context, flagged)
    else:
        total = _select_in_object_mode(context, flagged)
    bpy.ops.ed.undo_push(message=f"Select {label} Faces")
    return total


def report_selected(op, total):
    noun = "face" if total == 1 else "faces"
    op.report({'INFO'}, f"{total} {noun} selected")
