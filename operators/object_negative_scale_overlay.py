"""Negative Scale Overlay — sticky viewport mode that tints every visible
object whose scale is negative (red by default), including geometry
brought in through collection instances.

Toggle operator, not modal: module-level state owns one POST_VIEW handler
plus app handlers, same split as the Non-Planar overlay
(operators/mesh_nonplanar_overlay.py):

- App handlers (main thread, between evaluations) decide what is flagged
  and copy the EVALUATED mesh of each source object into CPU arrays in
  object local space. Geometry is keyed by source object, so every
  instance of a collection shares one copy, and it is re-read only when
  the depsgraph reports a geometry update for that object.
- The draw callback turns cached arrays into GPUBatches (needs the GPU
  context) and draws them at the live matrix of the object or instancer.

What is flagged:
- Direct objects: any local scale axis below zero OR a mirrored world
  matrix (determinant < 0), so children of mirrored parents count.
  Re-checked every redraw, so a flip back to positive clears instantly.
- Collection instances: every instanced object when the instancer itself
  is negative, and any object inside the collection (nested instances
  included) that is negative on its own. Moving an instancer or editing
  an instanced collection's members triggers a rescan (cheap — geometry
  is reused unless it changed).
"""
import bpy
import gpu
import numpy as np
from bpy.app.handlers import persistent
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix

from ..ui.draw import draw_scope, safe_handler_add, safe_handler_remove

