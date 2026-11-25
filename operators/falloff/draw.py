"""Viewport drawing of the falloff field stack: the fields, their labels, the
pivot and the weight preview.

Module-level draw handlers (installed at add-on register, removed at
unregister) rather than gizmos: the falloff operators draw the same thing
while they run under any tool (`op_begin` / `op_end`), and the percent
labels need a POST_PIXEL pass. The handles live in `tool.py`.

The geometry (gradient segments, labels, volume outlines, preview colours)
is built by pure functions so it can be tested without a GPU; the
`_draw_*` functions only hand it to `ui/draw/primitives`.

The preview cache keeps numpy arrays only (never BMesh references): the
domain is collected again when a depsgraph update touched objects / meshes,
the weights when the stack signature changed. The weight-dot GPU batches
are kept apart (`_weight_batches`, keyed by preview version, theme colours
and dimming) and dropped by `uninstall()`. It reads the edit meshes without tagging them: a tag from inside a
draw handler would fire another depsgraph update and re-dirty the cache on
every redraw.
"""
from __future__ import annotations

import traceback

import bpy
import numpy as np
from bpy.app.handlers import persistent
from bpy_extras import view3d_utils
from mathutils import Vector

from ...ui.draw import Role, get_theme, primitives
from ...ui.draw.handlers import safe_handler_add, safe_handler_remove
from ...ui.hud import text as hud_text
from ...utils import falloff_core as fc
from .domain import auto_pivot, collect_domain, finish_domain
from .props import field_to_dict

TOOL_IDNAME = "iops.falloff_tool"

# 0 % / 100 % colours: two existing theme roles (cyan -> amber)
ROLE_0 = Role.ACTIVE_LINE
ROLE_100 = Role.LOCKED_LINE
GRADIENT_STEPS = 16
OUTLINE_SEGMENTS = 48
# Inactive fields: dimmed, thinner and without handles, but still readable.
INACTIVE_ALPHA = 0.75
DISABLED_ALPHA = 0.5
# The field line is this many times the theme's active / default line
# width, so it reads over the dense weight dots.
LINE_SCALE = 2.0
# A dark backing line, this many pixels wider than the line it sits under,
# separates the line / outline from the dots and the face tint behind it.
HALO_PX = 3.0
HALO_ALPHA = 0.6
# Parts of a field that geometry hides are drawn at the theme's occluded
# opacity, but never fainter than this: after a Move raises the mesh over
# the field, the field must still be seen and grabbed.
OCCLUDED_MIN = 0.5
LABEL_OFFSET = 8


# ------------------------------------------------------------------ pure geometry

def dim(color, factor) -> tuple:
    """`color` with its alpha times `factor`."""
    return (float(color[0]), float(color[1]), float(color[2]),
            float(color[3]) * float(factor))


def weight_colors(W, c0, c100) -> np.ndarray:
    """(N, 4) colours lerp(c0, c100, w)."""
    w = np.clip(np.asarray(W, dtype=np.float64), 0.0, 1.0)[:, None]
    a = np.asarray(c0, dtype=np.float64)
    b = np.asarray(c100, dtype=np.float64)
    return a + (b - a) * w


def gradient_segments(field: dict, c0, c100, steps: int = GRADIENT_STEPS) -> list:
    """The Start->End line as `steps` segments ((a, b), colour), each
    coloured by the field's own weight (curve, invert) at its midpoint."""
    s = np.asarray(field["start"], dtype=np.float64)
    e = np.asarray(field["end"], dtype=np.float64)
    t = np.linspace(0.0, 1.0, steps + 1)[:, None]
    pts = s + (e - s) * t
    mids = 0.5 * (pts[:-1] + pts[1:])
    cols = weight_colors(fc.field_weight(mids, field), c0, c100)
    return [((tuple(pts[i]), tuple(pts[i + 1])), tuple(cols[i]))
            for i in range(steps)]


def field_labels(field: dict) -> list:
    """[(world point, "N%", weight)]: the field's weight at Start and End,
    plus the midpoint for Bidirectional."""
    s = np.asarray(field["start"], dtype=np.float64)
    e = np.asarray(field["end"], dtype=np.float64)
    pts = [s, 0.5 * (s + e), e] if field["type"] == "BIDIRECTIONAL" else [s, e]
    w = fc.field_weight(np.array(pts), field)
    return [(tuple(p), "%d%%" % int(round(100.0 * float(x))), float(x))
            for p, x in zip(pts, w)]


