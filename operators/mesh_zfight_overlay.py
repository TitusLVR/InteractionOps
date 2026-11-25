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
utils/zfight_core.py) is incremental: results are cached per object (its
own conflicts, keyed by its mesh version and matrix) and per pair of
objects whose world boxes come within the distance tolerance (their cross
conflicts, keyed by both), so moving one object re-checks only that
object and its neighbours. The flagged set is exactly the one of a single
whole-scope soup (see the core's docstring).

When collection runs is `Refresh`'s job (shared with the Hidden Faces
overlay): `bpy.app.handlers` hooks report changes, and a change re-collects
at once only while the last detection was cheap, so light scenes stay live
during a transform; on heavy scenes the last result stays drawn and the
highlight refreshes when the movement stops. The draw callback turns the
cached CPU arrays into a GPUBatch. The `Z-Fight: N` counter is a row in
the iOps statistics overlay (utils/draw_stats.py), which reads it via
`zfight_count()`.
"""
import math
import time

import bpy
import gpu
import numpy as np
from bpy.app.handlers import persistent
from gpu_extras.batch import batch_for_shader

from ..ui.draw import (Role, draw_scope, get_theme,
                       safe_handler_add, safe_handler_remove)
from ..utils.planarity import overlay_normal_offset
from ..utils.overlay_select import report_selected, select_flagged
from ..utils.zfight_core import (candidate_pairs, cross_pair_faces,
                                 degenerate_floor, tri_double_areas,
                                 triangle_boxes, zfight_faces)
# Same depth-shrink fill shader as the Non-Planar overlay.
from .mesh_nonplanar_overlay import DEPTH_SHRINK, _get_shader

FILL_ALPHA = 0.5
MODES = ('OBJECT', 'EDIT_MESH')

# A change re-collects at once while the last detection took less than
# this (seconds); slower ones wait until changes stop for SETTLE_DELAY.
LIVE_BUDGET = 0.015
SETTLE_DELAY = 0.2
# The draw-time scope check walks every view-layer object: at most this
# often (seconds).
SCOPE_CHECK_INTERVAL = 0.25

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
    # Incremental detection, current scope only (rebuilt every run):
    "world": {},            # pointer -> ((version, matrix), world data)
    "self_hits": {},        # pointer -> (key, own flagged polygons, secs)
    "pair_hits": {},        # (pointer, pointer) -> (key, hits a, b, secs)
    "fills": {},            # pointer -> (key, fill geometry or None)
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
        tri_verts = entry["tri_verts"]
        if np.linalg.det(mw[:3, :3]) < 0.0:
            # A mirrored object (negative scale) reverses the winding in
            # world space while Blender still shows the faces the same way
            # round; the detection derives normals from the winding.
            tri_verts = tri_verts[:, ::-1]
        tri_parts.append(tri_verts + v_off)
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
            and not entry.get("stale")):
        return entry
    new = _read_entry(obj, depsgraph, edit_mode)
    # Same content (a pure re-evaluation, an undo step that left this mesh
    # alone): keep the version, so results cached by it stay valid.
    if entry is not None and _same_content(entry, new):
        new["version"] = entry["version"]
    else:
        _VERSION[0] += 1
        new["version"] = _VERSION[0]
    cache[ptr] = new
    return new


def invalidate_entries(cache, changed_objects=None, changed_meshes=()):
    """Mark cache entries stale (kept for the same-content check): those of
    `changed_objects` / `changed_meshes` pointers, every one with None.
    A stale entry is re-read before use and keeps its version only when
    the new content is identical, so results cached by version are reused
    for unchanged meshes. Pointers are only compared, never dereferenced,
    so this is safe after undo or a file load too."""
    meshes = set(changed_meshes)
    for ptr, entry in cache.items():
        if (changed_objects is None or ptr in changed_objects
                or entry["data_ptr"] in meshes):
            entry["stale"] = True


def scan_updates(depsgraph):
    """(changed, scope, objects, meshes) from a depsgraph update, without
    touching any object that did not change:
    changed: a mesh object moved or a mesh object / mesh got new geometry;
    scope: something that can change the scope did (selection, hiding,
    collections, adding or deleting objects all come as Scene, Collection
    or flag-only Object updates);
    objects, meshes: original pointers with new geometry."""
    changed = scope = False
    objects = set()
    meshes = set()
    for u in depsgraph.updates:
        idv = u.id
        if isinstance(idv, bpy.types.Object):
            if idv.type != 'MESH':
                continue
            if u.is_updated_geometry:
                objects.add(idv.original.as_pointer())
                changed = True
            elif u.is_updated_transform:
                changed = True
            else:
                scope = True
        elif isinstance(idv, bpy.types.Mesh):
            if u.is_updated_geometry:
                meshes.add(idv.original.as_pointer())
                changed = True
        elif isinstance(idv, (bpy.types.Scene, bpy.types.Collection)):
            scope = True
    return changed, scope, objects, meshes


class Refresh:
    """When an overlay re-collects; one instance per overlay (Z-Fight,
    Hidden Faces).

    - A change reported by an app handler (`request`) re-collects at once
      while a full detection of the scope takes less than LIVE_BUDGET, so
      light scenes stay live during a transform. Otherwise it only pushes back a
      one-shot timer that re-collects once no change came for
      SETTLE_DELAY; the last result stays drawn meanwhile, then is
      swapped. A transform step then costs the handler microseconds.
    - Scope and preference changes (`soon`) re-collect on the next timer
      tick, whatever the cost: they are single user actions.
    - The draw callback (`draw_check`) compares mode and preferences every
      redraw (cheap) and walks the scope at most every
      SCOPE_CHECK_INTERVAL; a skipped walk is made up by the timer, so a
      change never waits for another redraw.
    The timer redraws every 3D viewport after re-collecting."""

    def __init__(self, label, state, collect, scope_key, params):
        self.label = label
        self.state = state          # the overlay's _STATE
        # collect(context, depsgraph): None/False when nothing ran, True
        # when a full detection ran, else the estimated seconds of one.
        self.collect = collect
        self.scope_key = scope_key  # context -> key as _collect stores it
        self.params = params        # () -> the overlay's preferences
        self._timer = self._tick    # one object for bpy.app.timers calls
        self.reset()

    def reset(self):
        self.cost = 0.0             # seconds a full detection takes
        self.due = None             # perf_counter time of the next collect
        self.check_due = None       # time of a postponed scope walk
        self.checked = -math.inf    # time of the last scope walk
        if bpy.app.timers.is_registered(self._timer):
            bpy.app.timers.unregister(self._timer)

    def run(self, context, depsgraph=None):
        """Collect now; remember what a full detection costs."""
        t = time.perf_counter()
        try:
            ran = self.collect(context, depsgraph)
        except Exception as e:
            # A raising app handler or timer repeats on every call.
            print(f"IOPS {self.label} overlay: collect failed:", e)
            return
        if ran is None or ran is False:
            return
        spent = time.perf_counter() - t
        self.cost = spent if ran is True else max(spent, ran)

    def request(self, context, depsgraph=None):
        """Something the overlay reads changed (app handler)."""
        if self.cost < LIVE_BUDGET:
            self.run(context, depsgraph)
            return
        self.due = time.perf_counter() + SETTLE_DELAY
        if not bpy.app.timers.is_registered(self._timer):
            bpy.app.timers.register(self._timer, first_interval=SETTLE_DELAY)

    def soon(self):
        """Re-collect on the next timer tick. Registering a timer is safe
        from the draw callback; its body runs later on the main thread."""
        now = time.perf_counter()
        registered = bpy.app.timers.is_registered(self._timer)
        if registered and self.due is not None and self.due <= now:
            return   # already queued for the next tick
        self.due = now
        if registered:
            # (A file load drops timers: `due` alone proves nothing.)
            bpy.app.timers.unregister(self._timer)
        bpy.app.timers.register(self._timer, first_interval=0.0)

    def check_scope(self, context, now=None):
        """Walk the scope; re-collect soon when it changed."""
        self.checked = time.perf_counter() if now is None else now
        if self.scope_key(context) != self.state["scope_key"]:
            self.soon()

    def draw_check(self, context):
        key = self.state["scope_key"]
        if (key is None or key[0] != context.mode
                or key[2] != self.params()):
            self.soon()
            return
        now = time.perf_counter()
        if now - self.checked >= SCOPE_CHECK_INTERVAL:
            self.check_scope(context, now)
        elif (self.check_due is None
              or not bpy.app.timers.is_registered(self._timer)):
            self.check_due = self.checked + SCOPE_CHECK_INTERVAL
            if not bpy.app.timers.is_registered(self._timer):
                bpy.app.timers.register(
                    self._timer, first_interval=max(self.check_due - now, 0.0))

    def _tick(self):
        if self.state["handle_view"] is None:
            self.due = self.check_due = None
            return None
        context = bpy.context
        now = time.perf_counter()
        if self.check_due is not None and now >= self.check_due - 1e-3:
            self.check_due = None
            if context.mode in MODES:
                self.check_scope(context, now)
        if self.due is not None and now >= self.due - 1e-3:
            self.due = None
            if context.mode in MODES:
                self.run(context)
                _tag_redraw_view3d(context)
        now = time.perf_counter()
        waits = [t - now for t in (self.due, self.check_due) if t is not None]
        return max(min(waits), 0.0) if waits else None


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


def scope_items(context, objs, depsgraph, entry_for, cache):
    """[(pointer, entry, matrix_world)] of the scoped objects with faces,
    entries from `cache` (re-read when stale). Bounds the cache: entries of
    objects that left the scene or the scope are dropped once it holds
    many more than the scope."""
    if depsgraph is None:
        depsgraph = context.evaluated_depsgraph_get()
    edit_mode = context.mode == 'EDIT_MESH'
    items = []
    for obj in objs:
        entry = entry_for(obj, depsgraph, edit_mode)
        if entry["n_poly"]:
            items.append((obj.as_pointer(), entry,
                          np.array(obj.matrix_world, np.float64)))
    live = {o.as_pointer() for o in objs}
    if len(cache) > 4 * max(len(live), 64):
        for ptr in [p for p in cache if p not in live]:
            del cache[ptr]
    return items


def _world_data(entry, mw):
    """One object's world-space soup and what detection needs of it."""
    soup = world_soup([(entry, mw)])
    tri_vis = soup["visible"][soup["tri_poly"]]
    tv = soup["tri_verts"][tri_vis]
    return {"soup": soup, "tv": tv, "tp": soup["tri_poly"][tri_vis],
            "dbl": tri_double_areas(soup["co"], tv),
            "box": triangle_boxes(soup["co"], tv),
            "lo": soup["co"].min(axis=0), "hi": soup["co"].max(axis=0)}


