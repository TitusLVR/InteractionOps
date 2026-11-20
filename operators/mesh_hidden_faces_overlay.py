"""Hidden Faces Overlay — sticky viewport mode that highlights faces which
cannot be seen from outside the model: faces inside a closed shell, faces
buried in other geometry. They cost polygons and texture space and are
never seen.

A face is hidden when, from its front (normal) side, every ray from a set
of sample points over a set of directions hits geometry of the scope (the
pure-NumPy sampling core is utils/hidden_faces_core.py; rays are cast
against a mathutils BVHTree of the whole scope).

Scope, reading and caching are the Z-Fight Overlay's
(operators/mesh_zfight_overlay.py) — read that module's docstring first:
- Object Mode: the selected visible mesh objects; with no mesh object
  selected, every visible mesh object of the view layer.
- Edit Mode: every mesh object in edit mode.
All scoped objects go into one world-space triangle soup, and every face of
the soup occludes. The overlay NEVER touches the edit-bmesh: geometry comes
from the EVALUATED mesh through `foreach_get` bulk copies only.

The `Hidden: N` counter is a row in the iOps statistics overlay
(utils/draw_stats.py), which reads it via `hidden_faces_count()`.
"""
import bpy
import gpu
import numpy as np
from bpy.app.handlers import persistent
from gpu_extras.batch import batch_for_shader
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from ..ui.draw import (Role, draw_scope, get_theme,
                       safe_handler_add, safe_handler_remove)
from ..utils.hidden_faces_core import hidden_faces
from ..utils.overlay_select import report_selected, select_flagged
# Same depth-shrink fill shader as the Non-Planar overlay.
from .mesh_nonplanar_overlay import DEPTH_SHRINK, _get_shader
# Same scope, mesh reading and world soup as the Z-Fight overlay.
from .mesh_zfight_overlay import (_same_content, _scope, _tag_redraw_view3d,
                                  fill_geometry, mesh_arrays, original_items,
                                  split_hits, world_soup)

FILL_ALPHA = 0.5
MODES = ('OBJECT', 'EDIT_MESH')
FILL_ROLE = Role.PREVIEW_LINE   # Non-Planar and Z-Fight use ERROR_LINE
DEFAULT_RAYS = 128
_MAX_WALK = 256   # hits followed along one ray by the inside-a-solid test

_STATE = {
    "handle_view": None,    # POST_VIEW draw handle
    "geom": None,           # (pos, col) float32 arrays from last collection
    "batch_dirty": False,   # geom changed; draw callback rebuilds the batch
    "batch": None,          # (shader, GPUBatch) or None
    "count": 0,             # hidden faces at last collection
    "scope_key": None,      # (mode, object pointers, params) last collected
    "signature": None,      # inputs of the last detection run
    "cache": {},            # object as_pointer() -> local-space entry
    "cache_mode": None,     # mode the cache was read in
}

_VERSION = [0]   # bumped whenever a cache entry gets new content


def overlay_enabled() -> bool:
    return _STATE["handle_view"] is not None


def _app_handler_lists():
    h = bpy.app.handlers
    return (h.depsgraph_update_post, h.undo_post, h.redo_post, h.load_post)


def _params() -> tuple:
    """(rays,) from the addon preferences."""
    try:
        prefs = bpy.context.preferences.addons["InteractionOps"].preferences
        return (int(prefs.hidden_faces_rays),)
    except (KeyError, AttributeError):
        return (DEFAULT_RAYS,)


def _scope_key(context, objs) -> tuple:
    return (context.mode, tuple(o.as_pointer() for o in objs), _params())


def _read_entry(obj, depsgraph, edit_mode):
    """Evaluated mesh of `obj` -> local-space arrays. foreach_get only."""
    ob_eval = obj.evaluated_get(depsgraph)
    # In edit mode the evaluated `.data` is a bmesh-backed wrapper whose
    # Mesh arrays are EMPTY; to_mesh() forces the native bmesh->Mesh
    # conversion (still no Python bmesh wrappers involved).
    try:
        me = ob_eval.to_mesh()
    except RuntimeError:
        me = None
    entry = {"name": obj.name, "data_ptr": obj.data.as_pointer(),
             "n_poly": 0}
    if me is None:
        return entry
    try:
        entry.update(mesh_arrays(me, edit_mode))
        return entry
    finally:
        ob_eval.to_mesh_clear()


def _entry_for(obj, depsgraph, edit_mode):
    """Cached entry for `obj`, read when missing or stale."""
    ptr = obj.as_pointer()
    cache = _STATE["cache"]
    entry = cache.get(ptr)
    if (entry is not None and entry["name"] == obj.name
            and entry["data_ptr"] == obj.data.as_pointer()
            and "version" in entry):
        return entry
    new = _read_entry(obj, depsgraph, edit_mode)
    if entry is not None and "version" in entry and _same_content(entry, new):
        new["version"] = entry["version"]
    else:
        _VERSION[0] += 1
        new["version"] = _VERSION[0]
    cache[ptr] = new
    return new


