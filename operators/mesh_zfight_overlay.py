"""Z-Fight Overlay — sticky viewport mode that highlights faces which will
z-fight: faces that lie in one plane, face the same way and overlap
by area, inside one object or between different objects. Faces that only
share an edge or a vertex are not a conflict.

Scope:
- Object Mode: every mesh object visible in the reference 3D viewport (the
  one the overlay was turned on in), selected or not, so Local View and the
  viewport's own hiding are respected. Selection never changes the scope.
- Edit Mode: every mesh object in edit mode that is visible there.
Every viewport draws the same result. The fill is drawn on top of all
geometry while the "In Front" preference is on (default), else depth-tested.
All scoped objects go into one world-space triangle soup, so faces of two
objects placed flush against each other are caught too. Two objects that
share one mesh are separate entries (each at its own matrix).

Sibling of the Non-Planar Faces Overlay (operators/mesh_nonplanar_overlay.py)
and built the same way — read that module's docstring first. The rule that
matters most is repeated here: the overlay NEVER touches the edit-bmesh.
Any Python bmesh element access can realloc customdata pools a running
transform modal holds pointers into (heap corruption, crash). Geometry is
read from the EVALUATED mesh, `obj.evaluated_get(depsgraph).to_mesh()`,
through `foreach_get` bulk copies only (in Object Mode that is the mesh
with modifiers applied, i.e. what is rendered).

Each object's local-space arrays are cached and re-read only when the
depsgraph reports a geometry update for it (or its mesh); a pure
transform only re-applies the matrix. Detection (the pure-NumPy core in
utils/zfight_core.py) is skipped when nothing it reads has changed.
Collection runs in `bpy.app.handlers` hooks (live during transforms); the
draw callback turns the cached CPU arrays into a GPUBatch. The
`Z-Fight: N` counter is a row in the iOps statistics overlay
(utils/draw_stats.py), which reads it via `zfight_count()`.
"""
import bpy
import gpu
import numpy as np
from bpy.app.handlers import persistent
from gpu_extras.batch import batch_for_shader

from ..ui.draw import (Role, draw_scope, get_theme,
                       safe_handler_add, safe_handler_remove)
from ..utils.planarity import overlay_normal_offset
from ..utils.overlay_select import report_selected, select_flagged
from ..utils.zfight_core import zfight_faces
# Same depth-shrink fill shader as the Non-Planar overlay.
from .mesh_nonplanar_overlay import DEPTH_SHRINK, _get_shader

FILL_ALPHA = 0.5
MODES = ('OBJECT', 'EDIT_MESH')

_STATE = {
    "handle_view": None,    # POST_VIEW draw handle
    "geom": None,           # (pos, col) float32 arrays from last collection
    "batch_dirty": False,   # geom changed; draw callback rebuilds the batch
    "batch": None,          # (shader, GPUBatch) or None
    "count": 0,             # z-fighting faces at last collection
    "scope_key": None,      # (mode, object pointers, params) last collected
    "signature": None,      # inputs of the last detection run
    "cache": {},            # object as_pointer() -> local-space entry
    "cache_mode": None,     # mode the cache was read in
    "view_area": None,      # as_pointer() of the reference 3D viewport area
}

_VERSION = [0]   # bumped whenever a cache entry gets new content


def overlay_enabled() -> bool:
    return _STATE["handle_view"] is not None


def in_front(pref="zfight_in_front", default=True) -> bool:
    """The overlay's "In Front" preference: fill drawn over all geometry."""
    try:
        prefs = bpy.context.preferences.addons["InteractionOps"].preferences
        return bool(getattr(prefs, pref))
    except (KeyError, AttributeError):
        return default


def view_area_pointer(context):
    """as_pointer() of the context's 3D viewport area, else None. Only an
    integer is kept, never the RNA struct: it is compared against live
    areas later and never dereferenced, so a closed area or a loaded file
    cannot leave a dangling reference behind."""
    area = getattr(context, "area", None)
    if area is not None and area.type == 'VIEW_3D':
        return area.as_pointer()
    return None


def find_view_space(area_ptr=None):
    """SpaceView3D of the 3D viewport area `area_ptr`, else of the first 3D
    viewport found; None without any (background mode)."""
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None and bpy.data.window_managers:
        wm = bpy.data.window_managers[0]
    first = None
    for window in (wm.windows if wm is not None else ()):
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != 'VIEW_3D':
                continue
            if area_ptr is not None and area.as_pointer() == area_ptr:
                return area.spaces.active
            if first is None:
                first = area.spaces.active
    return first