def _detect(items, params):
    """[(pointer, entry, matrix)] -> (per item: its world data, its
    flagged local polygon indices; the seconds a detection of every part
    from scratch takes, from each part's own last timing). The union of each object's own
    conflicts and the cross conflicts of every pair of objects whose boxes
    come within the distance: exactly the whole soup's result (same
    zero-area floor, from the whole scope's extent). Every part is cached
    by what it reads; the caches keep only the current scope."""
    angle, distance = params
    old_world = _STATE["world"]
    old_self = _STATE["self_hits"]
    old_pair = _STATE["pair_hits"]
    world, selfs, pairs = {}, {}, {}
    wds = []
    keys = []
    for ptr, entry, mw in items:
        key = (entry["version"], mw.tobytes())
        hit = old_world.get(ptr)
        wd = hit[1] if hit is not None and hit[0] == key else (
            _world_data(entry, mw))
        world[ptr] = (key, wd)
        wds.append(wd)
        keys.append(key)
    los = np.array([wd["lo"] for wd in wds])
    his = np.array([wd["hi"] for wd in wds])
    floor = degenerate_floor(float((his.max(axis=0) - los.min(axis=0)).max()))
    # Triangles at or below the floor are dropped. The floor follows the
    # whole scope's extent; the count of triangles above it decides
    # whether a cached result (computed with another floor) still holds.
    kept = [int(np.count_nonzero(wd["dbl"] > floor)) for wd in wds]
    flagged = [[] for _ in items]
    full = 0.0
    for k, (ptr, _entry, _mw) in enumerate(items):
        key = (keys[k], kept[k], params)
        hit = old_self.get(ptr)
        if hit is not None and hit[0] == key:
            hits, secs = hit[1], hit[2]
        else:
            wd = wds[k]
            t = time.perf_counter()
            hits = zfight_faces(wd["soup"]["co"], wd["tv"], wd["tp"],
                                angle, distance, area_floor=floor)
            secs = time.perf_counter() - t
        selfs[ptr] = (key, hits, secs)
        full += secs
        if len(hits):
            flagged[k].append(hits)
    pad = max(float(distance), 0.0)
    ia, ib = candidate_pairs(los - pad, his + pad)
    for a, b in zip(ia.tolist(), ib.tolist()):
        if items[a][0] > items[b][0]:
            a, b = b, a     # key by pointer order, not scope order
        pkey = (items[a][0], items[b][0])
        key = (keys[a], kept[a], keys[b], kept[b], params)
        hit = old_pair.get(pkey)
        if hit is not None and hit[0] == key:
            ha, hb, secs = hit[1], hit[2], hit[3]
        else:
            wa, wb = wds[a], wds[b]
            t = time.perf_counter()
            ha, hb = cross_pair_faces(
                wa["soup"]["co"], wa["tv"], wa["tp"],
                wb["soup"]["co"], wb["tv"], wb["tp"], angle, distance, floor,
                box_a=wa["box"], box_b=wb["box"])
            secs = time.perf_counter() - t
        pairs[pkey] = (key, ha, hb, secs)
        full += secs
        if len(ha):
            flagged[a].append(ha)
        if len(hb):
            flagged[b].append(hb)
    _STATE["world"] = world
    _STATE["self_hits"] = selfs
    _STATE["pair_hits"] = pairs
    none = np.empty(0, np.int64)
    return wds, [np.unique(np.concatenate(f)) if f else none
                 for f in flagged], full