def _frame(field: dict):
    """(centre, axes (3,3) columns, radii (3,)) of a Radial / Elliptical
    field, else None."""
    s = np.asarray(field["start"], dtype=np.float64)
    e = np.asarray(field["end"], dtype=np.float64)
    if field["type"] == "RADIAL":
        r = max(float(np.linalg.norm(e - s)), fc.MIN_SIZE)
        axes, _ = fc.ellipsoid_frame(s, e, (r, r), 0.0)
        return s, axes, np.array([r, r, r])
    if field["type"] == "ELLIPTICAL":
        axes, radii = fc.ellipsoid_frame(s, e, field["radii"], field["roll"])
        return s, axes, radii
    return None


def volume_outlines(field: dict, segments: int = OUTLINE_SEGMENTS) -> list:
    """Three (segments, 3) loops on the field's sphere / ellipsoid, one per
    pair of frame axes; [] for Linear and Bidirectional."""
    frame = _frame(field)
    if frame is None:
        return []
    c, axes, radii = frame
    a = np.linspace(0.0, 2.0 * np.pi, segments, endpoint=False)[:, None]
    loops = []
    for i, j in ((0, 1), (0, 2), (1, 2)):
        loops.append(c + np.cos(a) * axes[:, i] * radii[i]
                     + np.sin(a) * axes[:, j] * radii[j])
    return loops


def field_layers(field: dict, c0, c100, *, alpha: float, line_px: float,
                 outline_px: float, halo_color) -> list:
    """What to draw for one field, bottom to top, as [(flat segment pairs,
    colour, width px)]: the volume outline (Radial / Elliptical) over its
    halo, then the Start->End gradient line over its halo. The colour is
    one RGBA, or for the gradient line a list with one RGBA per point of
    `pairs` (one draw for the whole line). Every colour has its alpha times
    `alpha`; halos are `HALO_PX` wider than what they back and `HALO_ALPHA`
    as opaque."""
    halo = dim(halo_color, alpha * HALO_ALPHA)
    layers = []
    outline = loops_to_segments(volume_outlines(field))
    if outline:
        layers.append((outline, halo, outline_px + HALO_PX))
        layers.append((outline, dim(c0, alpha), outline_px))
    segs = gradient_segments(field, c0, c100)
    line = [p for (a, b), _ in segs for p in (a, b)]
    layers.append((line, halo, line_px + HALO_PX))
    colors = [c for _, col in segs for c in (dim(col, alpha),) * 2]
    layers.append((line, colors, line_px))
    return layers


def loops_to_segments(loops) -> list:
    """Closed loops -> flat [a, b, b, c, ...] segment list for edges_world."""
    out = []
    for lp in loops:
        n = len(lp)
        for k in range(n):
            out.append(tuple(lp[k]))
            out.append(tuple(lp[(k + 1) % n]))
    return out


# ------------------------------------------------------------------ preview cache

class PreviewCache:
    """World positions of the domain, their stack weights and the automatic
    pivot. numpy only. Two levels: the domain (`P`, `pivot`) is collected
    again only when a depsgraph update touched objects / meshes (`dirty`)
    or `geo_key` changed; the weights only when the stack signature
    changed. `version` counts the changes of `P` / `W` (the key of the
    drawn batch)."""
    __slots__ = ("P", "W", "pivot", "geo_key", "signature", "dirty", "version")

    def __init__(self):
        self.P = np.zeros((0, 3))
        self.W = np.zeros(0)
        self.pivot = None
        self.geo_key = None
        self.signature = None
        self.dirty = True
        self.version = 0


_cache = PreviewCache()


def geometry_key(context) -> tuple:
    """What the domain and the automatic pivot depend on besides the mesh."""
    settings = context.scene.IOPS.falloff
    edit = getattr(context, "edit_object", None)
    return (settings.basis, tuple(context.scene.cursor.location), context.mode,
            None if edit is None else edit.name)


def stack_signature(context) -> tuple:
    settings = context.scene.IOPS.falloff
    fields = tuple(tuple(sorted(field_to_dict(f).items())) for f in settings.fields)
    return (fields, settings.show_weights) + geometry_key(context)


def invalidate() -> None:
    _cache.dirty = True


def preview_dirty() -> bool:
    return _cache.dirty


