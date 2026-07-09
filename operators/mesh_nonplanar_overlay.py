"""Non-Planar Faces Overlay — sticky edit-mesh mode that highlights
non-planar quads/ngons in real time.

Toggle operator, not modal: module-level state owns one POST_VIEW handler
(deviation-tinted face fills, cached GPU batch) and one POST_PIXEL handler
(`Non-Planar: N` corner label). `bpy.app.handlers` hooks only set a dirty
flag; the batch rebuilds lazily inside the draw callback, so orbit/pan
redraws cost one `batch.draw()`.
"""
import bpy
import bmesh
import gpu
from bpy.app.handlers import persistent
from gpu_extras.batch import batch_for_shader
from mathutils import Vector
from mathutils.geometry import tessellate_polygon

from ..ui.draw import (Role, draw_scope, get_theme,
                       safe_handler_add, safe_handler_remove)
from ..ui.hud import text as hud_text
from ..utils.planarity import deviation_alpha, face_deviation_deg

NORMAL_OFFSET = 0.002  # world-space push along the face normal (z-fight)
LABEL_X = 20
LABEL_Y_FROM_TOP = 60

_STATE = {
    "handle_view": None,    # POST_VIEW draw handle
    "handle_pixel": None,   # POST_PIXEL draw handle
    "batch": None,          # (shader, GPUBatch) or None
    "count": 0,             # non-planar faces at last rebuild
    "dirty": True,
    "obj_ptr": 0,           # as_pointer() of the object last built
    "threshold": None,      # threshold used at last rebuild
}


def overlay_enabled() -> bool:
    return _STATE["handle_view"] is not None


@persistent
def _mark_dirty(*_args):
    _STATE["dirty"] = True


def _app_handler_lists():
    h = bpy.app.handlers
    return (h.depsgraph_update_post, h.undo_post, h.redo_post, h.load_post)


def _threshold_deg() -> float:
    try:
        return float(bpy.context.preferences.addons["InteractionOps"]
                     .preferences.nonplanar_angle)
    except (KeyError, AttributeError):
        return 0.5


def collect_nonplanar(bm, matrix_world, threshold_deg):
    """[(face, deviation_deg, world_coords)] for visible non-planar
    quads/ngons. World space so non-uniform object scale is measured the
    way the user sees it."""
    out = []
    for f in bm.faces:
        if len(f.verts) <= 3 or f.hide:
            continue
        coords = [tuple(matrix_world @ v.co) for v in f.verts]
        dev = face_deviation_deg(coords)
        if dev > threshold_deg:
            out.append((f, dev, coords))
    return out


def _rebuild(context):
    _STATE["batch"] = None
    _STATE["count"] = 0
    _STATE["dirty"] = False
    obj = context.edit_object
    if obj is None or obj.type != 'MESH':
        return
    threshold = _threshold_deg()
    _STATE["threshold"] = threshold
    _STATE["obj_ptr"] = obj.as_pointer()
    try:
        bm = bmesh.from_edit_mesh(obj.data)
    except (ValueError, ReferenceError):
        return
    hits = collect_nonplanar(bm, obj.matrix_world, threshold)
    _STATE["count"] = len(hits)
    if not hits:
        return
    theme = get_theme(context)
    r, g, b, _a = theme.color_for(Role.ERROR_LINE)
    normal_mat = obj.matrix_world.inverted_safe().transposed().to_3x3()
    pos, col = [], []
    for f, dev, coords in hits:
        alpha = deviation_alpha(dev, threshold)
        world_n = (normal_mat @ f.normal)
        world_n = (world_n.normalized() if world_n.length_squared > 0.0
                   else Vector((0.0, 0.0, 0.0)))
        offset = world_n * NORMAL_OFFSET
        pts = [Vector(c) + offset for c in coords]
        rgba = (r, g, b, alpha)
        for i0, i1, i2 in tessellate_polygon([pts]):
            pos.extend((pts[i0], pts[i1], pts[i2]))
            col.extend((rgba, rgba, rgba))
    shader = gpu.shader.from_builtin('SMOOTH_COLOR')
    _STATE["batch"] = (shader,
                       batch_for_shader(shader, 'TRIS',
                                        {"pos": pos, "color": col}))


def _needs_rebuild(context) -> bool:
    obj = context.edit_object
    return (_STATE["dirty"]
            or obj.as_pointer() != _STATE["obj_ptr"]
            or _threshold_deg() != _STATE["threshold"])


def _draw_view():
    context = bpy.context
    if context.mode != 'EDIT_MESH':
        return
    obj = context.edit_object
    if obj is None or obj.type != 'MESH':
        return
    if _needs_rebuild(context):
        try:
            _rebuild(context)
        except Exception as e:
            # Never raise from a draw handler — it repeats every redraw.
            print("IOPS Non-Planar overlay: rebuild failed:", e)
            _STATE["batch"] = None
            _STATE["dirty"] = False
    if _STATE["batch"] is None:
        return
    shader, batch = _STATE["batch"]
    with draw_scope(blend='ALPHA', depth='LESS_EQUAL', depth_mask=False):
        batch.draw(shader)


def _draw_pixel():
    context = bpy.context
    if context.mode != 'EDIT_MESH' or context.edit_object is None:
        return
    region = context.region
    if region is None:
        return
    theme = get_theme(context)
    count = _STATE["count"]
    role = Role.HUD_STATS_ERROR if count else Role.HUD_LABEL
    with hud_text.isolated(theme) as font_id:
        hud_text.draw(f"Non-Planar: {count}", LABEL_X,
                      region.height - LABEL_Y_FROM_TOP,
                      theme=theme, role=role, font_id=font_id)


def _enable():
    if overlay_enabled():
        return
    _STATE["dirty"] = True
    _STATE["handle_view"] = safe_handler_add(
        bpy.types.SpaceView3D, _draw_view, (), "WINDOW", "POST_VIEW")
    _STATE["handle_pixel"] = safe_handler_add(
        bpy.types.SpaceView3D, _draw_pixel, (), "WINDOW", "POST_PIXEL")
    for lst in _app_handler_lists():
        if _mark_dirty not in lst:
            lst.append(_mark_dirty)


def disable_overlay():
    """Idempotent. Also called from the addon's unregister(); removes only
    this module's handlers."""
    safe_handler_remove(_STATE["handle_view"], bpy.types.SpaceView3D, "WINDOW")
    safe_handler_remove(_STATE["handle_pixel"], bpy.types.SpaceView3D, "WINDOW")
    for lst in _app_handler_lists():
        while _mark_dirty in lst:
            lst.remove(_mark_dirty)
    _STATE.update(handle_view=None, handle_pixel=None, batch=None,
                  count=0, dirty=True, obj_ptr=0, threshold=None)


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
            _rebuild(context)
            self.report({'INFO'},
                        f"Non-Planar overlay: ON "
                        f"({_STATE['count']} non-planar)")
        _tag_redraw_view3d(context)
        return {'FINISHED'}