def _invalidate(changed_objects=(), changed_meshes=()):
    """Mark cache entries stale (kept for the same-content check)."""
    cache = _STATE["cache"]
    meshes = set(changed_meshes)
    for ptr, entry in cache.items():
        if ptr in changed_objects or entry["data_ptr"] in meshes:
            entry.pop("version", None)


def _clear_result():
    _STATE["geom"] = None
    _STATE["count"] = 0
    _STATE["batch_dirty"] = True
    _STATE["signature"] = None


def _detect(soup, rays):
    """Soup polygon indices that are hidden. Every soup triangle occludes;
    only visible (not edit-hidden) polygons are tested."""
    co = soup["co"]
    tri_verts = soup["tri_verts"]
    bvh = BVHTree.FromPolygons(co.tolist(), tri_verts.tolist(),
                               all_triangles=True)
    ray_cast = bvh.ray_cast
    far = 1.0e30
    diag = float(np.linalg.norm(co.max(axis=0) - co.min(axis=0)))
    step = max(1e-6, 1e-5 * diag)

    def cast(origin, direction, distance=None):
        return ray_cast(origin, direction,
                        far if distance is None else distance)[0] is not None

    def winding(origin, direction):
        # Walk every hit along the ray. Triangle normals follow the polygon
        # winding: a normal along the ray is a back-side hit.
        d = Vector(direction)
        o = Vector(origin)
        total = 0
        for _ in range(_MAX_WALK):
            loc, normal, _index, _dist = ray_cast(o, d)
            if loc is None:
                return total
            total += 1 if normal.dot(d) > 0.0 else -1
            o = loc + d * step
        return 0   # undecided: treat as outside

    return hidden_faces(co, tri_verts, soup["tri_poly"], soup["normals"],
                        rays, cast, winding=winding, test=soup["visible"])


def _collect(context, depsgraph=None):
    """Read the scoped objects into one world-space soup, detect, cache
    CPU arrays. Main-thread, between-evaluations contexts only (operator
    execute, app handlers, timers) — and never via bmesh."""
    mode = context.mode
    if _STATE["cache_mode"] != mode:
        _STATE["cache"] = {}
        _STATE["cache_mode"] = mode
    objs = _scope(context)
    params = _params()
    _STATE["scope_key"] = _scope_key(context, objs)
    if not objs:
        _clear_result()
        return
    if depsgraph is None:
        depsgraph = context.evaluated_depsgraph_get()
    edit_mode = mode == 'EDIT_MESH'
    items = []
    for obj in objs:
        entry = _entry_for(obj, depsgraph, edit_mode)
        if entry["n_poly"]:
            items.append((entry, np.array(obj.matrix_world, np.float64)))
    # Drop entries of objects that left the scene or the scope's mode.
    live = {o.as_pointer() for o in objs}
    if len(_STATE["cache"]) > 4 * max(len(live), 64):
        _STATE["cache"] = {p: e for p, e in _STATE["cache"].items()
                           if p in live}
    rgb = tuple(get_theme(context).color_for(FILL_ROLE)[:3])
    # Selection clicks, view changes and unrelated edits also fire
    # depsgraph updates; skip detection when nothing it reads changed.
    signature = (mode, params, rgb,
                 tuple((e["version"], mw.tobytes()) for e, mw in items))
    if signature == _STATE["signature"]:
        return
    _STATE["signature"] = signature
    _STATE["geom"] = None
    _STATE["count"] = 0
    _STATE["batch_dirty"] = True
    if not items:
        return
    soup = world_soup(items)
    hits = _detect(soup, params[0])
    _STATE["count"] = len(hits)
    if not len(hits):
        return
    _STATE["geom"] = fill_geometry(soup, hits, rgb, FILL_ALPHA)


def flagged_faces(context) -> dict:
    """{object: polygon indices of its original mesh} the hidden-face check
    flags in the current scope — for the Shift-click selection."""
    objs = _scope(context)
    items = original_items(objs, context.mode == 'EDIT_MESH')
    if not items:
        return {}
    soup = world_soup([(e, mw) for _o, e, mw in items])
    return split_hits(_detect(soup, _params()[0]), items, soup)


def _apply_updates(depsgraph):
    """Invalidate cache entries the depsgraph reports geometry changes for."""
    objects = set()
    meshes = set()
    for u in depsgraph.updates:
        if not u.is_updated_geometry:
            continue
        idv = u.id
        if isinstance(idv, bpy.types.Object):
            objects.add(idv.original.as_pointer())
        elif isinstance(idv, bpy.types.Mesh):
            meshes.add(idv.original.as_pointer())
    if objects or meshes:
        _invalidate(objects, meshes)


@persistent
def _on_change(scene=None, depsgraph=None, *_args):
    """depsgraph_update_post gets the depsgraph (incremental geometry
    re-reads); undo/redo/load don't, and their pointers may all be stale,
    so the cache is dropped."""
    if not overlay_enabled():
        return
    context = bpy.context
    if context.mode not in MODES:
        return
    try:
        if isinstance(depsgraph, bpy.types.Depsgraph):
            _apply_updates(depsgraph)
            _collect(context, depsgraph)
        else:
            _STATE["cache"] = {}
            _collect(context)
    except Exception as e:
        # A raising app handler gets called every depsgraph update.
        print("IOPS Hidden Faces overlay: collect failed:", e)