def _collect(context, depsgraph=None):
    """Read the scoped objects, detect, cache CPU arrays. Main-thread,
    between-evaluations contexts only (operator execute, app handlers,
    timers) — and never via bmesh. None when nothing changed, else the
    estimated seconds of a full (uncached) detection, for `Refresh`."""
    mode = context.mode
    if _STATE["cache_mode"] != mode:
        _STATE["cache"] = {}
        _STATE["cache_mode"] = mode
    objs = _overlay_scope(context)
    params = _params()
    _STATE["scope_key"] = _scope_key(context, objs)
    if not objs:
        _clear_result()
        return None
    items = scope_items(context, objs, depsgraph, _entry_for, _STATE["cache"])
    rgb = tuple(get_theme(context).color_for(Role.ERROR_LINE)[:3])
    # Selection clicks, view changes and unrelated edits also fire
    # depsgraph updates; skip detection when nothing it reads changed.
    signature = (mode, params, rgb,
                 tuple((p, e["version"], mw.tobytes()) for p, e, mw in items))
    if signature == _STATE["signature"]:
        return None
    _STATE["signature"] = signature
    _STATE["batch_dirty"] = True
    if not items:
        _STATE.update(geom=None, count=0, world={}, self_hits={},
                      pair_hits={}, fills={})
        return 0.0
    wds, flagged, full = _detect(items, params)
    # Fill triangles per object, cached by what they read; concatenated in
    # scope order they equal the whole soup's fill.
    old_fills = _STATE["fills"]
    fills = {}
    parts = []
    count = 0
    for (ptr, _entry, _mw), wd, hits in zip(items, wds, flagged):
        count += len(hits)
        if not len(hits):
            continue
        key = (_STATE["world"][ptr][0], hits.tobytes(), rgb)
        hit = old_fills.get(ptr)
        geom = hit[1] if hit is not None and hit[0] == key else (
            fill_geometry(wd["soup"], hits, rgb, FILL_ALPHA))
        fills[ptr] = (key, geom)
        if geom is not None:
            parts.append(geom)
    _STATE["fills"] = fills
    _STATE["count"] = count
    _STATE["geom"] = ((np.concatenate([g[0] for g in parts]),
                       np.concatenate([g[1] for g in parts]))
                      if parts else None)
    return full


