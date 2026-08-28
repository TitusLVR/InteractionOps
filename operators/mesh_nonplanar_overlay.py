"""Non-Planar Faces Overlay — sticky edit-mesh mode that highlights
non-planar quads/ngons in real time.

Toggle operator, not modal: module-level state owns one POST_VIEW handler
(deviation-tinted face fills, cached GPU batch).

The overlay NEVER touches the edit-bmesh, and that is load-bearing: any
Python bmesh element access adds/removes a CD_BM_ELEM_PYPTR customdata
layer under the hood (BM_data_layer_add via BPy_BMLoop_Array_As_Tuple),
which reallocs the customdata pools that a running transform modal (G-G
vert slide's UV correction, etc.) holds cached pointers into — silent
heap corruption, crash a few slides later (confirmed via crash-dump
symbolication against blender.pdb, Blender 5.2). It reads the EVALUATED
mesh instead: `obj.evaluated_get(depsgraph).to_mesh()` exposes plain
Mesh arrays through `foreach_get` bulk copies — no per-element
PyObjects, no customdata mutation, and it reflects the in-progress
transform because it is what the viewport renders. (to_mesh(), not
`.data`: in edit mode the evaluated `.data` is a bmesh-backed wrapper
whose Mesh arrays are empty.)

Geometry collection runs in `bpy.app.handlers` hooks (per mouse move
during transforms — that's what keeps the highlight live while sliding)
and caches CPU vertex/color arrays; the draw callback only turns those
into a GPUBatch (needs the GPU context draw callbacks provide) and draws.
The `Non-Planar: N` counter is a row in the iOps statistics overlay
(utils/draw_stats.py), which reads it via `nonplanar_count()`.
"""
import bpy
import gpu
import numpy as np
from bpy.app.handlers import persistent
from gpu_extras.batch import batch_for_shader

from ..ui.draw import (Role, draw_scope, get_theme,
                       safe_handler_add, safe_handler_remove)
from ..utils.planarity import (deviation_alpha, face_deviation_deg,
                               overlay_normal_offset)

DEPTH_SHRINK = 0.005   # pull verts toward the eye by 0.5% of their view
                       # depth: scales with distance (a fixed world offset
                       # falls below depth precision on large/far meshes)
                       # and shifts nothing on screen — points move along
                       # their own view ray

_STATE = {
    "handle_view": None,    # POST_VIEW draw handle
    "geom": None,           # (pos, col) float32 arrays from last collection
    "batch_dirty": False,   # geom changed; draw callback rebuilds the batch
    "batch": None,          # (shader, GPUBatch) or None
    "count": 0,             # non-planar faces at last collection
    "obj_ptr": 0,           # as_pointer() of the object last collected
    "threshold": None,      # threshold used at last collection
}


_SHADER = None


def _get_shader():
    """SMOOTH_COLOR clone with a clip-space depth bias. Lazy — creating
    shaders needs a GPU context, which background mode doesn't have."""
    global _SHADER
    if _SHADER is None:
        info = gpu.types.GPUShaderCreateInfo()
        info.vertex_in(0, 'VEC3', "pos")
        info.vertex_in(1, 'VEC4', "color")
        iface = gpu.types.GPUStageInterfaceInfo("iops_nonplanar_iface")
        iface.smooth('VEC4', "fcol")
        info.vertex_out(iface)
        info.fragment_out(0, 'VEC4', "fragColor")
        info.push_constant('MAT4', "viewMat")
        info.push_constant('MAT4', "projMat")
        info.push_constant('FLOAT', "depthShrink")
        info.vertex_source(
            "void main() {\n"
            "  vec4 vp = viewMat * vec4(pos, 1.0);\n"
            "  vp.xyz *= (1.0 - depthShrink);\n"
            "  gl_Position = projMat * vp;\n"
            "  fcol = color;\n"
            "}\n")
        info.fragment_source(
            "void main() { fragColor = fcol; }\n")
        _SHADER = gpu.shader.create_from_info(info)
    return _SHADER


def overlay_enabled() -> bool:
    return _STATE["handle_view"] is not None