_TIMER_PENDING = False


def _deferred_collect():
    """One-shot timer body: re-collect outside the draw callback for
    changes no app handler reports (preferences, scope)."""
    global _TIMER_PENDING
    _TIMER_PENDING = False
    if overlay_enabled():
        context = bpy.context
        if context.mode in MODES:
            try:
                _collect(context)
            except Exception as e:
                print("IOPS Hidden Faces overlay: collect failed:", e)
            _tag_redraw_view3d(context)
    return None


def _schedule_collect():
    # Registering a timer is safe from the draw callback; its body runs
    # later on the main thread.
    global _TIMER_PENDING
    if not _TIMER_PENDING:
        _TIMER_PENDING = True
        bpy.app.timers.register(_deferred_collect)


def _cache_stale(context) -> bool:
    """Scope (mode, selection, visibility, objects) or prefs changed."""
    return _scope_key(context, _scope(context)) != _STATE["scope_key"]


def _build_batch():
    """GPU side of the split: cached CPU arrays -> GPUBatch. Draw-callback
    only (needs the bound GPU context)."""
    _STATE["batch_dirty"] = False
    geom = _STATE["geom"]
    if geom is None or not len(geom[0]):
        _STATE["batch"] = None
        return
    shader = _get_shader()
    _STATE["batch"] = (shader,
                       batch_for_shader(shader, 'TRIS',
                                        {"pos": geom[0], "color": geom[1]}))


def _draw_view():
    context = bpy.context
    if context.mode not in MODES:
        return
    if _cache_stale(context):
        _schedule_collect()
    if _STATE["batch_dirty"]:
        try:
            _build_batch()
        except Exception as e:
            # Never raise from a draw handler — it repeats every redraw.
            print("IOPS Hidden Faces overlay: batch build failed:", e)
            _STATE["batch"] = None
            _STATE["batch_dirty"] = False
    if _STATE["batch"] is None:
        return
    shader, batch = _STATE["batch"]
    with draw_scope(blend='ALPHA', depth='LESS_EQUAL', depth_mask=False):
        shader.bind()
        shader.uniform_float("viewMat", gpu.matrix.get_model_view_matrix())
        shader.uniform_float("projMat", gpu.matrix.get_projection_matrix())
        shader.uniform_float("depthShrink", DEPTH_SHRINK)
        batch.draw(shader)


def hidden_faces_count() -> int:
    """Hidden face count at the last collection, over all scoped objects —
    read by the iOps statistics overlay for its Hidden row."""
    return _STATE["count"]


def _enable():
    if overlay_enabled():
        return
    _STATE["handle_view"] = safe_handler_add(
        bpy.types.SpaceView3D, _draw_view, (), "WINDOW", "POST_VIEW")
    for lst in _app_handler_lists():
        if _on_change not in lst:
            lst.append(_on_change)


def disable_overlay():
    """Idempotent. Also called from the addon's unregister(); removes only
    this module's handlers."""
    safe_handler_remove(_STATE["handle_view"], bpy.types.SpaceView3D, "WINDOW")
    for lst in _app_handler_lists():
        while _on_change in lst:
            lst.remove(_on_change)
    _STATE.update(handle_view=None, geom=None, batch_dirty=False,
                  batch=None, count=0, scope_key=None, signature=None,
                  cache={}, cache_mode=None)


class IOPS_OT_MeshHiddenFacesOverlay(bpy.types.Operator):
    """Toggle a real-time highlight of faces that cannot be seen from
    outside the model: faces inside a closed shell or buried in other
    geometry.
    Object Mode checks the selected objects (all visible ones when nothing
    is selected); Edit Mode checks every object being edited.
    Shift-click: select those faces instead (Object Mode selects their
    objects and marks the faces for Edit Mode)"""
    bl_idname = "iops.mesh_hidden_faces_overlay"
    bl_label = "Hidden Faces Overlay"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        # Enabling needs Object or Edit Mesh mode; disabling works anywhere.
        return overlay_enabled() or context.mode in MODES

    def invoke(self, context, event):
        if not event.shift:
            return self.execute(context)
        if context.mode not in MODES:
            self.report({'WARNING'}, "Select hidden faces: Object or "
                                     "Edit Mode only")
            return {'CANCELLED'}
        total = select_flagged(context, flagged_faces(context), "Hidden")
        report_selected(self, total)
        _tag_redraw_view3d(context)
        return {'FINISHED'}

    def execute(self, context):
        if overlay_enabled():
            disable_overlay()
            self.report({'INFO'}, "Hidden Faces overlay: OFF")
        else:
            _enable()
            _collect(context)
            self.report({'INFO'},
                        f"Hidden Faces overlay: ON "
                        f"({_STATE['count']} hidden faces)")
        _tag_redraw_view3d(context)
        return {'FINISHED'}