@persistent
def _on_change(scene=None, depsgraph=None, *_args):
    """depsgraph_update_post gets the depsgraph: only the changes it lists
    are looked at (a transform step lists the moved objects), so updates
    that change nothing the overlay reads cost next to nothing. It fires
    per mouse move during transform modals; `Refresh` decides whether that
    re-collects live or once the movement stops. Undo/redo/load pass no
    depsgraph and any pointer may be stale: every entry is re-read."""
    if not overlay_enabled():
        return
    context = bpy.context
    if context.mode not in MODES:
        return
    try:
        if isinstance(depsgraph, bpy.types.Depsgraph):
            changed, scope, objects, meshes = scan_updates(depsgraph)
            if objects or meshes:
                invalidate_entries(_STATE["cache"], objects, meshes)
            if changed:
                _REFRESH.request(context, depsgraph)
            if scope:
                # Hiding, adding, deleting: re-collect soon, not deferred.
                _REFRESH.check_scope(context)
        else:
            invalidate_entries(_STATE["cache"])
            _REFRESH.request(context)
    except Exception as e:
        # A raising app handler gets called every depsgraph update.
        print("IOPS Z-Fight overlay: collect failed:", e)


def _cache_stale(context) -> bool:
    """Scope (mode, viewport visibility, objects) or prefs changed."""
    return _scope_key(context, _overlay_scope(context)) != _STATE["scope_key"]


_REFRESH = Refresh("Z-Fight", _STATE, _collect,
                   lambda context: _scope_key(context, _overlay_scope(context)),
                   _params)


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
    _REFRESH.draw_check(context)
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
    _REFRESH.reset()
    _STATE.update(handle_view=None, geom=None, batch_dirty=False,
                  batch=None, count=0, scope_key=None, signature=None,
                  cache={}, cache_mode=None, view_area=None, world={},
                  self_hits={}, pair_hits={}, fills={})


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
            _REFRESH.run(context)
            self.report({'INFO'},
                        f"Z-Fight overlay: ON "
                        f"({_STATE['count']} z-fighting faces)")
        _tag_redraw_view3d(context)
        return {'FINISHED'}