def _app_handler_lists():
    h = bpy.app.handlers
    return (h.depsgraph_update_post, h.undo_post, h.redo_post, h.load_post)


def _threshold_deg() -> float:
    try:
        return float(bpy.context.preferences.addons["InteractionOps"]
                     .preferences.nonplanar_angle)
    except (KeyError, AttributeError):
        return 0.5


def _collect(context, depsgraph=None):
    """Evaluated-mesh walk into CPU vertex/color arrays. Main-thread,
    between-evaluations contexts only (operator execute, app handlers,
    timers) — and per the module docstring, never via bmesh."""
    _STATE["geom"] = None
    _STATE["count"] = 0
    _STATE["batch_dirty"] = True
    obj = context.edit_object
    if obj is None or obj.type != 'MESH':
        return
    threshold = _threshold_deg()
    _STATE["threshold"] = threshold
    _STATE["obj_ptr"] = obj.as_pointer()
    if depsgraph is None:
        depsgraph = context.evaluated_depsgraph_get()
    ob_eval = obj.evaluated_get(depsgraph)
    # In edit mode the evaluated `.data` is a bmesh-backed wrapper whose
    # Mesh arrays are EMPTY; to_mesh() forces the native bmesh→Mesh
    # conversion (still no Python bmesh wrappers involved).
    me = ob_eval.to_mesh()
    try:
        _collect_from_mesh(context, obj, me, threshold)
    finally:
        ob_eval.to_mesh_clear()


def _collect_from_mesh(context, obj, me, threshold):
    n_poly = len(me.polygons)
    if n_poly == 0:
        return
    loop_total = np.empty(n_poly, np.int32)
    me.polygons.foreach_get("loop_total", loop_total)
    cand_mask = loop_total > 3
    hide = me.attributes.get(".hide_poly")
    if hide is not None and hide.domain == 'FACE':
        hidden = np.empty(n_poly, bool)
        hide.data.foreach_get("value", hidden)
        cand_mask &= ~hidden
    cand = np.nonzero(cand_mask)[0]
    if not len(cand):
        return
    loop_start = np.empty(n_poly, np.int32)
    me.polygons.foreach_get("loop_start", loop_start)
    loop_verts = np.empty(len(me.loops), np.int32)
    me.loops.foreach_get("vertex_index", loop_verts)
    co = np.empty(len(me.vertices) * 3, np.float64)
    me.vertices.foreach_get("co", co)
    mw = np.array(obj.matrix_world, dtype=np.float64)
    # World space so non-uniform object scale is measured the way the
    # user sees it.
    co_w = co.reshape(-1, 3) @ mw[:3, :3].T + mw[:3, 3]
    hit_devs = {}
    for pi in cand:
        s = loop_start[pi]
        coords = co_w[loop_verts[s:s + loop_total[pi]]]
        dev = face_deviation_deg(coords)
        if dev > threshold:
            hit_devs[int(pi)] = dev
    _STATE["count"] = len(hit_devs)
    if not hit_devs:
        return
    # Fill with the mesh's own render tessellation (loop triangles) — a
    # generic tessellator can pick the opposite diagonal on a warped face,
    # and two differently-diagonalized saddles intersect mid-face, which
    # z-fights at any offset.
    me.calc_loop_triangles()
    n_tri = len(me.loop_triangles)
    tri_verts = np.empty(n_tri * 3, np.int32)
    me.loop_triangles.foreach_get("vertices", tri_verts)
    tri_poly = np.empty(n_tri, np.int32)
    me.loop_triangles.foreach_get("polygon_index", tri_poly)
    hit_ids = np.fromiter(hit_devs, np.int32, len(hit_devs))
    tri_sel = np.nonzero(np.isin(tri_poly, hit_ids))[0]
    if not len(tri_sel):
        return
    normals = np.empty(n_poly * 3, np.float64)
    me.polygons.foreach_get("normal", normals)
    normals = normals.reshape(-1, 3)
    try:
        inv3 = np.linalg.inv(mw[:3, :3])
    except np.linalg.LinAlgError:
        inv3 = np.zeros((3, 3))
    world_n = normals @ inv3  # row-vector form of (M^-1)^T @ n
    lens = np.linalg.norm(world_n, axis=1, keepdims=True)
    np.divide(world_n, lens, out=world_n, where=lens > 0.0)
    theme = get_theme(context)
    r, g, b, _a = theme.color_for(Role.ERROR_LINE)
    alpha_by_poly = np.zeros(n_poly, np.float64)
    for pi, dev in hit_devs.items():
        alpha_by_poly[pi] = deviation_alpha(dev, threshold)
    sel_poly = tri_poly[tri_sel]
    pos = co_w[tri_verts.reshape(-1, 3)[tri_sel].ravel()]
    # Push relative to mesh size — a fixed world offset visibly floats
    # above small objects.
    diag = float(np.linalg.norm(co_w.max(axis=0) - co_w.min(axis=0)))
    pos += np.repeat(world_n[sel_poly] * overlay_normal_offset(diag),
                     3, axis=0)
    col = np.empty((len(pos), 4), np.float64)
    col[:, 0] = r
    col[:, 1] = g
    col[:, 2] = b
    col[:, 3] = np.repeat(alpha_by_poly[sel_poly], 3)
    _STATE["geom"] = (pos.astype(np.float32), col.astype(np.float32))


