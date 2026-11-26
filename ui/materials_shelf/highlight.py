"""Viewport highlight for the iOps shelf (POST_VIEW draw handler).

- Hover: while a shelf cell is hovered (and Highlight On Hover is on), the
  faces that use its material on visible mesh objects are filled. The
  triangles come from the evaluated meshes (what the viewport shows,
  modifiers included); the CPU arrays are cached per (material, depsgraph
  generation) and turned into one GPU batch in the draw callback. At most
  MAX_TRIS triangles are collected (objects in view-layer order, the last
  one cut); past that the highlight is partial.
- Drag: the object under the cursor gets its bounding box drawn, and with
  Alt the face under the cursor is filled.
Fills use the Non-Planar overlay's depth-shrink shader (depth tested, no
z-fighting) in theme colours.
"""
import time

import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader

from ...operators.materials import common, state
from ..draw import Role, draw_scope, get_theme, primitives, \
    safe_handler_add, safe_handler_remove

MAX_TRIS = 300_000

_CACHE = {"key": None, "geom": None, "batch": None, "tris": 0,
          "capped": False, "ms": 0.0}
_HANDLE = {"view": None}
# drag target, written by events.py: {"bbox": [8 world corners],
# "face": [world triangle coords] or None}
DROP = {"target": None}


def collect(context, mat, max_tris=MAX_TRIS):
    """(float32 (N*3, 3) world triangle coords, triangle count, capped)
    of the faces using `mat` on visible mesh objects."""
    depsgraph = context.evaluated_depsgraph_get()
    chunks, total, capped = [], 0, False
    for obj in common.view_layer_objects(context):
        if obj.type != "MESH" or not obj.visible_get():
            continue
        slots = [i for i, s in enumerate(obj.material_slots)
                 if s.material == mat]
        if not slots:
            continue
        me = obj.evaluated_get(depsgraph).data
        n = len(me.loop_triangles)
        if not n:
            continue
        mi = np.empty(n, dtype=np.int32)
        me.loop_triangles.foreach_get("material_index", mi)
        mask = np.isin(mi, slots)
        count = int(mask.sum())
        if not count:
            continue
        tv = np.empty(n * 3, dtype=np.int32)
        me.loop_triangles.foreach_get("vertices", tv)
        tv = tv.reshape(n, 3)[mask]
        if total + count > max_tris:
            tv = tv[:max_tris - total]
            count = len(tv)
            capped = True
        co = np.empty(len(me.vertices) * 3, dtype=np.float32)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        mw = np.array(obj.matrix_world, dtype=np.float32)
        world = co @ mw[:3, :3].T + mw[:3, 3]
        chunks.append(world[tv.reshape(-1)])
        total += count
        if capped:
            break
    if not chunks:
        return np.empty((0, 3), dtype=np.float32), 0, False
    return np.concatenate(chunks), total, capped


def set_hover(context, mat):
    """Hovered material (None clears). Rebuilds the CPU arrays only when
    the material or the depsgraph generation changed."""
    if mat is None:
        if _CACHE["key"] is not None:
            _CACHE.update(key=None, geom=None, batch=None, tris=0)
            _tag()
        return
    key = (common.material_key(mat), state.generation())
    if key == _CACHE["key"]:
        return
    t0 = time.perf_counter()
    try:
        geom, tris, capped = collect(context, mat)
    except (ReferenceError, RuntimeError, ValueError):
        geom, tris, capped = None, 0, False
    _CACHE.update(key=key, geom=geom, batch=None, tris=tris, capped=capped,
                  ms=(time.perf_counter() - t0) * 1000.0)
    _tag()


def cache_info():
    return {"tris": _CACHE["tris"], "capped": _CACHE["capped"],
            "ms": _CACHE["ms"], "key": _CACHE["key"]}


def _tag():
    from . import tag_redraw_all
    tag_redraw_all()


def _fill_batch(coords, color):
    from ...operators.mesh_nonplanar_overlay import _get_shader
    shader = _get_shader()
    cols = np.empty((len(coords), 4), dtype=np.float32)
    cols[:] = color
    return shader, batch_for_shader(shader, "TRIS",
                                    {"pos": coords, "color": cols})


def _draw_fill(shader, batch):
    from ...operators.mesh_nonplanar_overlay import DEPTH_SHRINK
    shader.bind()
    shader.uniform_float("viewMat", gpu.matrix.get_model_view_matrix())
    shader.uniform_float("projMat", gpu.matrix.get_projection_matrix())
    shader.uniform_float("depthShrink", DEPTH_SHRINK)
    batch.draw(shader)


_BBOX_EDGES = ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7),
               (7, 4), (0, 4), (1, 5), (2, 6), (3, 7))


def _draw_view():
    context = bpy.context
    from . import shelf_active
    if not shelf_active(context):
        return
    theme = get_theme(context)
    try:
        prefs = common.addon_prefs(context)
        hover_on = prefs.materials_highlight_hover
    except (KeyError, AttributeError):
        hover_on = False
    geom = _CACHE["geom"]
    if hover_on and geom is not None and len(geom):
        if _CACHE["batch"] is None:
            _CACHE["batch"] = _fill_batch(
                geom, theme.color_for(Role.GHOST_PREVIEW))
        with draw_scope(blend="ALPHA", depth="LESS_EQUAL", depth_mask=False):
            _draw_fill(*_CACHE["batch"])
    target = DROP["target"]
    if target is not None:
        corners = target["bbox"]
        flat = [corners[i] for edge in _BBOX_EDGES for i in edge]
        primitives.edges_world(flat, role=Role.ACTIVE_LINE, theme=theme,
                               occluded_min=0.5)
        face = target.get("face")
        if face is not None and len(face):
            shader, batch = _fill_batch(
                np.asarray(face, dtype=np.float32),
                theme.color_for(Role.GHOST_ACTIVE))
            with draw_scope(blend="ALPHA", depth="LESS_EQUAL",
                            depth_mask=False):
                _draw_fill(shader, batch)


def clear():
    _CACHE.update(key=None, geom=None, batch=None, tris=0, capped=False)
    DROP["target"] = None


def register():
    if _HANDLE["view"] is None:
        _HANDLE["view"] = safe_handler_add(bpy.types.SpaceView3D, _draw_view,
                                           (), "WINDOW", "POST_VIEW")


def unregister():
    if _HANDLE["view"] is not None:
        safe_handler_remove(_HANDLE["view"], bpy.types.SpaceView3D, "WINDOW")
        _HANDLE["view"] = None
    clear()


def handler_installed():
    return _HANDLE["view"] is not None