def context_view_space(context):
    """The context's 3D viewport (an operator run from it), else the first."""
    space = getattr(context, "space_data", None)
    if space is not None and space.type == 'VIEW_3D':
        return space
    return find_view_space()


def _visible(obj, view_layer, space) -> bool:
    """Visible in the view layer and, with a viewport, in that viewport too
    (Local View, the viewport's own hiding)."""
    if space is None:
        return obj.visible_get(view_layer=view_layer)
    return obj.visible_get(view_layer=view_layer, viewport=space)


def _app_handler_lists():
    h = bpy.app.handlers
    return (h.depsgraph_update_post, h.undo_post, h.redo_post, h.load_post)


def _params() -> tuple:
    """(angle in degrees, distance) from the addon preferences."""
    try:
        prefs = bpy.context.preferences.addons["InteractionOps"].preferences
        return (float(prefs.zfight_angle), float(prefs.zfight_distance))
    except (KeyError, AttributeError):
        return (0.5, 0.0001)


def _scope(context, space) -> list:
    """Mesh objects to check, in a stable order: those visible in the 3D
    viewport `space` (None: view layer visibility only). Selection does not
    matter, so selecting an object never drops conflicts with the others."""
    mode = context.mode
    view_layer = context.view_layer
    if view_layer is None or mode not in MODES:
        return []
    if mode == 'EDIT_MESH':
        objs = [o for o in (getattr(context, "objects_in_mode", None) or ())
                if o.type == 'MESH']
        if not objs and context.edit_object is not None:
            objs = [context.edit_object]
        return [o for o in objs if _visible(o, view_layer, space)]
    # A just-removed object can leave a None in the list until the view
    # layer syncs.
    return [o for o in view_layer.objects
            if o is not None and o.type == 'MESH'
            and _visible(o, view_layer, space)]


def _overlay_scope(context) -> list:
    """Scope in the viewport the overlay was turned on in."""
    return _scope(context, find_view_space(_STATE["view_area"]))


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


def mesh_arrays(me, edit_mode) -> dict:
    """Local-space arrays of a plain Mesh via foreach_get: n_poly, co,
    tri_verts, tri_poly, normals, visible (n_poly 0 and nothing else for an
    empty mesh). Shared by the overlays (evaluated mesh) and by their
    Shift-click selection (original mesh)."""
    n_poly = len(me.polygons)
    if n_poly == 0 or len(me.vertices) == 0:
        return {"n_poly": 0}
    co = np.empty(len(me.vertices) * 3, np.float64)
    me.vertices.foreach_get("co", co)
    me.calc_loop_triangles()
    n_tri = len(me.loop_triangles)
    tri_verts = np.empty(n_tri * 3, np.int32)
    me.loop_triangles.foreach_get("vertices", tri_verts)
    tri_poly = np.empty(n_tri, np.int32)
    me.loop_triangles.foreach_get("polygon_index", tri_poly)
    normals = np.empty(n_poly * 3, np.float64)
    me.polygons.foreach_get("normal", normals)
    visible = np.ones(n_poly, bool)
    # Hidden faces only exist in Edit Mode; Object Mode renders them.
    hide = me.attributes.get(".hide_poly") if edit_mode else None
    if hide is not None and hide.domain == 'FACE':
        hidden = np.empty(n_poly, bool)
        hide.data.foreach_get("value", hidden)
        visible = ~hidden
    return {"n_poly": n_poly, "co": co.reshape(-1, 3),
            "tri_verts": tri_verts.reshape(-1, 3), "tri_poly": tri_poly,
            "normals": normals.reshape(-1, 3), "visible": visible}