@persistent
def _on_change(scene=None, depsgraph=None, *_args):
    """depsgraph_update_post / undo_post / redo_post / load_post. Fires per
    mouse move during transform modals, which is what keeps the overlay
    live while sliding."""
    if not overlay_enabled():
        return
    context = bpy.context
    if context.mode != 'EDIT_MESH':
        return
    try:
        _collect(context, depsgraph if isinstance(
            depsgraph, bpy.types.Depsgraph) else None)
    except Exception as e:
        # A raising app handler gets called every depsgraph update.
        print("IOPS Non-Planar overlay: collect failed:", e)


_TIMER_PENDING = False


def _deferred_collect():
    """One-shot timer body: re-collect outside the draw callback for
    changes no app handler reports (threshold pref, active-object swap)."""
    global _TIMER_PENDING
    _TIMER_PENDING = False
    if overlay_enabled():
        context = bpy.context
        if context.mode == 'EDIT_MESH':
            _collect(context)
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
    obj = context.edit_object
    return (obj.as_pointer() != _STATE["obj_ptr"]
            or _threshold_deg() != _STATE["threshold"])


def _build_batch():
    """GPU side of the split: cached CPU arrays → GPUBatch. Draw-callback
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
    if context.mode != 'EDIT_MESH':
        return
    obj = context.edit_object
    if obj is None or obj.type != 'MESH':
        return
    if _cache_stale(context):
        _schedule_collect()
    if _STATE["batch_dirty"]:
        try:
            _build_batch()
        except Exception as e:
            # Never raise from a draw handler — it repeats every redraw.
            print("IOPS Non-Planar overlay: batch build failed:", e)
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


def nonplanar_count() -> int:
    """Non-planar face count at the last collection — read by the iOps
    statistics overlay for its Non-Planar row."""
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
                  batch=None, count=0, obj_ptr=0, threshold=None)


def _tag_redraw_view3d(context):
    screen = getattr(context, "screen", None)
    if screen is None:
        return
    for area in screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()


class IOPS_OT_MeshNonPlanarOverlay(bpy.types.Operator):
    """Toggle a real-time highlight of non-planar faces in Edit Mode.
    Fill intensity scales with how far each face is from planar"""
    bl_idname = "iops.mesh_nonplanar_overlay"
    bl_label = "Non-Planar Faces Overlay"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        # Enabling needs an edit-mesh; disabling is allowed from anywhere.
        return overlay_enabled() or (context.mode == 'EDIT_MESH'
                                     and context.edit_object is not None)

    def execute(self, context):
        if overlay_enabled():
            disable_overlay()
            self.report({'INFO'}, "Non-Planar overlay: OFF")
        else:
            _enable()
            _collect(context)
            self.report({'INFO'},
                        f"Non-Planar overlay: ON "
                        f"({_STATE['count']} non-planar)")
        _tag_redraw_view3d(context)
        return {'FINISHED'}