# Object types `to_mesh()` can produce triangles for.
MESH_TYPES = {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'}

MAX_INSTANCE_DEPTH = 8  # nested collection instances; also a cycle guard

DEPTH_SHRINK = 0.002   # pull verts toward the eye by a fraction of their
                       # view depth so the fill wins the depth test against
                       # the object's own surface without shifting on screen

DEFAULT_COLOR = (1.0, 0.0, 0.0, 0.35)

_STATE = {
    "handle_view": None,   # POST_VIEW draw handle
    # source as_pointer() -> {"co", "tris", "batch", "dirty"}
    "geom": {},
    # direct flagged objects: as_pointer() -> name
    "direct": {},
    # instanced draws: (root_ptr, root_name, rel Matrix, source_ptr);
    # drawn at root.matrix_world @ rel
    "inst": [],
    # instancers and instanced-collection members: an update to any of
    # these needs a rescan, the incremental path can't place them
    "watch": set(),
}


_SHADER = None


def _get_shader():
    """Uniform-color shader with a clip-space depth bias. Lazy — creating
    shaders needs a GPU context, which background mode doesn't have."""
    global _SHADER
    if _SHADER is None:
        info = gpu.types.GPUShaderCreateInfo()
        info.vertex_in(0, 'VEC3', "pos")
        info.fragment_out(0, 'VEC4', "fragColor")
        info.push_constant('MAT4', "modelViewMat")
        info.push_constant('MAT4', "projMat")
        info.push_constant('VEC4', "color")
        info.push_constant('FLOAT', "depthShrink")
        info.vertex_source(
            "void main() {\n"
            "  vec4 vp = modelViewMat * vec4(pos, 1.0);\n"
            "  vp.xyz *= (1.0 - depthShrink);\n"
            "  gl_Position = projMat * vp;\n"
            "}\n")
        info.fragment_source(
            "void main() { fragColor = color; }\n")
        _SHADER = gpu.shader.create_from_info(info)
    return _SHADER


def overlay_enabled() -> bool:
    return _STATE["handle_view"] is not None


def is_negative_scale(obj) -> bool:
    s = obj.scale
    return (s[0] < 0.0 or s[1] < 0.0 or s[2] < 0.0
            or obj.matrix_world.determinant() < 0.0)


def _is_instancer(obj) -> bool:
    return (obj.instance_type == 'COLLECTION'
            and obj.instance_collection is not None)


def negative_scale_count() -> int:
    """Flagged objects + flagged instanced objects at the last collection."""
    return len(_STATE["direct"]) + len(_STATE["inst"])


def _color():
    try:
        return tuple(bpy.context.preferences.addons["InteractionOps"]
                     .preferences.negative_scale_color)
    except (KeyError, AttributeError):
        return DEFAULT_COLOR


def _app_handler_lists():
    h = bpy.app.handlers
    return (h.depsgraph_update_post, h.undo_post, h.redo_post, h.load_post)


def _read_geometry(obj, depsgraph):
    """Evaluated mesh → (local-space co float32 (N,3), tri indices int32
    (M,3)), or None. Bulk foreach_get only — no bmesh, same reasoning as
    the Non-Planar overlay (safe during edit-mode transform modals)."""
    ob_eval = obj.evaluated_get(depsgraph)
    try:
        me = ob_eval.to_mesh()
    except RuntimeError:
        return None
    if me is None:
        return None
    try:
        n_vert = len(me.vertices)
        if n_vert == 0 or len(me.polygons) == 0:
            return None
        co = np.empty(n_vert * 3, np.float32)
        me.vertices.foreach_get("co", co)
        me.calc_loop_triangles()
        n_tri = len(me.loop_triangles)
        tris = np.empty(n_tri * 3, np.int32)
        me.loop_triangles.foreach_get("vertices", tris)
        return co.reshape(-1, 3), tris.reshape(-1, 3)
    finally:
        ob_eval.to_mesh_clear()


def _ensure_geom(obj, depsgraph, old=None):
    """Cache `obj`'s geometry, reusing the entry from `old` when given.
    Returns True when the object has drawable geometry."""
    ptr = obj.as_pointer()
    geom = _STATE["geom"]
    if ptr in geom:
        return True
    if old is not None and ptr in old:
        geom[ptr] = old[ptr]
        return True
    data = _read_geometry(obj, depsgraph)
    if data is None:
        return False
    geom[ptr] = {"co": data[0], "tris": data[1], "batch": None,
                 "dirty": True}
    return True


def _walk_instances(root, coll, rel, root_neg, depth, depsgraph, old):
    """Flag the contents of `coll` instanced by top-level `root`. `rel` is
    the transform from root space to the collection's object space."""
    for o in coll.all_objects:
        _STATE["watch"].add(o.as_pointer())
        m = rel @ o.matrix_world
        neg = root_neg or is_negative_scale(o)
        if o.type in MESH_TYPES and neg and _ensure_geom(o, depsgraph, old):
            _STATE["inst"].append((root.as_pointer(), root.name, m,
                                   o.as_pointer()))
        if _is_instancer(o) and depth < MAX_INSTANCE_DEPTH:
            sub = o.instance_collection
            _walk_instances(root, sub,
                            m @ Matrix.Translation(-sub.instance_offset),
                            neg, depth + 1, depsgraph, old)


def _collect_all(context, depsgraph=None, changed=()):
    """Full rescan. Geometry from the previous pass is reused unless its
    source pointer is in `changed` (geometry-updated objects)."""
    old = {p: e for p, e in _STATE["geom"].items() if p not in changed}
    _STATE.update(geom={}, direct={}, inst=[], watch=set())
    view_layer = context.view_layer
    if view_layer is None:
        return
    if depsgraph is None:
        depsgraph = context.evaluated_depsgraph_get()
    for obj in view_layer.objects:
        neg = is_negative_scale(obj)
        if (obj.type in MESH_TYPES and neg
                and _ensure_geom(obj, depsgraph, old)):
            _STATE["direct"][obj.as_pointer()] = obj.name
        if _is_instancer(obj):
            _STATE["watch"].add(obj.as_pointer())
            coll = obj.instance_collection
            _walk_instances(obj, coll,
                            Matrix.Translation(-coll.instance_offset),
                            neg, 1, depsgraph, old)


def _collect_updates(context, depsgraph):
    """Incremental pass from depsgraph.updates. Scene/collection changes
    (add, delete, link, visibility) and anything touching a collection
    instance fall back to a full rescan."""
    updates = depsgraph.updates
    changed = set()
    rescan = False
    objs = []
    for u in updates:
        if isinstance(u.id, (bpy.types.Scene, bpy.types.Collection)):
            rescan = True
        elif isinstance(u.id, bpy.types.Object):
            if not (u.is_updated_transform or u.is_updated_geometry):
                continue
            obj = u.id.original
            ptr = obj.as_pointer()
            if u.is_updated_geometry:
                changed.add(ptr)
            if ptr in _STATE["watch"] or _is_instancer(obj):
                rescan = True
            objs.append((obj, ptr))
    if rescan:
        _collect_all(context, depsgraph, changed)
        return
    direct = _STATE["direct"]
    for obj, ptr in objs:
        if ptr in changed:
            _STATE["geom"].pop(ptr, None)
        if obj.type in MESH_TYPES and is_negative_scale(obj):
            if _ensure_geom(obj, depsgraph):
                direct[ptr] = obj.name
            else:
                direct.pop(ptr, None)
        else:
            direct.pop(ptr, None)


@persistent
def _on_change(scene=None, depsgraph=None, *_args):
    """depsgraph_update_post gets the depsgraph (incremental); undo/redo/
    load don't, and their pointers may all be stale — full rescan later,
    on a timer, once the new state has been evaluated."""
    if not overlay_enabled():
        return
    try:
        if isinstance(depsgraph, bpy.types.Depsgraph):
            _collect_updates(bpy.context, depsgraph)
        else:
            _STATE.update(geom={}, direct={}, inst=[], watch=set())
            _schedule_collect()
    except Exception as e:
        # A raising app handler gets called every depsgraph update.
        print("IOPS Negative Scale overlay: collect failed:", e)


_TIMER_PENDING = False


def _deferred_collect():
    """One-shot timer body: full rescan outside the draw callback."""
    global _TIMER_PENDING
    _TIMER_PENDING = False
    if overlay_enabled():
        try:
            _collect_all(bpy.context)
        except Exception as e:
            print("IOPS Negative Scale overlay: collect failed:", e)
        _tag_redraw_view3d(bpy.context)
    return None


def _schedule_collect():
    # Registering a timer is safe from the draw callback; its body runs
    # later on the main thread.
    global _TIMER_PENDING
    if not _TIMER_PENDING:
        _TIMER_PENDING = True
        bpy.app.timers.register(_deferred_collect)


def _resolve(objects, ptr, name):
    obj = objects.get(name)
    if obj is None or obj.as_pointer() != ptr:
        # Renamed or deleted since the last collection.
        _schedule_collect()
        return None
    return obj


def _batch_for(entry, shader):
    if entry["dirty"]:
        entry["dirty"] = False
        try:
            entry["batch"] = batch_for_shader(
                shader, 'TRIS', {"pos": entry["co"]}, indices=entry["tris"])
        except Exception as e:
            # Never raise from a draw handler — it repeats every redraw.
            print("IOPS Negative Scale overlay: batch build failed:", e)
            entry["batch"] = None
    return entry["batch"]


def _draw_view():
    geom = _STATE["geom"]
    if not _STATE["direct"] and not _STATE["inst"]:
        return
    context = bpy.context
    space = context.space_data
    objects = bpy.data.objects
    view = gpu.matrix.get_model_view_matrix()
    draws = []  # (geom entry, world matrix)
    for ptr, name in _STATE["direct"].items():
        obj = _resolve(objects, ptr, name)
        if (obj is None or ptr not in geom or not is_negative_scale(obj)
                or not obj.visible_get(viewport=space)):
            continue
        draws.append((geom[ptr], obj.matrix_world))
    roots = {}
    for root_ptr, root_name, rel, src in _STATE["inst"]:
        if root_ptr not in roots:
            root = _resolve(objects, root_ptr, root_name)
            roots[root_ptr] = (root if root is not None
                               and root.visible_get(viewport=space)
                               else None)
        root = roots[root_ptr]
        if root is None or src not in geom:
            continue
        draws.append((geom[src], root.matrix_world @ rel))
    if not draws:
        return
    shader = _get_shader()
    with draw_scope(blend='ALPHA', depth='LESS_EQUAL', depth_mask=False):
        shader.bind()
        shader.uniform_float("projMat", gpu.matrix.get_projection_matrix())
        shader.uniform_float("color", _color())
        shader.uniform_float("depthShrink", DEPTH_SHRINK)
        for entry, mw in draws:
            batch = _batch_for(entry, shader)
            if batch is None:
                continue
            shader.uniform_float("modelViewMat", view @ mw)
            batch.draw(shader)


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
    _STATE.update(handle_view=None, geom={}, direct={}, inst=[], watch=set())


def _tag_redraw_view3d(context):
    wm = getattr(context, "window_manager", None)
    if wm is None:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


class IOPS_OT_ObjectNegativeScaleOverlay(bpy.types.Operator):
    """Toggle a viewport highlight of objects with negative scale
    (mirrored), including children of mirrored parents and geometry in
    collection instances"""
    bl_idname = "iops.object_negative_scale_overlay"
    bl_label = "Negative Scale Overlay"
    bl_options = {"REGISTER"}

    def execute(self, context):
        if overlay_enabled():
            disable_overlay()
            self.report({'INFO'}, "Negative Scale overlay: OFF")
        else:
            _enable()
            _collect_all(context)
            self.report({'INFO'},
                        f"Negative Scale overlay: ON "
                        f"({negative_scale_count()} negative)")
        _tag_redraw_view3d(context)
        return {'FINISHED'}