def world_soup(items) -> dict:
    """[(entry, matrix_world as (4, 4) ndarray)] -> one world-space soup:
    co, tri_verts, tri_poly (int64, polygon indices offset per item),
    visible, normals (world, unit), offset (per-polygon fill push) and
    poly_start (first soup polygon index of each item)."""
    co_parts, tri_parts, poly_parts, vis_parts, nrm_parts, off_parts = (
        [], [], [], [], [], [])
    starts = []
    v_off = 0
    p_off = 0
    for entry, mw in items:
        co_w = entry["co"] @ mw[:3, :3].T + mw[:3, 3]
        co_parts.append(co_w)
        tri_parts.append(entry["tri_verts"] + v_off)
        poly_parts.append(entry["tri_poly"] + p_off)
        vis_parts.append(entry["visible"])
        nrm_parts.append(_world_normals(entry["normals"], mw))
        # Fill push relative to each object's own size: a fixed or
        # scene-wide offset would float visibly above small objects.
        diag = float(np.linalg.norm(co_w.max(axis=0) - co_w.min(axis=0)))
        off_parts.append(np.full(entry["n_poly"], overlay_normal_offset(diag)))
        starts.append(p_off)
        v_off += len(co_w)
        p_off += entry["n_poly"]
    return {"co": np.concatenate(co_parts),
            "tri_verts": np.concatenate(tri_parts).astype(np.int64),
            "tri_poly": np.concatenate(poly_parts).astype(np.int64),
            "visible": np.concatenate(vis_parts),
            "normals": np.concatenate(nrm_parts),
            "offset": np.concatenate(off_parts),
            "poly_start": starts}


def fill_geometry(soup, hits, rgb, alpha):
    """(pos, col) float32 fill triangles of the soup polygons `hits`, each
    pushed along its own normal; None when nothing to draw."""
    tri_poly = soup["tri_poly"]
    tri_sel = np.nonzero(np.isin(tri_poly, hits))[0]
    if not len(tri_sel):
        return None
    sel_poly = tri_poly[tri_sel]
    pos = soup["co"][soup["tri_verts"][tri_sel].ravel()]
    # Each fill is pushed along its own face normal, so two coincident
    # faces with opposite normals each show their fill on their own side.
    pos += np.repeat(soup["normals"][sel_poly]
                     * soup["offset"][sel_poly, None], 3, axis=0)
    col = np.empty((len(pos), 4), np.float32)
    col[:, :3] = rgb
    col[:, 3] = alpha
    return (pos.astype(np.float32), col)


def original_items(objs, edit_mode):
    """[(obj, entry, matrix_world)] read from the ORIGINAL meshes (no
    modifiers), so polygon indices match the mesh the user selects in.
    Operator context only: in Edit Mode it syncs the edit-mesh first."""
    items = []
    for obj in objs:
        if edit_mode:
            obj.update_from_editmode()
        entry = mesh_arrays(obj.data, edit_mode)
        if entry["n_poly"]:
            items.append((obj, entry,
                          np.array(obj.matrix_world, np.float64)))
    return items


def split_hits(hits, objs_items, soup):
    """Soup polygon indices -> {obj: local polygon indices}."""
    out = {}
    starts = soup["poly_start"]
    for k, (obj, entry, _mw) in enumerate(objs_items):
        lo = starts[k]
        local = hits[(hits >= lo) & (hits < lo + entry["n_poly"])] - lo
        if len(local):
            out[obj] = local
    return out


def flagged_faces(context) -> dict:
    """{object: polygon indices of its original mesh} the Z-Fight check
    flags in the current scope — for the Shift-click selection."""
    objs = _scope(context, context_view_space(context))
    edit_mode = context.mode == 'EDIT_MESH'
    items = original_items(objs, edit_mode)
    if not items:
        return {}
    soup = world_soup([(e, mw) for _o, e, mw in items])
    tri_vis = soup["visible"][soup["tri_poly"]]
    angle, distance = _params()
    hits = zfight_faces(soup["co"], soup["tri_verts"][tri_vis],
                        soup["tri_poly"][tri_vis], angle, distance)
    return split_hits(hits, items, soup)


_ARRAYS = ("co", "tri_verts", "tri_poly", "normals", "visible")


def _same_content(a, b) -> bool:
    if a["n_poly"] != b["n_poly"]:
        return False
    if a["n_poly"] == 0:
        return True
    return all(np.array_equal(a[k], b[k]) for k in _ARRAYS)


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


def _world_normals(normals, mw):
    try:
        inv3 = np.linalg.inv(mw[:3, :3])
    except np.linalg.LinAlgError:
        return np.zeros_like(normals)   # zero scale: nothing to offset
    world_n = normals @ inv3  # row-vector form of (M^-1)^T @ n
    lens = np.linalg.norm(world_n, axis=1, keepdims=True)
    np.divide(world_n, lens, out=world_n, where=lens > 0.0)
    return world_n