def compute_preview(context) -> PreviewCache:
    """The cache: the domain collected again when dirty or its key changed,
    the weights when the domain or the stack changed. With Show Weights off
    no weights are computed (`W` empty); the domain is still kept for the
    pivot and the handle snapping."""
    sig = stack_signature(context)
    geo = geometry_key(context)
    recollect = _cache.dirty or geo != _cache.geo_key
    if not recollect and sig == _cache.signature:
        return _cache
    if recollect:
        P = np.zeros((0, 3))
        pivot = None
        if context.mode == "EDIT_MESH":
            domain = collect_domain(context, normals=False)
            if domain is not None:
                try:
                    P = domain.P.copy()
                    pivot = np.asarray(auto_pivot(context, domain), dtype=np.float64)
                finally:
                    finish_domain(domain, update=False)
        _cache.P, _cache.pivot, _cache.geo_key = P, pivot, geo
        _cache.dirty = False
    settings = context.scene.IOPS.falloff
    if settings.show_weights and len(_cache.P):
        stack = [field_to_dict(f) for f in settings.fields]
        _cache.W = fc.stack_weights(_cache.P, stack)
    else:
        _cache.W = np.zeros(0)
    _cache.signature = sig
    _cache.version += 1
    return _cache


def preview_points() -> np.ndarray:
    """Domain positions of the last preview (for handle snapping)."""
    return _cache.P


def touches_geometry(updates) -> bool:
    """Whether depsgraph `updates` may have changed the domain: any object
    or mesh (geometry, selection, hiding, transform). A change of scene
    properties alone (field handles, settings) does not; the stack
    signature covers those. Unreadable or empty -> True."""
    try:
        ids = [u.id for u in updates]
    except Exception:
        return True
    if not ids:
        return True
    kinds = (bpy.types.Object, bpy.types.Mesh)
    return any(i is None or isinstance(i, kinds) for i in ids)


@persistent
def _on_depsgraph_update(scene, depsgraph):
    if touches_geometry(getattr(depsgraph, "updates", None) or ()):
        _cache.dirty = True


@persistent
def _on_load_post(*_args):
    """A file load drops running modals without `_finish` (an operator's
    `cancel` may not run either): forget them so the drawing does not stay
    on under every tool."""
    _ops.clear()
    _cache.dirty = True


# ------------------------------------------------------------------ GPU batches

class BatchSlot:
    """One cached value rebuilt only when its key changes. Holds GPU
    batches: module-level, emptied by `uninstall()`."""
    __slots__ = ("key", "value")

    def __init__(self):
        self.key = None
        self.value = None

    def get(self, key, build):
        if self.value is None or key != self.key:
            self.value = build()
            self.key = key
        return self.value

    def clear(self) -> None:
        self.key = None
        self.value = None


_weight_batches = BatchSlot()


def weight_batch_key(cache: PreviewCache, c0, c100, factors) -> tuple:
    """Key of the weight-dot batches: the preview (its version), the 0 % /
    100 % colours and the occlusion alpha factors baked into them."""
    return (cache.version, tuple(map(float, c0)), tuple(map(float, c100)),
            tuple(map(float, factors)))


# ------------------------------------------------------------------ visibility

_ops: set = set()


def op_begin(op) -> None:
    """A falloff operator started: draw while it runs, whatever the tool."""
    _ops.add(id(op))
    invalidate()


def op_end(op) -> None:
    _ops.discard(id(op))


def active_tool_id(context):
    """idname of the 3D view's active tool in the current mode, or None."""
    try:
        tool = context.workspace.tools.from_space_view3d_mode(
            context.mode, create=False)
    except (AttributeError, RuntimeError, TypeError):
        return None
    return None if tool is None else tool.idname


def tool_active(context) -> bool:
    return active_tool_id(context) == TOOL_IDNAME


def world_per_px(region, rv3d, p) -> float:
    """World length of one pixel at world point `p` (along view right);
    0.0 when it cannot be measured (behind the view, degenerate)."""
    at = Vector(tuple(p))
    right = rv3d.view_rotation @ Vector((1.0, 0.0, 0.0))
    a = view3d_utils.location_3d_to_region_2d(region, rv3d, at)
    b = view3d_utils.location_3d_to_region_2d(region, rv3d, at + right)
    if a is None or b is None or (b - a).length < 1e-6:
        return 0.0
    return 1.0 / (b - a).length


def is_visible(context) -> bool:
    try:
        if context.mode != "EDIT_MESH":
            return False
    except AttributeError:
        return False
    return bool(_ops) or tool_active(context)


# ------------------------------------------------------------------ drawing

_reported = set()


def _guard(fn):
    """Draw-handler body: never raise into Blender (a ReferenceError would
    make the safe proxy drop the handler for good); report once."""
    def run():
        try:
            context = bpy.context
            if is_visible(context):
                fn(context)
        except Exception:
            if fn.__name__ not in _reported:
                _reported.add(fn.__name__)
                traceback.print_exc()
    run.__name__ = fn.__name__
    return run