def _collect(context, depsgraph=None):
    """Read the scoped objects into one world-space soup, detect, cache
    CPU arrays. Main-thread, between-evaluations contexts only (operator
    execute, app handlers, timers) — and never via bmesh."""
    mode = context.mode
    if _STATE["cache_mode"] != mode:
        _STATE["cache"] = {}
        _STATE["cache_mode"] = mode
    objs = _overlay_scope(context)
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
    rgb = tuple(get_theme(context).color_for(Role.ERROR_LINE)[:3])
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
    tri_vis = soup["visible"][soup["tri_poly"]]
    hits = zfight_faces(soup["co"], soup["tri_verts"][tri_vis],
                        soup["tri_poly"][tri_vis], params[0], params[1])
    _STATE["count"] = len(hits)
    if not len(hits):
        return
    _STATE["geom"] = fill_geometry(soup, hits, rgb, FILL_ALPHA)


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
    so the cache is dropped. Fires per mouse move during transform modals,
    which is what keeps the overlay live while moving geometry."""
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
        print("IOPS Z-Fight overlay: collect failed:", e)


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
                print("IOPS Z-Fight overlay: collect failed:", e)
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
    """Scope (mode, viewport visibility, objects) or prefs changed."""
    return _scope_key(context, _overlay_scope(context)) != _STATE["scope_key"]


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
            print("IOPS Z-Fight overlay: batch build failed:", e)
            _STATE["batch"] = None
            _STATE["batch_dirty"] = False
    if _STATE["batch"] is None:
        return
    shader, batch = _STATE["batch"]
    # "In Front" is read per redraw: no re-detection, no batch rebuild.
    depth = 'ALWAYS' if in_front() else 'LESS_EQUAL'
    with draw_scope(blend='ALPHA', depth=depth, depth_mask=False):
        shader.bind()
        shader.uniform_float("viewMat", gpu.matrix.get_model_view_matrix())
        shader.uniform_float("projMat", gpu.matrix.get_projection_matrix())
        shader.uniform_float("depthShrink", DEPTH_SHRINK)
        batch.draw(shader)


def zfight_count() -> int:
    """Z-fighting face count at the last collection, over all scoped
    objects — read by the iOps statistics overlay for its Z-Fight row."""
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
                  cache={}, cache_mode=None, view_area=None)


def _tag_redraw_view3d(context):
    """Redraw every 3D viewport of every window: a timer has no screen in
    its context, and all viewports draw the overlay."""
    wm = getattr(context, "window_manager", None)
    if wm is not None:
        screens = [w.screen for w in wm.windows]
    else:
        screens = [getattr(context, "screen", None)]
    for screen in screens:
        if screen is None:
            continue
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


class IOPS_OT_MeshZFightOverlay(bpy.types.Operator):
    """Toggle a real-time highlight of faces that z-fight: faces that lie
    in the same plane, face the same way and overlap, inside one object or
    between objects.
    Object Mode checks every mesh object visible in the viewport (Local
    View respected); Edit Mode checks every object being edited.
    In Front draws the highlight on top of all geometry.
    Shift-click: select those faces instead (Object Mode selects their
    objects and marks the faces for Edit Mode)"""
    bl_idname = "iops.mesh_zfight_overlay"
    bl_label = "Z-Fight Overlay"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        # Enabling needs Object or Edit Mesh mode; disabling works anywhere.
        return overlay_enabled() or context.mode in MODES

    def invoke(self, context, event):
        if not event.shift:
            return self.execute(context)
        if context.mode not in MODES:
            self.report({'WARNING'}, "Select z-fighting faces: Object or "
                                     "Edit Mode only")
            return {'CANCELLED'}
        total = select_flagged(context, flagged_faces(context), "Z-Fighting")
        report_selected(self, total)
        _tag_redraw_view3d(context)
        return {'FINISHED'}

    def execute(self, context):
        if overlay_enabled():
            disable_overlay()
            self.report({'INFO'}, "Z-Fight overlay: OFF")
        else:
            _enable()
            _STATE["view_area"] = view_area_pointer(context)
            _collect(context)
            self.report({'INFO'},
                        f"Z-Fight overlay: ON "
                        f"({_STATE['count']} z-fighting faces)")
        _tag_redraw_view3d(context)
        return {'FINISHED'}