def field_alpha(active: bool, enabled: bool) -> float:
    k = 1.0 if active else INACTIVE_ALPHA
    return k if enabled else k * DISABLED_ALPHA


def _field_alpha(settings, i, f) -> float:
    return field_alpha(i == settings.active_index, f.enabled)


@_guard
def _draw_view(context):
    th = get_theme(context)
    settings = context.scene.IOPS.falloff
    cache = compute_preview(context)
    c0, c100 = th.color_for(ROLE_0), th.color_for(ROLE_100)
    if settings.show_weights and len(cache.W):
        factors = primitives.occlusion_factors(th)
        batches = _weight_batches.get(
            weight_batch_key(cache, c0, c100, factors),
            lambda: primitives.points_colored_batches(
                cache.P, weight_colors(cache.W, c0, c100), factors))
        primitives.draw_points_colored_world(
            batches, size=th.point_size("default"), theme=th)
    # after the dots so the fields read on top of them; inactive fields
    # first, the active one last. edges_world draws the parts geometry
    # hides again at the theme's occluded opacity (at least OCCLUDED_MIN).
    halo = th.color_for(Role.POINT_OUTLINE)
    order = sorted(range(len(settings.fields)), key=lambda i: i == settings.active_index)
    for i in order:
        f = settings.fields[i]
        active = i == settings.active_index
        base = th.width("active" if active else "default")
        for pairs, col, px in field_layers(
                field_to_dict(f), c0, c100, alpha=_field_alpha(settings, i, f),
                line_px=base * LINE_SCALE, outline_px=base, halo_color=halo):
            if isinstance(col, list):
                primitives.edges_colored_world(pairs, col, width=px, theme=th,
                                               occluded_min=OCCLUDED_MIN)
            else:
                primitives.edges_world(pairs, color=col, width=px, theme=th,
                                       occluded_min=OCCLUDED_MIN)
    pivot = (tuple(settings.pivot) if settings.use_custom_pivot
             else (None if cache.pivot is None else tuple(cache.pivot)))
    if pivot is not None:
        primitives.points_world([pivot], role=Role.PIVOT, theme=th)


@_guard
def _draw_pixel(context):
    region, rv3d = context.region, context.region_data
    if region is None or rv3d is None:
        return
    th = get_theme(context)
    settings = context.scene.IOPS.falloff
    c0, c100 = th.color_for(ROLE_0), th.color_for(ROLE_100)
    with hud_text.isolated(th) as font_id:
        for i, f in enumerate(settings.fields):
            k = _field_alpha(settings, i, f)
            for p, text, w in field_labels(field_to_dict(f)):
                xy = view3d_utils.location_3d_to_region_2d(region, rv3d, p)
                if xy is None:
                    continue
                col = tuple(weight_colors([w], c0, c100)[0])
                hud_text.draw(text, int(xy.x) + LABEL_OFFSET, int(xy.y) + LABEL_OFFSET,
                              theme=th, color=dim(col, k), font_id=font_id)


# ------------------------------------------------------------------ install

_handles: list = []


_APP_HANDLERS = (("depsgraph_update_post", _on_depsgraph_update),
                 ("load_post", _on_load_post))


def _remove_app_handlers() -> None:
    """Every app handler of this module, including ones left by an earlier
    import of it (dev reload): matched by module and function name."""
    for kind, fn in _APP_HANDLERS:
        hs = getattr(bpy.app.handlers, kind)
        for h in list(hs):
            if (getattr(h, "__module__", None) == __name__
                    and getattr(h, "__name__", None) == fn.__name__):
                hs.remove(h)


def install() -> None:
    """Add the POST_VIEW / POST_PIXEL handlers and the depsgraph / load
    hooks. Idempotent."""
    if not _handles:
        for fn, kind in ((_draw_view, "POST_VIEW"), (_draw_pixel, "POST_PIXEL")):
            _handles.append(safe_handler_add(bpy.types.SpaceView3D, fn, (),
                                             "WINDOW", kind, tick=False))
    _remove_app_handlers()
    for kind, fn in _APP_HANDLERS:
        getattr(bpy.app.handlers, kind).append(fn)
    invalidate()


def uninstall() -> None:
    while _handles:
        safe_handler_remove(_handles.pop(), bpy.types.SpaceView3D, "WINDOW")
    _remove_app_handlers()
    _ops.clear()
    _reported.clear()
    _weight_batches.clear()
    global _cache
    _cache = PreviewCache()
