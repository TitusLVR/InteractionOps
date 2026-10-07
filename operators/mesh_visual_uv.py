import bpy
import blf
import bmesh
import math
from mathutils import Color, Matrix, Vector
from mathutils.bvhtree import BVHTree
from bpy_extras.view3d_utils import (location_3d_to_region_2d,
                                     region_2d_to_origin_3d)

from ..ui.draw.theme import get_theme, Role, axis_color
from ..ui.draw import primitives as draw_prim, draw_scope
from ..ui.draw import safe_handler_add, safe_handler_remove
from ..ui.hud import (HUDOverlay, HelpOverlay, HUDSection, HUDItem,
                      HUDParam, ItemState,
                      handle_hud_toggle, handle_help_toggle, capture_event)
from ..ui.hud.text import draw as hud_text_draw

from ..utils.uv_utils import (
    get_uv_layer,
    get_selected_face_islands,
    get_island_uv_data,
    get_island_3d_data,
    cache_all_uvs,
    restore_uvs,
    move_island_uv,
    rotate_island_uv,
    scale_island_uv,
    flip_island_uv,
    align_island_to_edge_uv,
    align_island_to_edge_dir_uv,
    uv_point_key,
    toggle_pins_uv,
    clear_pins_uv,
    flip_island_across_line_uv,
    island_signed_area_uv,
    compute_texel_density,
    match_texel_density,
    match_island_dimensions,
    randomize_island_uv,
    straighten_uv_edge_loop,
    stitch_island_to_edge_uv,
    island_centroid_uv,
    get_unselected_face_islands,
    collect_island_edges,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HIT_RADIUS = 14
NORMAL_OFFSET = 0.002
ROT_HANDLE_OFFSET = 28  # px past the top-mid handle

GRAB_SENS_DEFAULT = 1.0
GRAB_SENS_MIN = 0.05
GRAB_SENS_MAX = 3.0
GRAB_SENS_STEP = 1.25

TILE_LIMIT_DEFAULT = 0   # 0 = islands may be dragged anywhere

ROTATION_STEPS = (1, 5, 10, 15, 30, 45, 90)
ROTATION_STEP_DEFAULT_IDX = 6          # 90°

STATE_IDLE = 'IDLE'
STATE_GRAB = 'GRAB'
STATE_ROTATE = 'ROTATE'
STATE_SCALE = 'SCALE'
STATE_HANDLE_SCALE = 'HANDLE_SCALE'
STATE_HANDLE_ROTATE = 'HANDLE_ROTATE'
STATE_PICK_ALIGN_EDGE = 'ALIGN_EDGE'
STATE_PICK_DENSITY_REF = 'DENSITY_REF'
STATE_PICK_DENSITY_TGT = 'DENSITY_TGT'
STATE_PICK_STITCH_SRC = 'STITCH_SRC'
STATE_STITCH_DRAG = 'STITCH_DRAG'
STATE_ALIGN_DRAG = 'ALIGN_DRAG'
STATE_PICK_PIN = 'PIN_EDGES'
STITCH_STATES = (STATE_PICK_STITCH_SRC, STATE_STITCH_DRAG)
ALIGN_STATES = (STATE_PICK_ALIGN_EDGE, STATE_ALIGN_DRAG)
# Two-click edge tools: pick a source edge, then hover a target edge
# with a live preview. They share the stitch_src / stitch_pool /
# stitch_target plumbing.
EDGE_DRAG_STATES = (STATE_STITCH_DRAG, STATE_ALIGN_DRAG)
# Transforms driven by mouse distance / angle get a continuous grab:
# the cursor wraps at the region edges and the motion carries on.
WRAP_STATES = (STATE_GRAB, STATE_ROTATE, STATE_SCALE,
               STATE_HANDLE_SCALE, STATE_HANDLE_ROTATE)
# Click-to-pick sub-modes: Esc / RMB step back to IDLE instead of
# cancelling the whole operator.
PICK_STATES = (STATE_PICK_ALIGN_EDGE, STATE_PICK_DENSITY_REF,
               STATE_PICK_DENSITY_TGT, STATE_PICK_STITCH_SRC,
               STATE_PICK_PIN)
# Pick modes that work on edges: the island wire is drawn and only
# edges are hit-tested.
EDGE_PICK_STATES = (STATE_PICK_ALIGN_EDGE, STATE_PICK_STITCH_SRC,
                    STATE_PICK_PIN)

UNWRAP_METHODS = (
    ('ANGLE_BASED', "Angle Based", "LSCM-style angle based unwrap"),
    ('CONFORMAL', "Conformal", "Conformal (least squares) unwrap"),
    ('MINIMUM_STRETCH', "Minimum Stretch", "SLIM minimum stretch unwrap"),
)
UNWRAP_METHOD_NAMES = {k: n for k, n, _ in UNWRAP_METHODS}
# Max screen distance (px) from the mouse to a target edge for the
# stitch to snap; further away the island stays put ("no target").
STITCH_SNAP_PX = HIT_RADIUS * 3

PIVOT_CENTER = 'CENTER'
PIVOT_CURSOR = 'CURSOR'

SCOPE_ALL = 'ALL'
SCOPE_ACTIVE = 'ACTIVE'

HANDLE_CORNERS = ('BL', 'BR', 'TL', 'TR')
HANDLE_MIDS = ('B', 'T', 'L', 'R')

HANDLE_OPPOSITE = {
    'BL': 'TR', 'BR': 'TL', 'TL': 'BR', 'TR': 'BL',
    'B': 'T', 'T': 'B', 'L': 'R', 'R': 'L',
}

# Per-island identification colors and widget palette live in the
# unified IOPS_Theme (theme.island_palette). State-like edge colors
# are sourced from the 5-state Line/Point/Text roles via Role.*.
# Island fills come from Blender's own theme (Edit Mode face select /
# active face) so the overlay reads like native edit-mode selection.

_FILL_SELECT_FALLBACK = (0.8, 0.36, 0.23, 0.4)
_FILL_ACTIVE_FALLBACK = (1.0, 1.0, 1.0, 0.4)


def _blender_fill_colors():
    """(face_select, editmesh_active) RGBA from Blender's theme.

    Theme stores display sRGB; POST_VIEW drawing expects scene-linear,
    so decode RGB and keep the theme's own alpha."""
    try:
        v3d = bpy.context.preferences.themes[0].view_3d
        sel, act = tuple(v3d.face_select), tuple(v3d.editmesh_active)
    except (IndexError, AttributeError):
        return _FILL_SELECT_FALLBACK, _FILL_ACTIVE_FALLBACK

    def _lin(src, fallback):
        if len(src) < 4:
            return fallback
        c = Color(src[:3]).from_srgb_to_scene_linear()
        # Theme alphas can be fully opaque (editmesh_active is often 1.0);
        # clamp so the mesh always stays visible under the fill.
        return (c.r, c.g, c.b, min(float(src[3]), 0.6))

    return (_lin(sel, _FILL_SELECT_FALLBACK),
            _lin(act, _FILL_ACTIVE_FALLBACK))

def _v3(p):
    """Lift a 2D pixel-space point into a Vector for primitives.*"""
    return Vector((p[0], p[1], 0.0))


def _draw_polyline(pts, *, role=None, color=None, width="default"):
    """Pixel-space polyline through unified primitives."""
    if len(pts) < 2:
        return
    coords = [_v3(p) for p in pts]
    draw_prim.polyline(coords, role=role, color=color, width=width,
                       context=bpy.context)


def _draw_circle(cx, cy, size, *, role=None, color=None):
    """Antialiased filled disc in pixel space (point_disc shader).
    *size* is the diameter in px, matching theme point sizes."""
    draw_prim.points([_v3((cx, cy))], role=role, color=color,
                     size=size, context=bpy.context)


def _draw_ring(cx, cy, radius, *, role=None, color=None,
               width="default", segs=32):
    """Open ring in pixel space."""
    pts = [(cx + math.cos(2 * math.pi * i / segs) * radius,
            cy + math.sin(2 * math.pi * i / segs) * radius)
           for i in range(segs + 1)]
    _draw_polyline(pts, role=role, color=color, width=width)


# ---------------------------------------------------------------------------
# 3D helpers
# ---------------------------------------------------------------------------

def _off(pos, nrm, amt=NORMAL_OFFSET):
    return pos + nrm * amt


def _seg_dist_2d(p, a, b):
    ab = b - a
    if ab.length_squared < 1e-10:
        return (p - a).length
    t = max(0, min(1, ab.dot(p - a) / ab.length_squared))
    return (p - (a + ab * t)).length


# Occlusion tolerance for visibility rays, relative to the ray length:
# the probe point sits on the surface itself, so the mesh is always hit
# at (about) the probe distance and only a clearly nearer hit counts.
_VIS_EPS_REL = 1e-3


def _point_visible(context, bvh, world_inv, p_world, screen_pt):
    """True when nothing of the mesh sits between the viewer and
    p_world. bvh is in object space; screen_pt is p_world projected."""
    region, rv3d = context.region, context.region_data
    origin = region_2d_to_origin_3d(region, rv3d, screen_pt)
    o_l = world_inv @ origin
    p_l = world_inv @ p_world
    ray = p_l - o_l
    length = ray.length
    if length < 1e-9:
        return True
    _, _, _, dist = bvh.ray_cast(o_l, ray / length, length)
    return dist is None or dist >= length * (1.0 - _VIS_EPS_REL)


# ---------------------------------------------------------------------------
# UV-correspondent screen handles
# ---------------------------------------------------------------------------

def _bary_raw(p, a, b, c):
    """Unclamped barycentric coordinates of 2D point *p* in triangle (a, b, c).
    Returns (w_a, w_b, w_c) or None if the triangle is degenerate."""
    v0x, v0y = c[0] - a[0], c[1] - a[1]
    v1x, v1y = b[0] - a[0], b[1] - a[1]
    v2x, v2y = p[0] - a[0], p[1] - a[1]
    d00 = v0x * v0x + v0y * v0y
    d01 = v0x * v1x + v0y * v1y
    d02 = v0x * v2x + v0y * v2y
    d11 = v1x * v1x + v1y * v1y
    d12 = v1x * v2x + v1y * v2y
    det = d00 * d11 - d01 * d01
    if abs(det) < 1e-12:
        return None
    inv = 1.0 / det
    s = (d11 * d02 - d01 * d12) * inv
    t = (d00 * d12 - d01 * d02) * inv
    return (1.0 - s - t, t, s)


def _bary_coords(p, a, b, c):
    """Barycentric coordinates if *p* is inside triangle (a, b, c), else None."""
    bc = _bary_raw(p, a, b, c)
    if bc is None:
        return None
    w, u, v = bc
    if w >= -1e-6 and u >= -1e-6 and v >= -1e-6 and w + u + v <= 1.0 + 2e-6:
        return bc
    return None


def _seg_closest_t(p, a, b):
    """Parameter *t* of closest point on segment a->b to 2D point *p*,
    and the squared distance."""
    abx, aby = b[0] - a[0], b[1] - a[1]
    lsq = abx * abx + aby * aby
    if lsq < 1e-12:
        return 0.0, (a[0] - p[0]) ** 2 + (a[1] - p[1]) ** 2
    t = max(0.0, min(1.0,
            ((p[0] - a[0]) * abx + (p[1] - a[1]) * aby) / lsq))
    cx, cy = a[0] + abx * t, a[1] + aby * t
    return t, (cx - p[0]) ** 2 + (cy - p[1]) ** 2


def _decompose_screen(sv, u_dir, v_dir):
    """Decompose screen vector *sv* into components along *u_dir* and *v_dir*
    using proper 2x2 matrix inverse (handles non-orthogonal axes).
    Returns (cu, cv) such that sv = cu * u_dir + cv * v_dir, or None."""
    det = u_dir.x * v_dir.y - v_dir.x * u_dir.y
    if abs(det) < 1e-6:
        return None
    inv = 1.0 / det
    cu = (sv.x * v_dir.y - sv.y * v_dir.x) * inv
    cv = (sv.y * u_dir.x - sv.x * u_dir.y) * inv
    return cu, cv


def _nearest_3d_for_uv(geo, tu, tv):
    """Precise 3D world position for a UV coordinate via barycentric
    interpolation on the island's UV triangles.  When the point falls
    outside all triangles the nearest triangle is used with unclamped
    (extrapolated) barycentric coords so bbox corners that overshoot
    the UV silhouette still map accurately."""
    p = (tu, tv)
    uv_tris = geo.get('uv_tris')
    if not uv_tris:
        best, pos = 1e10, None
        for uv_key, p3d in geo['verts_3d'].items():
            d = (uv_key[0] - tu) ** 2 + (uv_key[1] - tv) ** 2
            if d < best:
                best, pos = d, p3d
        return pos

    # Exact containment
    for (ua, ub, uc), (pa, pb, pc) in uv_tris:
        bc = _bary_coords(p, ua, ub, uc)
        if bc is not None:
            w, u, v = bc
            return pa * w + pb * u + pc * v

    # Outside all triangles -- find the nearest one (by edge distance)
    # then extrapolate via unclamped bary coords.
    best_d, best_pos = 1e10, None
    for (ua, ub, uc), (pa, pb, pc) in uv_tris:
        d_min = min(_seg_closest_t(p, ua, ub)[1],
                    _seg_closest_t(p, ub, uc)[1],
                    _seg_closest_t(p, uc, ua)[1])
        if d_min < best_d:
            raw = _bary_raw(p, ua, ub, uc)
            if raw is not None:
                w, u, v = raw
                best_d = d_min
                best_pos = pa * w + pb * u + pc * v
    if best_pos is not None:
        return best_pos

    # Final fallback: nearest vertex
    best, pos = 1e10, None
    for uv_key, p3d in geo['verts_3d'].items():
        d = (uv_key[0] - tu) ** 2 + (uv_key[1] - tv) ** 2
        if d < best:
            best, pos = d, p3d
    return pos


def _island_center_3d(idata):
    """3D anchor for the island's center handle: the UV bbox center
    mapped onto the mesh surface — the same mapping the bbox handles
    use — so the marker lands inside the drawn rectangle (the 3D vertex
    centroid drifts away from it on uneven UV density)."""
    geo = idata.get('geo3d')
    if not geo:
        return None
    c = idata['center']
    pos = _nearest_3d_for_uv(geo, c.x, c.y)
    return pos if pos is not None else geo['center_3d']


def _uv_screen_affine(geo, region, rv3d, nrm, nrm_off):
    """Least-squares affine map UV -> screen fitted on the island's own
    vertices.  Returns (rx, ry) Vectors such that
    screen = (rx.dot(u, v, 1), ry.dot(u, v, 1)), or None when the fit is
    degenerate (too few points, collinear UVs, offscreen island)."""
    pts = []
    for (u, v), pos in geo['verts_3d'].items():
        sp = location_3d_to_region_2d(region, rv3d, pos + nrm * nrm_off)
        if sp is not None:
            pts.append((u, v, sp.x, sp.y))
    if len(pts) < 3:
        return None

    su = sv = suu = suv = svv = 0.0
    sx = sy = sux = svx = suy = svy = 0.0
    for u, v, x, y in pts:
        su += u
        sv += v
        suu += u * u
        suv += u * v
        svv += v * v
        sx += x
        sy += y
        sux += u * x
        svx += v * x
        suy += u * y
        svy += v * y
    n = float(len(pts))
    a = Matrix(((suu, suv, su),
                (suv, svv, sv),
                (su, sv, n)))
    if abs(a.determinant()) < 1e-9:
        return None
    ai = a.inverted()
    rx = ai @ Vector((sux, svx, sx))
    ry = ai @ Vector((suy, svy, sy))
    return rx, ry


def _compute_screen_handles(op, context):
    """Screen-space gizmo for the active island: a tight axis-aligned
    rectangle around the island's projected vertices, so the box always
    hugs the island regardless of how curved its UV layout is.  Handle
    names stay UV-semantic (R = UV u max, T = UV v max, ...) — an
    affine UV->screen fit decides which rectangle side each handle sits
    on and provides the axes used to decompose mouse motion back into
    UV space."""
    if not (0 <= op.active_island_idx < len(op.islands_data)):
        return {}
    idata = op.islands_data[op.active_island_idx]
    geo = idata.get('geo3d')
    if not geo or not geo['verts_3d']:
        return {}

    region = context.region
    rv3d = context.region_data
    nrm = geo['normal_avg']
    prefs = bpy.context.preferences.addons["InteractionOps"].preferences
    nrm_off = getattr(prefs, 'visual_uv_normal_offset', NORMAL_OFFSET)

    pts = []
    for pos in geo['verts_3d'].values():
        sp = location_3d_to_region_2d(region, rv3d, pos + nrm * nrm_off)
        if sp is not None:
            pts.append(sp)
    if len(pts) < 3:
        return {}
    pad = 14
    xmin = min(p.x for p in pts) - pad
    xmax = max(p.x for p in pts) + pad
    ymin = min(p.y for p in pts) - pad
    ymax = max(p.y for p in pts) + pad
    cx, cy = (xmin + xmax) * 0.5, (ymin + ymax) * 0.5
    hw, hh = (xmax - xmin) * 0.5, (ymax - ymin) * 0.5

    bmin, bmax = idata['bbox_min'], idata['bbox_max']
    uv_w = max(bmax.x - bmin.x, 1e-8)
    uv_h = max(bmax.y - bmin.y, 1e-8)

    u_scr = v_scr = None
    aff = _uv_screen_affine(geo, region, rv3d, nrm, nrm_off)
    if aff is not None:
        rx, ry = aff
        u_scr = Vector((rx.x, ry.x)) * uv_w
        v_scr = Vector((rx.y, ry.y)) * uv_h

    # Which rectangle side does UV u / v grow toward?
    u_axis, v_axis = 0, 1          # default: UV u along screen x
    su = sv = 1.0
    if u_scr is not None and v_scr is not None:
        if abs(u_scr.x) + abs(v_scr.y) < abs(u_scr.y) + abs(v_scr.x):
            u_axis, v_axis = 1, 0  # island lies sideways on screen
        su = 1.0 if u_scr[u_axis] >= 0 else -1.0
        sv = 1.0 if v_scr[v_axis] >= 0 else -1.0

    def anchor(us, vs):
        d = [0.0, 0.0]
        d[u_axis] = su * us
        d[v_axis] = sv * vs
        return Vector((cx + d[0] * hw, cy + d[1] * hh))

    result = {
        'BL': anchor(-1, -1), 'BR': anchor(1, -1),
        'TL': anchor(-1, 1), 'TR': anchor(1, 1),
        'B': anchor(0, -1), 'T': anchor(0, 1),
        'L': anchor(-1, 0), 'R': anchor(1, 0),
        '_C': Vector((cx, cy)),
    }
    if (u_scr is not None and v_scr is not None
            and u_scr.length > 1 and v_scr.length > 1):
        result['_u_dir'] = u_scr
        result['_v_dir'] = v_scr

    # Rotation handle sits just above the rectangle
    result['_ROT'] = Vector((cx, ymax + ROT_HANDLE_OFFSET))
    return result


# ---------------------------------------------------------------------------
# Draw callbacks
# ---------------------------------------------------------------------------

def draw_3d_callback(op, context):
    if context.area != op._area:
        return
    import gpu
    prefs = bpy.context.preferences.addons["InteractionOps"].preferences
    nrm_off = getattr(prefs, 'visual_uv_normal_offset', NORMAL_OFFSET)
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.depth_mask_set(False)

    fill_select, fill_active = _blender_fill_colors()
    # Clean view hides the island fills and outlines so textures stay
    # readable; the hovered edge and the stitch edges are still drawn.
    # While picking a stitch source every island edge is pickable, so
    # the wire comes back even in clean view (interior edges dimmed):
    # otherwise the user cannot tell which edges will respond.
    show_fill = not op._clean_view
    picking_src = op.state in EDGE_PICK_STATES
    show_outline = show_fill or picking_src
    islands = op.islands_data if show_outline else []
    for idx, idata in enumerate(islands):
        geo = idata.get('geo3d')
        if not geo:
            continue
        is_active = (idx == op.active_island_idx)
        is_selected = idx in op._transform_targets()
        nrm = geo['normal_avg']

        # Fill mirrors native edit-mode selection: active island uses
        # the active-face tint, the rest the face-select tint; islands
        # outside the working set fade out.
        fill = fill_active if is_active else fill_select
        if not (is_active or is_selected):
            fill = (fill[0], fill[1], fill[2], fill[3] * 0.35)
        tv = []
        if show_fill:
            for v0, v1, v2 in geo['face_tris']:
                tv.extend([_off(v0, nrm, nrm_off), _off(v1, nrm, nrm_off),
                           _off(v2, nrm, nrm_off)])
        if tv:
            draw_prim.tris(tv, color=fill, context=context)

        if picking_src:
            wire = []
            for pa, pb in geo['edges_3d']:
                wire.extend([_off(pa, nrm, nrm_off * 1.5),
                             _off(pb, nrm, nrm_off * 1.5)])
            if wire:
                lc = get_theme(context).color_for(Role.LINE)
                draw_prim.edges_3d(wire,
                                   color=(lc[0], lc[1], lc[2], lc[3] * 0.5),
                                   width="default", context=context)

        # Outline only the island's UV boundary — inner edges stay clean.
        edge_role = (Role.ACTIVE_LINE if is_active
                     else Role.CLOSEST_LINE if is_selected else Role.LINE)
        ep = []
        for pa, pb in geo['boundary_edges_3d']:
            ep.extend([_off(pa, nrm, nrm_off * 1.5),
                       _off(pb, nrm, nrm_off * 1.5)])
        if ep:
            draw_prim.edges_3d(ep, role=edge_role, width="active",
                               context=context)

    # Hover / stitch edges sit exactly on the surface (no normal offset
    # is known for arbitrary pool edges) and would z-fight with the
    # mesh, so they are drawn on top of everything.
    gpu.state.depth_test_set('NONE')

    # Edge selection (LMB / Shift+LMB in idle): the active edge is the
    # last picked one and is what E / A start from.
    sel = op._resolved_sel_edges()
    if sel:
        rest = []
        for e in sel[:-1]:
            rest.extend(e['edge_3d'])
        if rest:
            draw_prim.edges_3d(rest, role=Role.LOCKED_LINE,
                               width="default", context=context)
        draw_prim.edges_3d(list(sel[-1]['edge_3d']), role=Role.LOCKED_LINE,
                           width="active", context=context)

    # Pinned UV verts of the session islands: user markings, always
    # shown so an unwrap never surprises.
    pins = []
    for idata in op.islands_data:
        geo = idata.get('geo3d')
        keys = idata.get('pinned_keys')
        if not geo or not keys:
            continue
        v3 = geo['verts_3d']
        pins.extend(v3[k] for k in keys if k in v3)
    if pins:
        draw_prim.points(pins, role=Role.LOCKED_POINT,
                         ring_role=Role.POINT_OUTLINE, context=context)

    if op.stitch_src is not None and op.state in EDGE_DRAG_STATES:
        # Source edge = preview, target edge = active, so the two read
        # differently; the target island gets a faint outline so even
        # an unselected (otherwise undrawn) island shows where we snap.
        src_segs = op.stitch_src.get('segments_3d')
        if src_segs:
            flat = []
            for pa, pb in src_segs:
                flat.extend([pa, pb])
            draw_prim.edges_3d(flat, role=Role.PREVIEW_LINE,
                               width="active", context=context)
        else:
            draw_prim.edges_3d(list(op.stitch_src['edge_3d']),
                               role=Role.PREVIEW_LINE, width="active",
                               context=context)
        if op.stitch_target is not None:
            contour = []
            for (_, _, pa, pb) in op.stitch_target['entry']['edges']:
                contour.extend([pa, pb])
            if contour:
                lc = get_theme(context).color_for(Role.ACTIVE_LINE)
                draw_prim.edges_3d(contour,
                                   color=(lc[0], lc[1], lc[2], lc[3] * 0.35),
                                   width="default", context=context)
            draw_prim.edges_3d(list(op.stitch_target['edge_3d']),
                               role=Role.ACTIVE_LINE, width="active",
                               context=context)

    if op.hover_edge_3d is not None:
        pick_states = ALIGN_STATES + STITCH_STATES + (STATE_PICK_PIN,)
        hover_role = (Role.PREVIEW_LINE if op.state in pick_states
                      else Role.LOCKED_LINE)
        draw_prim.edges_3d(list(op.hover_edge_3d), role=hover_role,
                           width="active", context=context)

    gpu.state.depth_test_set('NONE')
    gpu.state.depth_mask_set(True)
    gpu.state.blend_set('NONE')


def draw_pixel_callback(op, context):
    if context.area != op._area:
        return
    import gpu
    region = context.region
    rv3d = context.region_data
    prefs = bpy.context.preferences.addons["InteractionOps"].preferences
    nrm_off = getattr(prefs, 'visual_uv_normal_offset', NORMAL_OFFSET)
    theme = get_theme(context)
    gpu.state.blend_set('ALPHA')

    for idx, idata in enumerate(op.islands_data):
        geo = idata.get('geo3d')
        if not geo:
            continue
        island_col = theme.island_palette[idx % 8]
        nrm = geo['normal_avg']
        center_off = _island_center_3d(idata) + nrm * nrm_off

        csp = location_3d_to_region_2d(region, rv3d, center_off)

        # Pivot ring sits where the UV-center pivot actually lies on the
        # mesh, so rotation visually spins around the marker. (With the
        # cursor pivot the UV cursor crosshair marks the pivot instead.)
        if (idx == op.active_island_idx and csp
                and op.pivot_mode == PIVOT_CENTER):
            pvs = theme.point_size_for(Role.PIVOT)
            _draw_ring(csp.x, csp.y, pvs * 0.75, role=Role.PIVOT,
                       width="active")
            _draw_circle(csp.x, csp.y, pvs * 0.5, role=Role.PIVOT)

        if not op._clean_view:
            td = idata.get('texel_density')
            if td is not None and csp:
                blf.size(0, 12)
                blf.color(0, *island_col)
                blf.position(0, csp.x + 14, csp.y - 6, 0)
                blf.draw(0, f"TD:{td:.3f}")

    # Gizmo sizes reuse the theme's 5-state Point sizes (diameters, same
    # as every other point in the addon): handle = Default, hover =
    # Closest, pivot = Active, cursor = Locked
    hsize = theme.point_size_for(Role.HANDLE)
    hsize_hover = theme.point_size_for(Role.HANDLE_HOVER)
    pvs = theme.point_size_for(Role.PIVOT)

    # Move handle (gizmo box center) + rotation handle
    handles = _compute_screen_handles(op, context)
    if handles:
        csp = handles['_C']
        hovered = op.hover_handle == 'CENTER'
        hc_role = Role.HANDLE_HOVER if hovered else Role.HANDLE
        _draw_circle(csp.x, csp.y, hsize_hover if hovered else hsize,
                     role=hc_role)
        rsp = handles.get('_ROT')
        if rsp:
            pivot = theme.color_for(Role.PIVOT)
            _draw_polyline([csp, rsp],
                           color=(pivot[0], pivot[1], pivot[2], 0.35),
                           width="default")
            rc_role = (Role.HANDLE_HOVER if op.hover_rotate_handle
                       else Role.PIVOT)
            _draw_circle(rsp.x, rsp.y, pvs, role=rc_role)

    # Bounding box + handles (active island)
    if handles and op.state in (STATE_IDLE, STATE_HANDLE_SCALE):
        if all(n in handles for n in HANDLE_CORNERS):
            box = [(handles[n].x, handles[n].y)
                   for n in ('BL', 'BR', 'TR', 'TL', 'BL')]
            _draw_polyline(box, role=Role.BBOX)

        for name in HANDLE_CORNERS:
            if name not in handles:
                continue
            h = handles[name]
            hovered = op.hover_handle == name
            hc_role = Role.HANDLE_HOVER if hovered else Role.HANDLE
            _draw_circle(h.x, h.y, hsize_hover if hovered else hsize,
                         role=hc_role)

        for name in HANDLE_MIDS:
            if name not in handles:
                continue
            h = handles[name]
            hovered = op.hover_handle == name
            hc_role = Role.HANDLE_HOVER if hovered else Role.HANDLE
            _draw_circle(h.x, h.y,
                         (hsize_hover if hovered else hsize) * 0.8,
                         role=hc_role)

    # UV Cursor
    if op.cursor_3d is not None:
        csp = location_3d_to_region_2d(region, rv3d, op.cursor_3d)
        if csp:
            csize = theme.point_size_for(Role.CURSOR)
            arm = csize * 1.25
            coords = [_v3(p) for p in [
                (csp.x - arm, csp.y), (csp.x + arm, csp.y),
                (csp.x, csp.y - arm), (csp.x, csp.y + arm),
            ]]
            draw_prim.edges_3d(coords, role=Role.CURSOR, width="active",
                               context=bpy.context)
            _draw_circle(csp.x, csp.y, max(4.0, csize * 0.5),
                         role=Role.CURSOR)

    # Axis-lock preview: rail through the pivot along the UV axis the
    # transform is constrained to, in Blender's axis colors
    if (op.state in (STATE_GRAB, STATE_SCALE, STATE_HANDLE_SCALE)
            and op.grab_axis in ('X', 'Y')
            and op.drag_center_screen is not None):
        d = op.uv_screen_u if op.grab_axis == 'X' else op.uv_screen_v
        if d is not None and d.length > 1e-3:
            dn = d.normalized()
            c = op.drag_center_screen
            ext = 4000.0
            col = axis_color(op.grab_axis)
            _draw_polyline([c - dn * ext, c + dn * ext],
                           color=(col[0], col[1], col[2], 0.6),
                           width="default")

    _draw_transform_feedback(op)
    gpu.state.blend_set('NONE')


def _draw_transform_feedback(op):
    mx, my = op.mouse_x, op.mouse_y
    theme = get_theme(bpy.context)

    def _t(text, *, role=None, color=None):
        hud_text_draw(text, mx + 18, my + 10, theme=theme,
                      role=role, color=color, size_token="hud_label")

    if (op.state in (STATE_ROTATE, STATE_HANDLE_ROTATE)
            and op.drag_center_screen):
        deg = math.degrees(op.current_angle_delta)
        step_deg = ROTATION_STEPS[op.rotation_step_idx]
        _t(f"R {deg:.1f}\u00b0  [Ctrl snap {step_deg}\u00b0]", role=Role.HUD_ACTIVE_VALUE)

    elif (op.state in (STATE_SCALE, STATE_HANDLE_SCALE)
          and op.drag_center_screen):
        sx, sy = op.current_scale_x, op.current_scale_y
        if op.grab_axis == 'X':
            _t(f"S X {sx:.3f}", color=axis_color('X'))
        elif op.grab_axis == 'Y':
            _t(f"S Y {sy:.3f}", color=axis_color('Y'))
        else:
            _t(f"S {sx:.3f} x {sy:.3f}", role=Role.HUD_ACTIVE_VALUE)

    elif op.state == STATE_PICK_STITCH_SRC:
        _t("Stitch: pick source edge  [RMB / Esc exit]",
           role=Role.HUD_ACTIVE_VALUE)

    elif op.state == STATE_PICK_ALIGN_EDGE:
        _t("Align: pick source edge  [RMB / Esc exit]",
           role=Role.HUD_ACTIVE_VALUE)

    elif op.state == STATE_PICK_PIN:
        _t("Pins: click edge to pin / unpin  "
           "[U unwrap, Alt+M clear, RMB / Esc exit]",
           role=Role.HUD_ACTIVE_VALUE)

    elif op.state == STATE_ALIGN_DRAG:
        deg = math.degrees(op.align_angle)
        mode = "to edge" if op.stitch_target is not None else "to axis"
        _t(f"Align  {deg:.1f}\u00b0  [{mode}]  LMB confirm, Shift flip",
           role=Role.HUD_ACTIVE_VALUE)

    elif op.state == STATE_STITCH_DRAG:
        n_src = op.stitch_src.get('n_edges', 1) if op.stitch_src else 1
        scale_mode = ("keep scale" if op.stitch_keep_scale
                      else f"fit {n_src} edges" if n_src > 1
                      else "match edge")
        if op.stitch_target is None:
            _t(f"Stitch  no target  [{scale_mode}]",
               role=Role.HUD_ACTIVE_VALUE)
        else:
            _t(f"Stitch  scale {op.stitch_scale:.2f}x  [{scale_mode}]  "
               "LMB confirm, Shift flip, Ctrl scale mode",
               role=Role.HUD_ACTIVE_VALUE)

    elif op.state == STATE_GRAB:
        sens_pct = int(op.grab_sensitivity / GRAB_SENS_DEFAULT * 100)
        if op.grab_axis == 'X':
            _t(f"G along X  [{sens_pct}%]", color=axis_color('X'))
        elif op.grab_axis == 'Y':
            _t(f"G along Y  [{sens_pct}%]", color=axis_color('Y'))
        else:
            _t(f"G Move  [{sens_pct}%]", role=Role.HUD_ACTIVE_VALUE)


def _build_visual_uv_hud(context):
    hud = HUDOverlay("visual_uv")
    hud.title = "Visual UV"
    helpo = HelpOverlay("visual_uv")
    helpo.add_section(HUDSection('Transform', [
        HUDItem('Move / Rotate / Scale', 'G / R / S', ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem('Axis lock', 'X / Y', ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem('Sensitivity', 'Alt+Scroll', ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem('Rotation step', 'Ctrl+Scroll', ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem('Pivot', 'P', ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem('UV cursor', 'C', ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem('Scope All / Active', 'I', ItemState.ON, default_state=ItemState.OFF, always_show=True),
    ]))
    helpo.add_section(HUDSection('Islands', [
        HUDItem('Active island', 'LMB / Tab', ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem('Select edge / add', 'LMB / Sh+LMB', ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem('Fit to active / W / H', 'D / Sh+D / Ct+D', ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem('Flip H / V', 'F / Sh+F', ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem('Randomize UV / U / V', 'N / Sh+N / Ct+N', ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem('Straighten chain', 'T', ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem('Align view', 'V', ItemState.ON, default_state=ItemState.OFF, always_show=True),
    ]))
    helpo.add_section(HUDSection('Edge tools', [
        HUDItem('Align to edge', 'A', ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem('Stitch to edge', 'E', ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem('Flip side / keep scale', 'Shift / Ctrl', ItemState.ON, default_state=ItemState.OFF, always_show=True),
    ]))
    helpo.add_section(HUDSection('Pins & Unwrap', [
        HUDItem('Pin edges / clear', 'M / Alt+M', ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem('Unwrap active / all', 'U / Ct+U', ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem('Method / keep mirror', 'Sh+U / Sh+M', ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem('Flip across pins', 'Alt+U', ItemState.ON, default_state=ItemState.OFF, always_show=True),
    ]))
    helpo.add_section(HUDSection('View & Session', [
        HUDItem('Overlays / modifiers', 'Q / Sh+Q', ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem('Undo / Redo', 'Ct+Z / Ct+Sh+Z', ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem('Confirm / Cancel', 'Enter / Esc', ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem('Help / HUD', 'H', ItemState.ON, default_state=ItemState.OFF, always_show=True),
    ]))
    return hud, helpo


def draw_shortcuts_callback(op, context):
    if context.area != op._area:
        return
    hud = getattr(op, "_hud", None)
    helpo = getattr(op, "_help", None)
    if helpo is not None:
        helpo.draw(context, getattr(op, "_last_event", None))
    if hud is None:
        return
    st = op.state.replace('_', ' ').title()
    pv = op.pivot_mode
    sens_pct = int(op.grab_sensitivity / GRAB_SENS_DEFAULT * 100)
    rot_step = ROTATION_STEPS[op.rotation_step_idx]
    uv_name = getattr(op.uv_layer, 'name', '?')
    hud.set_header(
        f"Visual UV  [{st}]",
        f"UV map: {uv_name}",
        f"Pivot: {pv}",
        f"Scope: {op.transform_scope.title()}",
        f"Sens: {sens_pct}%",
        f"Islands: {len(op.islands_data)}",
        f"RotStep: {rot_step}\u00b0",
        f"Unwrap: {UNWRAP_METHOD_NAMES.get(op.unwrap_method, '?')}"
        + ("  [keep mirror]" if op.unwrap_keep_flip else ""),
        ("Modifiers: PAUSED" if op._suspended_mods else None),
    )
    hud.draw(context, getattr(op, "_last_event", None))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _handle_uv_pos(idata, name):
    bmin, bmax = idata['bbox_min'], idata['bbox_max']
    cx = (bmin.x + bmax.x) * 0.5
    cy = (bmin.y + bmax.y) * 0.5
    return {
        'BL': Vector((bmin.x, bmin.y)), 'BR': Vector((bmax.x, bmin.y)),
        'TL': Vector((bmin.x, bmax.y)), 'TR': Vector((bmax.x, bmax.y)),
        'B': Vector((cx, bmin.y)), 'T': Vector((cx, bmax.y)),
        'L': Vector((bmin.x, cy)), 'R': Vector((bmax.x, cy)),
    }.get(name, Vector((cx, cy)))


def _get_pivot_uv(op, idata):
    if op.pivot_mode == PIVOT_CURSOR:
        return op.uv_cursor.copy()
    return idata['center'].copy()


# ---------------------------------------------------------------------------
# Operator
# ---------------------------------------------------------------------------

class IOPS_OT_MeshVisualUV(bpy.types.Operator):
    """Interactive UV island manipulation directly on the 3D mesh surface"""

    bl_idname = "iops.mesh_visual_uv"
    is_bindable = True
    bl_label = "IOPS Visual UV"
    bl_options = {"REGISTER", "UNDO"}

    tile_limit_prop: bpy.props.IntProperty(
        name="Tile Limit",
        description="Max tiles away from 0-1 before an island snaps back "
                    "to the centre; 0 disables the snap",
        default=TILE_LIMIT_DEFAULT, min=0, max=10)
    rotation_step_prop: bpy.props.IntProperty(
        name="Rotation Step",
        description="Ctrl-snap step in degrees",
        default=ROTATION_STEPS[ROTATION_STEP_DEFAULT_IDX],
        min=1, max=90)
    grab_sensitivity_prop: bpy.props.FloatProperty(
        name="Grab Sensitivity",
        description="Movement speed multiplier",
        default=GRAB_SENS_DEFAULT, min=GRAB_SENS_MIN, max=GRAB_SENS_MAX)
    unwrap_method_prop: bpy.props.EnumProperty(
        name="Unwrap Method",
        description="Algorithm used by U (pinned UVs stay put)",
        items=UNWRAP_METHODS, default='ANGLE_BASED')
    unwrap_keep_flip_prop: bpy.props.BoolProperty(
        name="Unwrap Keeps Mirroring",
        description="After U, flip the result back across the pins when "
                    "the unwrap changed the island's mirroring",
        default=True)

    _handle_3d = None
    _handle_pixel = None
    _handle_shortcuts = None
    _timer = None

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj is not None and obj.type == 'MESH'
                and obj.mode == 'EDIT' and context.area
                and context.area.type == 'VIEW_3D')

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def rebuild_data(self, context):
        obj = context.active_object
        self.bm = bmesh.from_edit_mesh(obj.data)
        self.uv_layer = get_uv_layer(self.bm)
        world = obj.matrix_world
        if self.islands:
            # Mid-session rebuild: keep the island partition stable.
            # Re-flood each island only within its own faces so islands
            # may split (after an unwrap) but never merge -- a stitched
            # island whose UVs now coincide with its neighbour stays a
            # separate island the user can keep working on.
            islands = []
            for old in self.islands:
                parts, _ = get_selected_face_islands(
                    self.bm, self.uv_layer, seed_faces=old,
                    restrict_to=old)
                islands.extend(parts)
        else:
            islands, _ = get_selected_face_islands(self.bm, self.uv_layer)
        self.islands = islands
        self.islands_data = []
        for island in islands:
            idata = get_island_uv_data(self.bm, island, self.uv_layer)
            if idata:
                idata['face_indices'] = island
                idata['texel_density'] = compute_texel_density(
                    self.bm, island, self.uv_layer)
                idata['geo3d'] = get_island_3d_data(
                    self.bm, island, self.uv_layer, world)
                self.islands_data.append(idata)
        n = len(self.islands_data)
        if self.active_island_idx >= n:
            self.active_island_idx = max(0, n - 1)
        self.selected_islands = set(range(n))
        self._sync_uv_editor(context)

    def _align_view_to_island(self, context):
        """Point the viewport straight at the active island (view axis
        along the island normal) and roll it so the UV axes match the
        screen axes — the gizmo box becomes minimal. Centers and fits
        the island."""
        if not (0 <= self.active_island_idx < len(self.islands_data)):
            return False
        geo = self.islands_data[self.active_island_idx].get('geo3d')
        if not geo or not geo['verts_3d']:
            return False
        z = geo['normal_avg'].normalized()

        # 3D direction of the UV u axis (average surface tangent)
        t_acc = Vector((0.0, 0.0, 0.0))
        for (ua, ub, uc), (pa, pb, pc) in geo.get('uv_tris', []):
            e1, e2 = pb - pa, pc - pa
            du1, dv1 = ub[0] - ua[0], ub[1] - ua[1]
            du2, dv2 = uc[0] - ua[0], uc[1] - ua[1]
            det = du1 * dv2 - du2 * dv1
            if abs(det) < 1e-12:
                continue
            t_acc += (e1 * dv2 - e2 * dv1) / det
        t = t_acc - z * t_acc.dot(z)
        if t.length < 1e-6:
            t = Vector((1.0, 0.0, 0.0)) - z * z.x
        if t.length < 1e-6:
            t = Vector((0.0, 1.0, 0.0)) - z * z.y
        x = t.normalized()
        y = z.cross(x)

        rv3d = context.region_data
        # Columns = world directions of the view right/up/backward axes
        rv3d.view_rotation = Matrix((x, y, z)).transposed().to_quaternion()
        pts = list(geo['verts_3d'].values())
        center = sum(pts, Vector((0.0, 0.0, 0.0))) / len(pts)
        radius = max((p - center).length for p in pts)
        rv3d.view_location = center
        if radius > 1e-6:
            rv3d.view_distance = radius * 2.0
        return True

    def _sync_uv_editor(self, context):
        """Make every island fully visible in the UV editor and mirror
        the active island into the UV selection there.

        The UV editor only shows UVs of selected, visible mesh faces —
        islands expanded past the original selection (or with hidden
        faces) would otherwise appear cut off."""
        if not (0 <= self.active_island_idx < len(self.islands_data)):
            return
        face_lookup = {f.index: f for f in self.bm.faces}
        for isl in self.islands:
            for fi in isl:
                f = face_lookup.get(fi)
                if f is None:
                    continue
                if f.hide:
                    f.hide_set(False)
                if not f.select:
                    f.select_set(True)
        active_loops = set()
        for lp in self.islands_data[self.active_island_idx]['loops']:
            active_loops.add(lp)
        use_new = hasattr(next(iter(active_loops)), 'uv_select_vert') \
            if active_loops else False
        for f in self.bm.faces:
            if not f.select:
                continue
            for lp in f.loops:
                state = lp in active_loops
                if use_new:
                    lp.uv_select_vert = state
                    lp.uv_select_edge = state
                else:
                    lp[self.uv_layer].select = state
        bmesh.update_edit_mesh(context.active_object.data,
                               loop_triangles=False, destructive=False)
        for win in context.window_manager.windows:
            for area in win.screen.areas:
                if area.type == 'IMAGE_EDITOR':
                    area.tag_redraw()

    def _update_cursor_3d(self):
        best_dist, best_pos = 1e10, None
        for idata in self.islands_data:
            geo = idata.get('geo3d')
            if not geo:
                continue
            for uv_key, pos3d in geo['verts_3d'].items():
                d = (Vector(uv_key) - self.uv_cursor).length
                if d < best_dist:
                    best_dist, best_pos = d, pos3d
        self.cursor_3d = best_pos

    # ------------------------------------------------------------------
    # Mesh update helpers
    # ------------------------------------------------------------------

    def _push_mesh(self, context, loop_triangles=True):
        """Push the bmesh to the mesh and tag the depsgraph. Blender 5.2
        no longer refreshes the edit-mode material/texture draw cache on
        bmesh.update_edit_mesh alone: without the explicit tag the UVs
        change in the data but the viewport keeps showing the old ones."""
        me = context.active_object.data
        bmesh.update_edit_mesh(me, loop_triangles=loop_triangles)
        me.update_tag()

    def _update_mesh(self, context):
        """Full mesh update + data rebuild after a discrete UV operation."""
        self._push_mesh(context)
        self.rebuild_data(context)

    def _update_mesh_live(self, context):
        """Lightweight update for continuous transforms (every mouse
        move). A heavy modifier stack makes this slow: Shift+Q pauses
        the stack for the session."""
        self._check_tile_bounds()
        self._push_mesh(context, loop_triangles=False)
        self._refresh_active(context)

    def _set_modifiers_paused(self, context, paused):
        """Pause / resume edit-mode evaluation of the object's modifier
        stack; remembers which ones it touched so only those come back."""
        obj = context.active_object
        if obj is None:
            return
        if paused:
            if self._suspended_mods:
                return
            for mod in obj.modifiers:
                if mod.show_in_editmode:
                    self._suspended_mods.append(mod.name)
                    mod.show_in_editmode = False
        else:
            for name in self._suspended_mods:
                mod = obj.modifiers.get(name)
                if mod is not None:
                    mod.show_in_editmode = True
            self._suspended_mods = []

    def _adjust_sensitivity(self, up):
        if up:
            self.grab_sensitivity = min(
                self.grab_sensitivity * GRAB_SENS_STEP, GRAB_SENS_MAX)
        else:
            self.grab_sensitivity = max(
                self.grab_sensitivity / GRAB_SENS_STEP, GRAB_SENS_MIN)

    def _refresh_active(self, context):
        """Lightweight refresh of selected islands so helpers track
        live UV coordinates during interactive transforms."""
        obj = context.active_object
        world = obj.matrix_world
        for idx in self.selected_islands:
            if not (0 <= idx < len(self.islands)):
                continue
            island = self.islands[idx]
            idata = get_island_uv_data(self.bm, island, self.uv_layer)
            if not idata:
                continue
            idata['face_indices'] = island
            geo = get_island_3d_data(
                self.bm, island, self.uv_layer, world)
            if geo:
                idata['geo3d'] = geo
            self.islands_data[idx] = idata

    # ------------------------------------------------------------------
    # Hit testing
    # ------------------------------------------------------------------

    def hit_test(self, context, mx, my):
        region, rv3d = context.region, context.region_data
        mouse = Vector((mx, my))
        self.hover_island_idx = -1
        self.hover_vert_key = None
        self.hover_edge_3d = None
        self.hover_edge_uv = None
        self.hover_edge_id = None
        self.hover_rotate_handle = False
        self.hover_handle = None

        # Edge-pick modes look at edges only: handles and vertices would
        # otherwise swallow the hover near corners and the click would
        # silently do nothing.
        edges_only = self.state in EDGE_PICK_STATES

        handles = None if edges_only else _compute_screen_handles(
            self, context)

        if handles:
            # Hit radius follows the themed handle size so bigger
            # handles stay clickable edge to edge
            theme = get_theme(context)
            hit_r = max(HIT_RADIUS,
                        theme.point_size_for(Role.HANDLE) * 0.5 + 8)
            for name in list(HANDLE_CORNERS) + list(HANDLE_MIDS):
                if name in handles and (mouse - handles[name]).length <= hit_r:
                    self.hover_handle = name
                    return
            rsp = handles.get('_ROT')
            if rsp and (mouse - rsp).length <= hit_r:
                self.hover_rotate_handle = True
                return
            csp = handles.get('_C')
            if csp and (mouse - csp).length <= hit_r:
                self.hover_handle = 'CENTER'
                return

        # Candidates within the hit radius are tried nearest-first and
        # the first one not hidden behind the mesh wins, so picking
        # never goes through to the back side.
        bvh, winv = self._pick_bvh, self._world_inv

        # Vertices
        cands = []
        for idx, idata in enumerate(self.islands_data):
            geo = idata.get('geo3d')
            if not geo or edges_only:
                continue
            for uv_key, pos3d in geo['verts_3d'].items():
                sp = location_3d_to_region_2d(region, rv3d, pos3d)
                if sp is None:
                    continue
                d = (mouse - sp).length
                if d <= HIT_RADIUS:
                    cands.append((d, idx, uv_key, pos3d, sp))
        cands.sort(key=lambda c: c[0])
        for d, idx, uv_key, pos3d, sp in cands:
            if _point_visible(context, bvh, winv, pos3d, sp):
                self.hover_island_idx = idx
                self.hover_vert_key = uv_key
                return

        # Edges
        cands = []
        for idx, idata in enumerate(self.islands_data):
            geo = idata.get('geo3d')
            if not geo:
                continue
            loop_ids = geo['edge_loop_ids']
            for i, ((uv_a, uv_b), (pa, pb)) in enumerate(
                    geo['edge_uv_pairs']):
                spa = location_3d_to_region_2d(region, rv3d, pa)
                spb = location_3d_to_region_2d(region, rv3d, pb)
                if spa is None or spb is None:
                    continue
                d = _seg_dist_2d(mouse, spa, spb)
                if d <= HIT_RADIUS:
                    cands.append((d, idx, (pa, pb), (uv_a, uv_b),
                                  (spa + spb) * 0.5, loop_ids[i]))
        cands.sort(key=lambda c: c[0])
        for d, idx, e3d, euv, smid, lid in cands:
            mid = (e3d[0] + e3d[1]) * 0.5
            if _point_visible(context, bvh, winv, mid, smid):
                self.hover_island_idx = idx
                self.hover_edge_3d = e3d
                self.hover_edge_uv = euv
                self.hover_edge_id = lid
                return

        # Face fill -- click anywhere on the visible surface
        for idx, idata in enumerate(self.islands_data):
            geo = idata.get('geo3d')
            if not geo:
                continue
            for v0, v1, v2 in geo['face_tris']:
                s0 = location_3d_to_region_2d(region, rv3d, v0)
                s1 = location_3d_to_region_2d(region, rv3d, v1)
                s2 = location_3d_to_region_2d(region, rv3d, v2)
                if s0 is None or s1 is None or s2 is None:
                    continue
                if _bary_coords((mx, my),
                                (s0.x, s0.y), (s1.x, s1.y),
                                (s2.x, s2.y)) is not None:
                    self.hover_island_idx = idx
                    return

    def _screen_to_uv(self, context, mx, my):
        """Convert a screen pixel position to a UV coordinate by finding
        the face triangle under the mouse and interpolating UV via
        barycentric coordinates.  Returns Vector or None."""
        region, rv3d = context.region, context.region_data
        for idata in self.islands_data:
            geo = idata.get('geo3d')
            if not geo:
                continue
            for (ua, ub, uc), (pa, pb, pc) in geo.get('uv_tris', []):
                sa = location_3d_to_region_2d(region, rv3d, pa)
                sb = location_3d_to_region_2d(region, rv3d, pb)
                sc = location_3d_to_region_2d(region, rv3d, pc)
                if sa is None or sb is None or sc is None:
                    continue
                bc = _bary_coords((mx, my),
                                  (sa.x, sa.y), (sb.x, sb.y), (sc.x, sc.y))
                if bc is not None:
                    w, u, v = bc
                    return Vector((ua[0] * w + ub[0] * u + uc[0] * v,
                                   ua[1] * w + ub[1] * u + uc[1] * v))
        return None

    # ------------------------------------------------------------------
    # Invoke / Modal
    # ------------------------------------------------------------------

    def invoke(self, context, event):
        obj = context.active_object
        if not obj or obj.type != 'MESH' or obj.mode != 'EDIT':
            self.report({'WARNING'}, "Must be in Edit Mode on a mesh")
            return {'CANCELLED'}
        self.bm = bmesh.from_edit_mesh(obj.data)
        self.uv_layer = get_uv_layer(self.bm)
        if not any(f.select for f in self.bm.faces):
            self.report({'WARNING'}, "No faces selected")
            return {'CANCELLED'}

        self._area = context.area
        self._region = context.region
        self.state = STATE_IDLE
        self.active_island_idx = 0
        self.hover_island_idx = -1
        self.hover_vert_key = None
        self.hover_edge_3d = None
        self.hover_edge_uv = None
        self.hover_edge_id = None
        self.hover_rotate_handle = False
        self.hover_handle = None
        self.grab_axis = None
        self._warp_acc = Vector((0.0, 0.0))
        # Edge selection as (island, face index, loop position): loop
        # ids survive UV transforms, UV coordinates do not.
        self.sel_edges = []
        # Loop ids pinned during this session; released on exit so the
        # tool leaves no pins behind that the user did not have before.
        self._session_pins = set()
        self.tile_limit = self.tile_limit_prop
        self.unwrap_method = self.unwrap_method_prop
        self.unwrap_keep_flip = self.unwrap_keep_flip_prop
        self.grab_sensitivity = self.grab_sensitivity_prop
        step_val = self.rotation_step_prop
        self.rotation_step_idx = (
            ROTATION_STEPS.index(step_val)
            if step_val in ROTATION_STEPS else ROTATION_STEP_DEFAULT_IDX)
        self.pivot_mode = PIVOT_CENTER
        self.transform_scope = SCOPE_ALL
        self.uv_cursor = Vector((0.5, 0.5))
        self.cursor_3d = None
        self.mouse_x = self.mouse_y = 0
        self.drag_start = None
        self.drag_start_angle = 0.0
        self.drag_center_screen = None
        self.pre_drag_cache = None
        self.density_ref_island = -1
        self.stitch_src = None
        self.stitch_target = None
        self.stitch_same_side = False
        self.stitch_keep_scale = False
        self.stitch_scale = 1.0
        self.align_flip = False
        self.align_angle = 0.0
        self.align_pivot = None
        self.stitch_pool = None
        self.stitch_pool_view = None
        # Object-space BVH of the mesh for pick occlusion. Geometry is
        # fixed for the session (only UVs move) so it is built once.
        self._pick_bvh = BVHTree.FromBMesh(self.bm)
        self._world_inv = obj.matrix_world.inverted()
        self.scale_handle_name = None
        self.transform_pivot_uv = None
        self.drag_handle_screen = None
        self.uv_screen_u = None
        self.uv_screen_v = None
        self.current_angle_delta = 0.0
        self.current_scale_x = 1.0
        self.current_scale_y = 1.0

        self.uv_cache = cache_all_uvs(self.bm, self.uv_layer)
        self.undo_stack = []
        self.redo_stack = []

        self.islands = []
        self.islands_data = []
        self.selected_islands = set()
        self.rebuild_data(context)
        if not self.islands_data:
            self.report({'WARNING'}, "No UV islands found on selected faces")
            return {'CANCELLED'}
        self.selected_islands = set(range(len(self.islands_data)))
        # The island holding the mesh's active face starts as the active
        # island, so reference-based actions (D, density, align) use the
        # face the user marked active instead of an arbitrary first island.
        active_face = self.bm.faces.active
        if active_face is not None:
            for idx, idata in enumerate(self.islands_data):
                if active_face.index in idata['face_indices']:
                    self.active_island_idx = idx
                    break

        self._overlay_was_on = context.space_data.overlay.show_overlays
        # Shift+Q pauses the edit-mode modifier stack for the session
        # (some GN setups rebuild UVs and hide every preview); restored
        # on exit.
        self._suspended_mods = []
        # Clean view (the Q mode) is on by default: Blender overlays and
        # the island fills stay hidden so textures are readable, only
        # the gizmo remains. Q toggles it all back. Restored on exit.
        self._clean_view = True
        context.space_data.overlay.show_overlays = False

        self._hud, self._help = _build_visual_uv_hud(context)
        self._hud.bind_region(context.region)
        self._help.bind_region(context.region)
        self._last_event = capture_event(event, getattr(self, "_last_event", None))

        self._handle_3d = safe_handler_add(
            bpy.types.SpaceView3D, draw_3d_callback, (self, context), 'WINDOW', 'POST_VIEW', tick=True)
        self._handle_pixel = safe_handler_add(
            bpy.types.SpaceView3D, draw_pixel_callback, (self, context), 'WINDOW', 'POST_PIXEL', tick=True)
        self._handle_shortcuts = safe_handler_add(
            bpy.types.SpaceView3D, draw_shortcuts_callback, (self, context), 'WINDOW', 'POST_PIXEL', tick=True)
        self._timer = context.window_manager.event_timer_add(
            0.05, window=context.window)

        context.window_manager.modal_handler_add(self)
        context.workspace.status_text_set(
            "Visual UV | G: Grab | R: Rotate | S: Scale | "
            "X/Y: Axis | Alt+Scroll: Sensitivity | "
            "Enter / Space: Confirm | Esc: Cancel")
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if context.area:
            context.area.tag_redraw()

        if event.alt and event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            self._adjust_sensitivity(event.type == 'WHEELUPMOUSE')
            pct = int(self.grab_sensitivity / GRAB_SENS_DEFAULT * 100)
            self.report({'INFO'}, f"Sensitivity: {pct}%")
            return {'RUNNING_MODAL'}

        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE',
                          'NDOF_MOTION', 'NDOF_BUTTON_PANZOOM'}:
            return {'PASS_THROUGH'}

        self.mouse_x = event.mouse_region_x
        self.mouse_y = event.mouse_region_y
        self._last_event = capture_event(event, getattr(self, "_last_event", None))
        try:
            theme_prefs = context.preferences.addons["InteractionOps"]\
                .preferences.iops_theme
        except (KeyError, AttributeError):
            theme_prefs = None
        if theme_prefs is not None:
            helpo = getattr(self, "_help", None) or getattr(self, "help", None)
            hud = getattr(self, "_hud", None) or getattr(self, "hud", None)
            if helpo is not None and helpo.handle_drag_event(context, event, theme_prefs):
                return {'RUNNING_MODAL'}
            if hud is not None and hud.handle_drag_event(context, event, theme_prefs):
                return {'RUNNING_MODAL'}
            if helpo is not None and helpo.handle_toggle_event(event, theme_prefs):
                return {'RUNNING_MODAL'}
            if hud is not None and hud.handle_param_toggle_event(event, theme_prefs):
                return {'RUNNING_MODAL'}

        if self.state in (STATE_GRAB, STATE_ROTATE, STATE_SCALE,
                          STATE_HANDLE_SCALE, STATE_HANDLE_ROTATE,
                          STATE_STITCH_DRAG, STATE_ALIGN_DRAG):
            return self._modal_transform(context, event)

        if (self.state in PICK_STATES and event.value == 'PRESS'
                and event.type in {'ESC', 'RIGHTMOUSE'}):
            self._end_pick()
            return {'RUNNING_MODAL'}

        if event.type == 'ESC' and event.value == 'PRESS':
            restore_uvs(self.uv_cache, self.uv_layer)
            self._push_mesh(context)
            self._cleanup(context)
            self.report({'INFO'}, "Visual UV cancelled")
            return {'CANCELLED'}

        if (event.type in {'RET', 'NUMPAD_ENTER', 'SPACE'}
                and event.value == 'PRESS'):
            self._push_mesh(context)
            self._cleanup(context)
            self.tile_limit_prop = self.tile_limit
            self.grab_sensitivity_prop = self.grab_sensitivity
            self.rotation_step_prop = ROTATION_STEPS[self.rotation_step_idx]
            self.unwrap_method_prop = self.unwrap_method
            self.unwrap_keep_flip_prop = self.unwrap_keep_flip
            self.report({'INFO'}, "Visual UV applied")
            return {'FINISHED'}

        self.hit_test(context, event.mouse_region_x,
                      event.mouse_region_y)

        if event.type == 'Z' and event.value == 'PRESS' and event.ctrl:
            self._redo(context) if event.shift else self._undo(context)
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            return self._on_lmb(context, event)

        if event.value == 'PRESS':
            return self._on_key(context, event)

        return {'RUNNING_MODAL'}

    def _wrap_cursor(self, context, mx, my):
        """Continuous grab for WRAP_STATES: the virtual mouse position
        (physical + accumulated offset) stays continuous while the real
        cursor is warped back in from the opposite region edge."""
        acc = self._warp_acc
        vx, vy = mx + acc.x, my + acc.y
        region = context.region
        w, h = region.width, region.height
        nx, ny = mx, my
        if mx < 0:
            nx = max(mx + w, 1)
        elif mx >= w:
            nx = min(mx - w, w - 2)
        if my < 0:
            ny = max(my + h, 1)
        elif my >= h:
            ny = min(my - h, h - 2)
        if (nx, ny) != (mx, my):
            acc.x += mx - nx
            acc.y += my - ny
            context.window.cursor_warp(region.x + nx, region.y + ny)
        return vx, vy

    def _modal_transform(self, context, event):
        mx, my = event.mouse_region_x, event.mouse_region_y
        if self.state in WRAP_STATES:
            mx, my = self._wrap_cursor(context, mx, my)

        if (event.ctrl
                and event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}
                and self.state in (STATE_ROTATE, STATE_HANDLE_ROTATE)):
            if event.type == 'WHEELUPMOUSE':
                self.rotation_step_idx = min(
                    self.rotation_step_idx + 1, len(ROTATION_STEPS) - 1)
            else:
                self.rotation_step_idx = max(
                    self.rotation_step_idx - 1, 0)
            self._apply_rotate(context, mx, my, event)
            return {'RUNNING_MODAL'}

        if event.alt and event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            self._adjust_sensitivity(event.type == 'WHEELUPMOUSE')
            return {'RUNNING_MODAL'}

        # Confirm: LMB release for handle-driven, LMB press / Enter for keys
        is_handle = self.state in (STATE_HANDLE_SCALE, STATE_HANDLE_ROTATE)
        lmb_confirm = (event.type == 'LEFTMOUSE'
                       and ((is_handle and event.value == 'RELEASE')
                            or (not is_handle and event.value == 'PRESS')))
        if lmb_confirm or (event.type in {'RET', 'NUMPAD_ENTER', 'SPACE'}
                           and event.value == 'PRESS'):
            if self.state == STATE_STITCH_DRAG and self.stitch_target is None:
                # Nothing snapped: confirming would just end the drag.
                return {'RUNNING_MODAL'}
            back_to = self._pick_state_after_drag()
            if self.pre_drag_cache:
                self.undo_stack.append(self.pre_drag_cache)
                self.redo_stack.clear()
            self._update_mesh(context)
            self._end_transform()
            if back_to:
                # Edge tools are almost always a series: stay in pick
                # mode for the next source edge, RMB / Esc leave it.
                self._enter_pick(context, back_to)
            return {'RUNNING_MODAL'}

        # Cancel
        if event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            back_to = self._pick_state_after_drag()
            if self.pre_drag_cache:
                restore_uvs(self.pre_drag_cache, self.uv_layer)
            if back_to:
                self._restore_stitch_selection()
            self._update_mesh(context)
            self._end_transform()
            if back_to:
                # One step back: drop the source, keep picking.
                self._enter_pick(context, back_to)
            return {'RUNNING_MODAL'}

        if (event.type in {'X', 'Y'} and event.value == 'PRESS'
                and self.state in (STATE_GRAB, STATE_SCALE,
                                   STATE_HANDLE_SCALE)):
            new_axis = event.type
            self.grab_axis = new_axis if self.grab_axis != new_axis else None
            return {'RUNNING_MODAL'}

        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            return {'PASS_THROUGH'}

        if self.state == STATE_STITCH_DRAG and event.value == 'PRESS':
            # Toggles, not holds: a held modifier plus a click to
            # confirm is awkward, and X/Y axis locks already toggle.
            if event.type in {'LEFT_SHIFT', 'RIGHT_SHIFT'}:
                self.stitch_same_side = not self.stitch_same_side
                self._apply_stitch(context, mx, my)
                return {'RUNNING_MODAL'}
            if event.type in {'LEFT_CTRL', 'RIGHT_CTRL'}:
                self.stitch_keep_scale = not self.stitch_keep_scale
                self._apply_stitch(context, mx, my)
                return {'RUNNING_MODAL'}

        if (self.state == STATE_ALIGN_DRAG and event.value == 'PRESS'
                and event.type in {'LEFT_SHIFT', 'RIGHT_SHIFT'}):
            self.align_flip = not self.align_flip
            self._apply_align(context, mx, my)
            return {'RUNNING_MODAL'}

        if event.type == 'MOUSEMOVE':
            if self.state == STATE_STITCH_DRAG:
                self._apply_stitch(context, mx, my)
            elif self.state == STATE_ALIGN_DRAG:
                self._apply_align(context, mx, my)
            elif self.state == STATE_GRAB:
                self._apply_grab(context, mx, my, event)
            elif self.state in (STATE_ROTATE, STATE_HANDLE_ROTATE):
                self._apply_rotate(context, mx, my, event)
            elif self.state in (STATE_SCALE, STATE_HANDLE_SCALE):
                self._apply_scale(context, mx, my, event)

        return {'RUNNING_MODAL'}

    def _cleanup(self, context):
        if hasattr(self, '_overlay_was_on'):
            context.space_data.overlay.show_overlays = self._overlay_was_on
        self._set_modifiers_paused(context, False)
        self._release_session_pins(context)
        for h in (self._handle_3d, self._handle_pixel,
                  self._handle_shortcuts):
            if h:
                try:
                    safe_handler_remove(h, bpy.types.SpaceView3D, 'WINDOW')
                except ValueError:
                    pass
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
        context.workspace.status_text_set(None)
        context.window.cursor_modal_restore()
        self._handle_3d = self._handle_pixel = None
        self._handle_shortcuts = self._timer = None

    def _transform_targets(self):
        """Islands G/R/S/F/N act on: all session islands, or just the
        active one when the scope is switched with I."""
        if self.transform_scope == SCOPE_ACTIVE:
            if 0 <= self.active_island_idx < len(self.islands_data):
                return {self.active_island_idx}
            return set()
        return self.selected_islands

    def _enter_pick(self, context, state, msg=None):
        """Switch to a click-to-pick sub-mode: crosshair cursor so the
        mode is visible even with the HUD hidden."""
        self.state = state
        context.window.cursor_modal_set('CROSSHAIR')
        if msg:
            self.report({'INFO'}, msg)

    def _end_pick(self):
        self.state = STATE_IDLE
        self.stitch_src = None
        self.stitch_target = None
        self.stitch_pool = None
        self.density_ref_island = -1
        bpy.context.window.cursor_modal_restore()

    def _pick_state_after_drag(self):
        """Pick state an edge-drag returns to on confirm / cancel, or
        None for the plain transforms and for drags started from the
        edge selection (those are one-shot)."""
        if self.stitch_src and self.stitch_src.get('from_selection'):
            return None
        if self.state == STATE_STITCH_DRAG:
            return STATE_PICK_STITCH_SRC
        if self.state == STATE_ALIGN_DRAG:
            return STATE_PICK_ALIGN_EDGE
        return None

    def _hover_edge_src(self):
        """The hovered edge as an edge-tool source dict, or None."""
        if self.hover_edge_uv is None or self.hover_island_idx < 0:
            return None
        return {'island': self.hover_island_idx,
                'edge_uv': (self.hover_edge_uv[0].copy(),
                            self.hover_edge_uv[1].copy()),
                'edge_3d': self.hover_edge_3d,
                'id': self.hover_edge_id}

    def _resolve_edge(self, e):
        """Current UV / 3D data of a selected edge, or None when its
        face left the session. Islands may split (unwrap), so the face
        is looked up again when it is no longer in the recorded one."""
        fi, li = e['face'], e['loop']
        island = e['island']
        if not (0 <= island < len(self.islands)
                and fi in self.islands[island]):
            island = next((i for i, isl in enumerate(self.islands)
                           if fi in isl), -1)
            if island < 0:
                return None
            e['island'] = island
        geo = self.islands_data[island].get('geo3d')
        if not geo:
            return None
        try:
            idx = geo['edge_loop_ids'].index((fi, li))
        except ValueError:
            return None
        (uv_a, uv_b), (pa, pb) = geo['edge_uv_pairs'][idx]
        return {'island': island, 'edge_uv': (uv_a.copy(), uv_b.copy()),
                'edge_3d': (pa, pb), 'id': (fi, li)}

    def _resolved_sel_edges(self):
        out = []
        for e in self.sel_edges:
            r = self._resolve_edge(e)
            if r is not None:
                out.append(r)
        return out

    def _active_sel_edge(self):
        """Last selected edge, resolved, or None."""
        for e in reversed(self.sel_edges):
            r = self._resolve_edge(e)
            if r is not None:
                return r
        return None

    def _selection_src(self):
        """Edge-tool source built from the edge selection: one edge as
        is, several as a chain on the active edge's island. The chain's
        end-to-end span gives the direction, its path length the size
        that stitch fits into the target edge."""
        sel = self._resolved_sel_edges()
        if not sel:
            return None
        if len(sel) == 1:
            return sel[0]
        island = sel[-1]['island']
        segs = [e for e in sel if e['island'] == island]
        keys = {}
        degree = {}
        for e in segs:
            for uv, p3 in zip(e['edge_uv'], e['edge_3d']):
                k = uv_point_key(uv)
                keys.setdefault(k, (uv, p3))
                degree[k] = degree.get(k, 0) + 1
        ends = [k for k, d in degree.items() if d % 2 == 1]
        if len(ends) != 2:
            # Not one open chain: span the two farthest points.
            pts = list(keys)
            best, ends = -1.0, pts[:2]
            for i, a in enumerate(pts):
                for b in pts[i + 1:]:
                    d = (Vector(a) - Vector(b)).length_squared
                    if d > best:
                        best, ends = d, [a, b]
        (uv_a, p_a), (uv_b, p_b) = keys[ends[0]], keys[ends[1]]
        if (uv_a - uv_b).length < 1e-8:
            return segs[-1]
        return {
            'island': island,
            'edge_uv': (uv_a.copy(), uv_b.copy()),
            'edge_3d': (p_a, p_b),
            'id': segs[-1]['id'],
            'segments_3d': [e['edge_3d'] for e in segs],
            'path_len': sum((e['edge_uv'][1] - e['edge_uv'][0]).length
                            for e in segs),
            'n_edges': len(segs),
        }

    def _select_hover_edge(self, extend):
        """LMB on an edge in idle: plain click makes it the only
        selected edge, Shift+click toggles it in the selection."""
        lid = self.hover_edge_id
        entry = {'island': self.hover_island_idx,
                 'face': lid[0], 'loop': lid[1]}
        existing = [e for e in self.sel_edges
                    if (e['face'], e['loop']) == lid]
        if extend:
            if existing:
                self.sel_edges = [e for e in self.sel_edges
                                  if (e['face'], e['loop']) != lid]
            else:
                self.sel_edges.append(entry)
        else:
            self.sel_edges = [entry]

    def _loop_id(self, loop):
        face = loop.face
        for i, l in enumerate(face.loops):
            if l == loop:
                return (face.index, i)
        return None

    def _toggle_pins(self, context, idata, keys):
        """Toggle pins at the point_loops keys of one island and keep
        the session-pin bookkeeping in step."""
        pinned, changed = toggle_pins_uv(idata['point_loops'],
                                         self.uv_layer, keys)
        ids = {self._loop_id(l) for l in changed}
        ids.discard(None)
        if pinned:
            self._session_pins |= ids
        else:
            self._session_pins -= ids
        return pinned, len(changed)

    def _release_session_pins(self, context):
        if not self._session_pins:
            return
        bm = self.bm
        bm.faces.ensure_lookup_table()
        for fi, li in self._session_pins:
            if fi < len(bm.faces):
                loops = bm.faces[fi].loops
                if li < len(loops):
                    loops[li][self.uv_layer].pin_uv = False
        self._session_pins = set()
        self._push_mesh(context, loop_triangles=False)

    def _begin_edge_drag(self, context, state, src, from_selection=False):
        """Start a two-click edge tool from src (see _hover_edge_src):
        the source island becomes active for the drag (the live refresh
        tracks the active set) and the selection side effect is undone
        on cancel."""
        island = src['island']
        self.stitch_src = {
            'island': island,
            'edge_uv': src['edge_uv'],
            'edge_3d': src['edge_3d'],
            'segments_3d': src.get('segments_3d'),
            'path_len': src.get('path_len'),
            'n_edges': src.get('n_edges', 1),
            'prev_active': self.active_island_idx,
            'was_selected': island in self.selected_islands,
            'from_selection': from_selection,
        }
        self.active_island_idx = island
        self.selected_islands.add(island)
        self.stitch_target = None
        self.pre_drag_cache = cache_all_uvs(self.bm, self.uv_layer)
        self.state = state

    def _start_align_drag(self, context, src, from_selection=False):
        self._build_stitch_pool(context, src['island'])
        idata = self.islands_data[src['island']]
        self.align_pivot = _get_pivot_uv(self, idata)
        self.align_flip = False
        self._begin_edge_drag(context, STATE_ALIGN_DRAG, src,
                              from_selection)
        self._apply_align(context, self.mouse_x, self.mouse_y)
        self.report({'INFO'},
                    "Align: hover a target edge (or none for axis), "
                    "LMB confirm, Shift flip")

    def _start_stitch_drag(self, context, src, from_selection=False):
        self._build_stitch_pool(context, src['island'])
        if not self.stitch_pool:
            self.report({'WARNING'}, "Stitch: no other UV island to snap to")
            self._end_pick()
            return False
        self._begin_edge_drag(context, STATE_STITCH_DRAG, src,
                              from_selection)
        self.report({'INFO'},
                    "Stitch: move to target edge, LMB confirm, "
                    "Shift flip side, Ctrl keep scale")
        return True

    def _restore_stitch_selection(self):
        """Undo the active/selected side effect of picking a stitch
        source (the source must be active during the drag so the live
        refresh tracks it)."""
        src = self.stitch_src
        if not src:
            return
        self.active_island_idx = src['prev_active']
        if not src['was_selected']:
            self.selected_islands.discard(src['island'])

    def _end_transform(self):
        self.state = STATE_IDLE
        self.stitch_src = None
        self.stitch_target = None
        self.stitch_pool = None
        bpy.context.window.cursor_modal_restore()
        self.pre_drag_cache = None
        self.transform_pivot_uv = None
        self.drag_handle_screen = None
        self.scale_handle_name = None
        self.grab_axis = None
        self.uv_screen_u = None
        self.uv_screen_v = None

    # ------------------------------------------------------------------
    # Tile bounds
    # ------------------------------------------------------------------

    def _check_tile_bounds(self):
        """If any selected island exceeds tile_limit tiles from the 0-1
        area, snap it back so its center sits at (0.5, 0.5). Off when
        the limit is 0."""
        uv = self.uv_layer
        lim = self.tile_limit
        if lim <= 0:
            return
        for idx in self.selected_islands:
            if not (0 <= idx < len(self.islands_data)):
                continue
            idata = self.islands_data[idx]
            min_u = min_v = 1e10
            max_u = max_v = -1e10
            seen = set()
            for loop in idata['loops']:
                lid = id(loop)
                if lid in seen:
                    continue
                seen.add(lid)
                u, v = loop[uv].uv.x, loop[uv].uv.y
                min_u, max_u = min(min_u, u), max(max_u, u)
                min_v, max_v = min(min_v, v), max(max_v, v)
            if (min_u < -lim or max_u > 1.0 + lim
                    or min_v < -lim or max_v > 1.0 + lim):
                cx = (min_u + max_u) * 0.5
                cy = (min_v + max_v) * 0.5
                move_island_uv(idata['loops'], uv,
                               Vector((0.5 - cx, 0.5 - cy)))

    # ------------------------------------------------------------------
    # Undo / Redo
    # ------------------------------------------------------------------

    def _push_undo(self):
        self.undo_stack.append(cache_all_uvs(self.bm, self.uv_layer))
        self.redo_stack.clear()

    def _undo(self, context):
        if not self.undo_stack:
            self.report({'INFO'}, "Nothing to undo")
            return
        self.redo_stack.append(cache_all_uvs(self.bm, self.uv_layer))
        restore_uvs(self.undo_stack.pop(), self.uv_layer)
        self._update_mesh(context)

    def _redo(self, context):
        if not self.redo_stack:
            self.report({'INFO'}, "Nothing to redo")
            return
        self.undo_stack.append(cache_all_uvs(self.bm, self.uv_layer))
        restore_uvs(self.redo_stack.pop(), self.uv_layer)
        self._update_mesh(context)

    # ------------------------------------------------------------------
    # Begin transform
    # ------------------------------------------------------------------

    def _begin_transform(self, context, mode, pivot_uv=None,
                         pivot_screen=None, handle_screen=None):
        if not (0 <= self.active_island_idx < len(self.islands_data)):
            return False
        self.selected_islands.add(self.active_island_idx)
        idata = self.islands_data[self.active_island_idx]
        geo = idata.get('geo3d')
        if not geo:
            return False
        if pivot_uv is None:
            # Freeze the pivot for the whole drag: islands_data refreshes
            # from the transformed UVs on every mouse move, so re-reading
            # the center mid-drag makes the pivot chase the rotation and
            # the island drifts away.
            pivot_uv = _get_pivot_uv(self, idata)
        region, rv3d = context.region, context.region_data
        handles = _compute_screen_handles(self, context)
        if pivot_screen is not None:
            csp = pivot_screen
        else:
            # Angles/scales are measured around the screen projection of
            # the actual UV pivot (island center), NOT the gizmo box
            # center — they differ on curved islands and a mismatch
            # makes rotation orbit instead of spin.
            prefs = bpy.context.preferences.addons[
                "InteractionOps"].preferences
            noff = getattr(prefs, 'visual_uv_normal_offset', NORMAL_OFFSET)
            center = _island_center_3d(idata) + geo['normal_avg'] * noff
            csp = location_3d_to_region_2d(region, rv3d, center)
            if csp is None and handles:
                csp = handles.get('_C')
        if not csp:
            return False

        self.pre_drag_cache = cache_all_uvs(self.bm, self.uv_layer)
        self._warp_acc = Vector((0.0, 0.0))
        self.drag_start = Vector((self.mouse_x, self.mouse_y))
        self.drag_center_screen = csp
        self.transform_pivot_uv = pivot_uv
        self.drag_handle_screen = handle_screen
        ref = handle_screen if handle_screen else self.drag_start
        self.drag_start_angle = math.atan2(ref.y - csp.y, ref.x - csp.x)
        self.current_angle_delta = 0.0
        self.current_scale_x = 1.0
        self.current_scale_y = 1.0

        self.uv_screen_u = handles.get('_u_dir')
        self.uv_screen_v = handles.get('_v_dir')

        self.state = mode
        return True

    def _handle_pivot_data(self, context, handle_name):
        """Return (pivot_uv, pivot_screen, handle_screen) for
        handle-based transforms where the opposite handle is the pivot."""
        idata = self.islands_data[self.active_island_idx]
        opp = HANDLE_OPPOSITE[handle_name]
        piv_uv = _handle_uv_pos(idata, opp)
        handles = _compute_screen_handles(self, context)
        piv_scr = handles.get(opp) if handles else None
        h_scr = handles.get(handle_name) if handles else None
        return piv_uv, piv_scr, h_scr

    # ------------------------------------------------------------------
    # Apply transforms
    # ------------------------------------------------------------------

    def _build_stitch_pool(self, context, src_idx):
        """Snap targets: every UV island except the source -- the other
        session islands plus all unselected visible islands of the mesh.
        Each entry: {'loops', 'edges': [(uv_a, uv_b, p3d_a, p3d_b)]}.
        Interior edges are included: hiding them reads as "some edges
        do not work" rather than as a rule."""
        world = context.active_object.matrix_world
        pool = []
        for idx, island in enumerate(self.islands):
            if idx == src_idx:
                continue
            edges, loops = collect_island_edges(
                self.bm, island, self.uv_layer, world, boundary_only=False)
            pool.append({'loops': loops, 'edges': edges})
        for island in get_unselected_face_islands(self.bm, self.uv_layer):
            edges, loops = collect_island_edges(
                self.bm, island, self.uv_layer, world, boundary_only=False)
            pool.append({'loops': loops, 'edges': edges})
        self.stitch_pool = pool
        self.stitch_pool_view = None

    def _project_stitch_pool(self, context):
        """Cache screen-space endpoints per pool edge; redo only when
        the view changes."""
        region, rv3d = context.region, context.region_data
        key = (tuple(rv3d.view_matrix.col[0]), tuple(rv3d.view_matrix.col[1]),
               tuple(rv3d.view_matrix.col[2]), tuple(rv3d.view_matrix.col[3]),
               rv3d.view_distance, rv3d.view_perspective,
               region.width, region.height)
        if self.stitch_pool_view == key:
            return
        for entry in self.stitch_pool:
            entry['screen'] = [
                (location_3d_to_region_2d(region, rv3d, pa),
                 location_3d_to_region_2d(region, rv3d, pb))
                for (_, _, pa, pb) in entry['edges']]
        self.stitch_pool_view = key

    def _nearest_pool_edge(self, context, mx, my):
        """Closest pool edge within STITCH_SNAP_PX of the mouse, or None."""
        if not self.stitch_pool:
            return None
        self._project_stitch_pool(context)
        mouse = Vector((mx, my))
        cands = []
        for entry in self.stitch_pool:
            for (uv_a, uv_b, pa, pb), (spa, spb) in zip(entry['edges'],
                                                        entry['screen']):
                if spa is None or spb is None:
                    continue
                d = _seg_dist_2d(mouse, spa, spb)
                if d <= STITCH_SNAP_PX:
                    cands.append((d, entry, (uv_a, uv_b), (pa, pb),
                                  (spa + spb) * 0.5))
        cands.sort(key=lambda c: c[0])
        for d, entry, euv, e3d, smid in cands:
            mid = (e3d[0] + e3d[1]) * 0.5
            if _point_visible(context, self._pick_bvh, self._world_inv,
                              mid, smid):
                return {'entry': entry, 'edge_uv': euv, 'edge_3d': e3d}
        return None

    def _apply_stitch(self, context, mx, my):
        src = self.stitch_src
        if src is None or not self.pre_drag_cache:
            return
        target = self._nearest_pool_edge(context, mx, my)
        self.stitch_target = target
        self.stitch_scale = 1.0
        restore_uvs(self.pre_drag_cache, self.uv_layer)
        if target is not None:
            src_loops = self.islands_data[src['island']]['loops']
            dst_loops = target['entry']['loops']
            xf = stitch_island_to_edge_uv(
                src_loops, self.uv_layer,
                src['edge_uv'][0], src['edge_uv'][1],
                target['edge_uv'][0], target['edge_uv'][1],
                island_centroid_uv(dst_loops, self.uv_layer),
                same_side=self.stitch_same_side,
                keep_scale=self.stitch_keep_scale,
                src_length=src.get('path_len'))
            if xf is not None:
                self.stitch_scale = xf['scale']
        self._update_mesh_live(context)

    def _pin_axis(self, island_idx):
        """Line through the island's pins (the two farthest apart), or
        through the selected edge when it lies on that island; None
        when neither exists."""
        idata = self.islands_data[island_idx]
        pts = [Vector(k) for k in idata.get('pinned_keys', ())]
        axis = None
        if len(pts) >= 2:
            best = -1.0
            for i, a in enumerate(pts):
                for b in pts[i + 1:]:
                    d = (a - b).length_squared
                    if d > best:
                        best, axis = d, (a, b)
        if axis is None:
            e = self._active_sel_edge()
            if e is not None and e['island'] == island_idx:
                axis = e['edge_uv']
        return axis

    def _flip_island(self, island_idx):
        """Mirror an island across its pin axis, or horizontally about
        its centre when it has no pins (keeps the pins in place when
        there are any)."""
        idata = self.islands_data[island_idx]
        axis = self._pin_axis(island_idx)
        if axis is not None:
            flip_island_across_line_uv(idata['loops'], self.uv_layer,
                                       axis[0], axis[1])
        else:
            flip_island_uv(idata['loops'], self.uv_layer,
                           idata['center'].copy(), 'H')

    def _flip_across_pins(self, context):
        """Mirror the active island across the line through its pins
        (the two farthest apart), or across the selected edge when it
        lies on the active island: an unwrap with pinned edges can come
        out mirrored, this turns it over without moving the pins."""
        ai = self.active_island_idx
        if not (0 <= ai < len(self.islands_data)):
            return
        idata = self.islands_data[ai]
        axis = self._pin_axis(ai)
        if axis is None:
            self.report({'INFO'},
                        "Flip: pin an edge (M) or select one first")
            return
        self._push_undo()
        flip_island_across_line_uv(idata['loops'], self.uv_layer,
                                   axis[0], axis[1])
        self._update_mesh(context)
        self.report({'INFO'}, "Flipped across pins")

    def _unwrap_islands(self, context, island_indices):
        """Run Blender's unwrap on the given session islands only: the
        operator works on the face selection, so the rest of the
        selection is parked for the call and put back afterwards. The
        selection boundary acts as a seam, so each island unwraps on
        its own; pinned UVs stay where they are."""
        bm = self.bm
        me = context.active_object.data
        was_selected = [f.index for f in bm.faces if f.select]
        target = set()
        for idx in island_indices:
            if 0 <= idx < len(self.islands):
                target.update(self.islands[idx])
        for f in bm.faces:
            f.select_set(f.index in target)
        bm.select_flush_mode()
        bmesh.update_edit_mesh(me, loop_triangles=False)
        try:
            bpy.ops.uv.unwrap(method=self.unwrap_method, margin=0.001)
        finally:
            bm = self.bm = bmesh.from_edit_mesh(me)
            self.uv_layer = get_uv_layer(bm)
            bm.faces.ensure_lookup_table()
            keep = set(was_selected)
            for f in bm.faces:
                f.select_set(f.index in keep)
            bm.select_flush_mode()
            bmesh.update_edit_mesh(me, loop_triangles=False)

    def _apply_align(self, context, mx, my):
        """Rotate the source island so its picked edge runs parallel to
        the hovered target edge; with no target in snap range fall back
        to the nearest UV axis (the classic align)."""
        src = self.stitch_src
        if src is None or not self.pre_drag_cache:
            return
        target = (self._nearest_pool_edge(context, mx, my)
                  if self.stitch_pool else None)
        self.stitch_target = target
        restore_uvs(self.pre_drag_cache, self.uv_layer)
        loops = self.islands_data[src['island']]['loops']
        src_a, src_b = src['edge_uv']
        if target is not None:
            rot = align_island_to_edge_dir_uv(
                loops, self.uv_layer, src_a, src_b,
                target['edge_uv'][0], target['edge_uv'][1],
                self.align_pivot, flip=self.align_flip)
        else:
            rot = align_island_to_edge_uv(
                loops, self.uv_layer, src_a, src_b, self.align_pivot)
            if self.align_flip:
                rotate_island_uv(loops, self.uv_layer, self.align_pivot,
                                 math.pi)
                rot += math.pi
        self.align_angle = rot or 0.0
        self._update_mesh_live(context)

    def _apply_grab(self, context, mx, my, event):
        idata = self.islands_data[self.active_island_idx]
        geo = idata.get('geo3d')
        if not geo:
            return
        pixel_delta = Vector((mx, my)) - self.drag_start

        u_dir, v_dir = self.uv_screen_u, self.uv_screen_v
        bmin, bmax = idata['bbox_min'], idata['bbox_max']
        uv_w = max(bmax.x - bmin.x, 1e-8)
        uv_h = max(bmax.y - bmin.y, 1e-8)

        if u_dir and v_dir and u_dir.length > 1 and v_dir.length > 1:
            comps = _decompose_screen(pixel_delta, u_dir, v_dir)
            if comps:
                uv_off = Vector((-comps[0] * uv_w, -comps[1] * uv_h))
            else:
                uv_off = Vector((0, 0))
        else:
            rv3d = context.region_data
            region = context.region
            view_dist = (geo['center_3d'] -
                         Vector(rv3d.view_matrix.inverted()
                                .translation)).length
            sf = view_dist / (region.height * 0.5)
            uv_off = Vector((-pixel_delta.x * sf, -pixel_delta.y * sf))

        uv_off *= self.grab_sensitivity

        if self.grab_axis == 'X':
            uv_off.y = 0
        elif self.grab_axis == 'Y':
            uv_off.x = 0
        elif event.shift:
            if abs(uv_off.x) > abs(uv_off.y):
                uv_off.y = 0
            else:
                uv_off.x = 0

        if event.ctrl:
            sn = 0.0625
            uv_off.x = round(uv_off.x / sn) * sn
            uv_off.y = round(uv_off.y / sn) * sn

        restore_uvs(self.pre_drag_cache, self.uv_layer)
        for si in self._transform_targets():
            if 0 <= si < len(self.islands_data):
                move_island_uv(self.islands_data[si]['loops'],
                               self.uv_layer, uv_off)
        self._update_mesh_live(context)

    def _apply_rotate(self, context, mx, my, event):
        cs = self.drag_center_screen
        if not cs:
            return
        cur = math.atan2(my - cs.y, mx - cs.x)
        delta = self.drag_start_angle - cur

        u_dir, v_dir = self.uv_screen_u, self.uv_screen_v
        if u_dir and v_dir:
            cross_z = u_dir.x * v_dir.y - u_dir.y * v_dir.x
            if cross_z < 0:
                delta = -delta

        if event.ctrl:
            step = math.radians(ROTATION_STEPS[self.rotation_step_idx])
            delta = round(delta / step) * step

        self.current_angle_delta = delta
        idata = self.islands_data[self.active_island_idx]
        pivot = (self.transform_pivot_uv if self.transform_pivot_uv
                 is not None else _get_pivot_uv(self, idata))
        restore_uvs(self.pre_drag_cache, self.uv_layer)
        for si in self._transform_targets():
            if 0 <= si < len(self.islands_data):
                rotate_island_uv(self.islands_data[si]['loops'],
                                 self.uv_layer, pivot, delta)
        self._update_mesh_live(context)

    def _apply_scale(self, context, mx, my, event):
        cs = self.drag_center_screen
        if not cs:
            return

        u_dir, v_dir = self.uv_screen_u, self.uv_screen_v
        have_axes = (u_dir and v_dir
                     and u_dir.length > 1 and v_dir.length > 1)

        hn = self.scale_handle_name
        hs = self.drag_handle_screen

        if hs and hn:
            sx, sy = self._scale_from_handle(
                mx, my, cs, hn, hs, u_dir, v_dir, have_axes, event)
        else:
            sx, sy = self._scale_from_mouse(
                mx, my, cs, u_dir, v_dir, have_axes, event)

        self.current_scale_x, self.current_scale_y = sx, sy
        idata = self.islands_data[self.active_island_idx]
        pivot = (self.transform_pivot_uv if self.transform_pivot_uv
                 is not None else _get_pivot_uv(self, idata))
        restore_uvs(self.pre_drag_cache, self.uv_layer)
        isx = 1.0 / sx if abs(sx) > 1e-6 else 1.0
        isy = 1.0 / sy if abs(sy) > 1e-6 else 1.0
        for si in self._transform_targets():
            if 0 <= si < len(self.islands_data):
                scale_island_uv(self.islands_data[si]['loops'],
                                self.uv_layer, pivot, isx, isy)
        self._update_mesh_live(context)

    def _scale_from_handle(self, mx, my, cs, hn, hs,
                           u_dir, v_dir, have_axes, event):
        handle_delta = hs - cs
        mouse_delta = Vector((mx, my)) - cs

        if have_axes:
            hc = _decompose_screen(handle_delta, u_dir, v_dir)
            mc = _decompose_screen(mouse_delta, u_dir, v_dir)
            if hc and mc:
                u0, v0, u1, v1 = hc[0], hc[1], mc[0], mc[1]
            else:
                u0, v0 = handle_delta.x, handle_delta.y
                u1, v1 = mouse_delta.x, mouse_delta.y
        else:
            u0, v0 = handle_delta.x, handle_delta.y
            u1, v1 = mouse_delta.x, mouse_delta.y

        if hn in HANDLE_CORNERS:
            sx = u1 / u0 if abs(u0) > 0.001 else 1.0
            sy = v1 / v0 if abs(v0) > 0.001 else 1.0
            if event.shift:
                avg = (abs(sx) + abs(sy)) * 0.5
                sx, sy = math.copysign(avg, sx), math.copysign(avg, sy)
        elif hn in ('L', 'R'):
            sx = u1 / u0 if abs(u0) > 0.001 else 1.0
            sy = 1.0
        elif hn in ('T', 'B'):
            sx = 1.0
            sy = v1 / v0 if abs(v0) > 0.001 else 1.0
        else:
            sx = sy = 1.0

        if self.grab_axis == 'X':
            sy = 1.0
        elif self.grab_axis == 'Y':
            sx = 1.0

        if event.ctrl:
            sx = round(sx / 0.05) * 0.05 or 0.05
            sy = round(sy / 0.05) * 0.05 or 0.05

        return sx, sy

    def _scale_from_mouse(self, mx, my, cs, u_dir, v_dir,
                          have_axes, event):
        cur_dist = max((Vector((mx, my)) - cs).length, 1.0)
        start_dist = max((self.drag_start - cs).length, 1.0)
        factor = cur_dist / start_dist
        if event.ctrl:
            factor = round(factor / 0.05) * 0.05
        factor = max(factor, 0.01)
        sx = sy = factor

        if self.grab_axis == 'X':
            if have_axes:
                sc = _decompose_screen(self.drag_start - cs, u_dir, v_dir)
                mc = _decompose_screen(
                    Vector((mx, my)) - cs, u_dir, v_dir)
                if sc and mc:
                    sx = abs(mc[0]) / max(abs(sc[0]), 0.001)
            sy = 1.0
        elif self.grab_axis == 'Y':
            sx = 1.0
            if have_axes:
                sc = _decompose_screen(self.drag_start - cs, u_dir, v_dir)
                mc = _decompose_screen(
                    Vector((mx, my)) - cs, u_dir, v_dir)
                if sc and mc:
                    sy = abs(mc[1]) / max(abs(sc[1]), 0.001)
        elif event.shift:
            if have_axes:
                mc = _decompose_screen(
                    Vector((mx, my)) - cs, u_dir, v_dir)
                if mc:
                    uc, vc = abs(mc[0]), abs(mc[1])
                else:
                    uc, vc = abs(mx - cs.x), abs(my - cs.y)
            else:
                uc, vc = abs(mx - cs.x), abs(my - cs.y)
            if uc > vc * 2:
                sy = 1.0
            elif vc > uc * 2:
                sx = 1.0

        return sx, sy

    # ------------------------------------------------------------------
    # LMB click
    # ------------------------------------------------------------------

    def _on_lmb(self, context, event):
        if self.state == STATE_PICK_ALIGN_EDGE:
            src = self._hover_edge_src()
            if src is not None:
                # Targets may be empty (single island): the drag then
                # only offers the axis snap.
                self._start_align_drag(context, src)
            return {'RUNNING_MODAL'}

        if self.state == STATE_PICK_PIN:
            if self.hover_edge_uv is not None and self.hover_island_idx >= 0:
                idata = self.islands_data[self.hover_island_idx]
                keys = [uv_point_key(self.hover_edge_uv[0]),
                        uv_point_key(self.hover_edge_uv[1])]
                pinned, _ = self._toggle_pins(context, idata, keys)
                self.active_island_idx = self.hover_island_idx
                self._update_mesh(context)
                self.report({'INFO'},
                            "Pinned edge" if pinned else "Unpinned edge")
            return {'RUNNING_MODAL'}

        if self.state == STATE_PICK_STITCH_SRC:
            src = self._hover_edge_src()
            if src is not None:
                self._start_stitch_drag(context, src)
            return {'RUNNING_MODAL'}

        if self.state == STATE_PICK_DENSITY_REF:
            if self.hover_island_idx >= 0:
                self.density_ref_island = self.hover_island_idx
                self.state = STATE_PICK_DENSITY_TGT
                self.report({'INFO'}, "Click target island")
            return {'RUNNING_MODAL'}

        if self.state == STATE_PICK_DENSITY_TGT:
            if (self.hover_island_idx >= 0
                    and self.hover_island_idx != self.density_ref_island):
                self._push_undo()
                ref = self.islands_data[self.density_ref_island]
                tgt = self.islands_data[self.hover_island_idx]
                match_texel_density(
                    self.bm, ref['face_indices'],
                    tgt['face_indices'], self.uv_layer)
                self._update_mesh(context)
            self.state = STATE_IDLE
            return {'RUNNING_MODAL'}

        # Center handle drag -- move (it has no opposite handle to
        # pivot a scale on, so treat it as grab)
        if self.hover_handle == 'CENTER':
            self.scale_handle_name = None
            self.grab_axis = None
            if self._begin_transform(context, STATE_GRAB):
                return {'RUNNING_MODAL'}

        # Handle drag -- scale with opposite handle as pivot
        if self.hover_handle in HANDLE_OPPOSITE:
            self.scale_handle_name = self.hover_handle
            piv_uv, piv_scr, h_scr = self._handle_pivot_data(
                context, self.hover_handle)
            if self._begin_transform(context, STATE_HANDLE_SCALE,
                                     pivot_uv=piv_uv, pivot_screen=piv_scr,
                                     handle_screen=h_scr):
                return {'RUNNING_MODAL'}

        # Rotation handle drag
        if self.hover_rotate_handle:
            self.scale_handle_name = None
            if self._begin_transform(context, STATE_HANDLE_ROTATE):
                return {'RUNNING_MODAL'}

        # Click an edge: select it (Shift extends / toggles); the
        # island becomes active as well.
        if self.hover_edge_id is not None and self.hover_island_idx >= 0:
            self._select_hover_edge(extend=event.shift)
            self.active_island_idx = self.hover_island_idx
            self._sync_uv_editor(context)
            return {'RUNNING_MODAL'}

        # Click island to set active (plain click drops the edge
        # selection, Shift keeps it)
        if self.hover_island_idx >= 0:
            if not event.shift:
                self.sel_edges = []
            self.active_island_idx = self.hover_island_idx
            self._sync_uv_editor(context)
            return {'RUNNING_MODAL'}

        return {'PASS_THROUGH'}

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------

    def _on_key(self, context, event):
        if event.type == 'G' and not event.ctrl and not event.alt:
            self.scale_handle_name = None
            self.grab_axis = None
            if self._begin_transform(context, STATE_GRAB):
                self.report({'INFO'},
                            "G: Move -- X/Y axis, Shift constrain, "
                            "Ctrl snap, Alt+Scroll sens")
            return {'RUNNING_MODAL'}

        if event.type == 'R' and not event.ctrl and not event.alt:
            self.scale_handle_name = None
            self.grab_axis = None
            piv_uv, piv_scr = None, None
            if (self.hover_handle
                    and 0 <= self.active_island_idx
                    < len(self.islands_data)):
                idata = self.islands_data[self.active_island_idx]
                piv_uv = _handle_uv_pos(idata, self.hover_handle)
                handles = _compute_screen_handles(self, context)
                piv_scr = (handles.get(self.hover_handle)
                           if handles else None)
            if self._begin_transform(context, STATE_ROTATE,
                                     pivot_uv=piv_uv,
                                     pivot_screen=piv_scr):
                where = self.hover_handle or self.pivot_mode
                self.report({'INFO'},
                            f"R: Rotate around {where} -- Ctrl snap 5\u00b0")
            return {'RUNNING_MODAL'}

        if event.type == 'S' and not event.ctrl and not event.alt:
            self.grab_axis = None
            piv_uv, piv_scr, h_scr = None, None, None
            if (self.hover_handle in HANDLE_OPPOSITE
                    and 0 <= self.active_island_idx
                    < len(self.islands_data)):
                self.scale_handle_name = self.hover_handle
                piv_uv, piv_scr, h_scr = self._handle_pivot_data(
                    context, self.hover_handle)
            else:
                self.scale_handle_name = None
            if self._begin_transform(context, STATE_SCALE,
                                     pivot_uv=piv_uv, pivot_screen=piv_scr,
                                     handle_screen=h_scr):
                self.report({'INFO'},
                            "S: Scale -- X/Y axis, Shift uniform, Ctrl snap")
            return {'RUNNING_MODAL'}

        if event.type == 'C' and not event.ctrl:
            uv_pos = self._screen_to_uv(context,
                                         self.mouse_x, self.mouse_y)
            if uv_pos is not None:
                self.uv_cursor = uv_pos
                self._update_cursor_3d()
                self.pivot_mode = PIVOT_CURSOR
                self.report({'INFO'},
                            f"Cursor: ({uv_pos.x:.3f}, {uv_pos.y:.3f})")
            else:
                self.report({'INFO'}, "No face under cursor")
            return {'RUNNING_MODAL'}

        if event.type == 'A':
            ai = self.active_island_idx
            targets = self.selected_islands - {ai}
            hn = self.hover_handle
            if hn is None and self.hover_rotate_handle:
                hn = 'CENTER'
            sel_src = self._selection_src()
            if sel_src is not None and self.state != STATE_PICK_ALIGN_EDGE:
                # A selected edge means edge align, whatever the mouse
                # happens to hover (small islands sit under their own
                # centre handle).
                self._start_align_drag(context, sel_src,
                                       from_selection=True)
                return {'RUNNING_MODAL'}
            if hn is not None and (0 <= ai < len(self.islands_data)) and targets:
                self._push_undo()
                ref = self.islands_data[ai]
                ref_pt = _handle_uv_pos(ref, hn)
                for si in targets:
                    if not (0 <= si < len(self.islands_data)):
                        continue
                    tgt = self.islands_data[si]
                    tgt_pt = _handle_uv_pos(tgt, hn)
                    off = ref_pt - tgt_pt
                    if hn in ('B', 'T'):
                        off.x = 0.0
                    elif hn in ('L', 'R'):
                        off.y = 0.0
                    move_island_uv(tgt['loops'], self.uv_layer, off)
                self._update_mesh(context)
                self.report({'INFO'}, f"Aligned {len(targets)} to {hn}")
            elif hn is None:
                if self.state == STATE_PICK_ALIGN_EDGE:
                    self._end_pick()
                else:
                    self._enter_pick(context, STATE_PICK_ALIGN_EDGE,
                                     "Align: click the edge to align")
            return {'RUNNING_MODAL'}

        if event.type == 'F':
            if self.selected_islands:
                self._push_undo()
                axis = 'V' if event.shift else 'H'
                active_idata = self.islands_data[self.active_island_idx]
                pivot = _get_pivot_uv(self, active_idata)
                for si in self._transform_targets():
                    if 0 <= si < len(self.islands_data):
                        flip_island_uv(self.islands_data[si]['loops'],
                                       self.uv_layer, pivot, axis)
                self._update_mesh(context)
            return {'RUNNING_MODAL'}

        if event.type == 'T':
            if (0 <= self.active_island_idx < len(self.islands_data)
                    and self.hover_edge_uv):
                chain = self._find_edge_chain(
                    self.islands_data[self.active_island_idx],
                    self.hover_edge_uv)
                if chain and len(chain) >= 3:
                    self._push_undo()
                    straighten_uv_edge_loop(chain, self.uv_layer)
                    self._update_mesh(context)
            return {'RUNNING_MODAL'}

        if event.type == 'I':
            self.transform_scope = (SCOPE_ACTIVE
                                    if self.transform_scope == SCOPE_ALL
                                    else SCOPE_ALL)
            self.report({'INFO'},
                        f"Transform scope: {self.transform_scope.title()}")
            return {'RUNNING_MODAL'}

        if event.type == 'E':
            if self.state in STITCH_STATES:
                self._end_pick()
                return {'RUNNING_MODAL'}
            src = self._selection_src()
            if src is not None:
                self._start_stitch_drag(context, src, from_selection=True)
            else:
                self._enter_pick(context, STATE_PICK_STITCH_SRC,
                                 "Stitch: click the edge of the island "
                                 "to move")
            return {'RUNNING_MODAL'}

        if event.type == 'N':
            if self.selected_islands:
                self._push_undo()
                if event.ctrl:
                    mode = 'V'
                elif event.shift:
                    mode = 'U'
                else:
                    mode = 'UV'
                for si in self._transform_targets():
                    if 0 <= si < len(self.islands_data):
                        sid = self.islands_data[si]
                        randomize_island_uv(
                            sid['loops'], self.uv_layer,
                            sid['bbox_min'], sid['bbox_max'], mode)
                self._update_mesh(context)
                self.report({'INFO'}, f"Randomize {mode}")
            return {'RUNNING_MODAL'}

        if event.type == 'U' and event.alt:
            self._flip_across_pins(context)
            return {'RUNNING_MODAL'}

        if event.type == 'U':
            if event.shift:
                keys = [k for k, _, _ in UNWRAP_METHODS]
                i = keys.index(self.unwrap_method) if self.unwrap_method in keys else 0
                self.unwrap_method = keys[(i + 1) % len(keys)]
                self.report({'INFO'}, "Unwrap method: "
                            f"{UNWRAP_METHOD_NAMES[self.unwrap_method]}")
                return {'RUNNING_MODAL'}
            if event.ctrl:
                targets = sorted(self.selected_islands)
            elif 0 <= self.active_island_idx < len(self.islands_data):
                targets = [self.active_island_idx]
            else:
                targets = []
            if not targets:
                self.report({'INFO'}, "No island to unwrap")
                return {'RUNNING_MODAL'}
            self._push_undo()
            signs_before = {i: island_signed_area_uv(
                self.bm, self.islands[i], self.uv_layer) for i in targets}
            self._unwrap_islands(context, targets)
            self._update_mesh(context)
            flipped = 0
            if self.unwrap_keep_flip:
                for i in targets:
                    before = signs_before.get(i, 0.0)
                    after = island_signed_area_uv(
                        self.bm, self.islands[i], self.uv_layer)
                    if before * after < 0:
                        self._flip_island(i)
                        flipped += 1
                if flipped:
                    self._update_mesh(context)
            self.report({'INFO'},
                        f"Unwrap {UNWRAP_METHOD_NAMES[self.unwrap_method]}"
                        f" ({len(targets)} island"
                        f"{'s' if len(targets) != 1 else ''}"
                        + (f", {flipped} kept mirrored" if flipped else "")
                        + ")")
            return {'RUNNING_MODAL'}

        if event.type == 'M' and event.shift:
            self.unwrap_keep_flip = not self.unwrap_keep_flip
            state = "ON" if self.unwrap_keep_flip else "OFF"
            self.report({'INFO'}, f"Unwrap keeps mirroring: {state}")
            return {'RUNNING_MODAL'}

        if event.type == 'M':
            if event.alt:
                if 0 <= self.active_island_idx < len(self.islands_data):
                    idata = self.islands_data[self.active_island_idx]
                    n = clear_pins_uv(idata['loops'], self.uv_layer)
                    self._update_mesh(context)
                    self.report({'INFO'}, f"Cleared {n} pins")
                return {'RUNNING_MODAL'}
            if self.state == STATE_PICK_PIN:
                self._end_pick()
                return {'RUNNING_MODAL'}
            sel = self._resolved_sel_edges()
            if sel:
                # Pin / unpin the selected edges as one group.
                by_island = {}
                for e in sel:
                    by_island.setdefault(e['island'], []).extend(
                        (uv_point_key(e['edge_uv'][0]),
                         uv_point_key(e['edge_uv'][1])))
                pinned = False
                for island, keys in by_island.items():
                    pinned, _ = self._toggle_pins(
                        context, self.islands_data[island], keys)
                self._update_mesh(context)
                self.report({'INFO'},
                            f"{'Pinned' if pinned else 'Unpinned'} "
                            f"{len(sel)} edge{'s' if len(sel) != 1 else ''}")
            else:
                self._enter_pick(context, STATE_PICK_PIN,
                                 "Pins: click edges to pin, U to unwrap")
            return {'RUNNING_MODAL'}

        if event.type == 'D':
            ai = self.active_island_idx
            targets = self.selected_islands - {ai}
            if not ((0 <= ai < len(self.islands_data)) and targets):
                return {'RUNNING_MODAL'}
            self._push_undo()
            mode = ('WIDTH' if event.shift
                    else 'HEIGHT' if event.ctrl else 'BOTH')
            ref = self.islands_data[ai]
            for si in targets:
                if 0 <= si < len(self.islands_data):
                    tgt = self.islands_data[si]
                    match_island_dimensions(
                        tgt['loops'], self.uv_layer,
                        tgt['bbox_min'], tgt['bbox_max'],
                        ref['bbox_min'], ref['bbox_max'], mode)
            self._update_mesh(context)
            self.report({'INFO'},
                        f"Matched {mode.lower()} of {len(targets)} to active")
            return {'RUNNING_MODAL'}

        if event.type == 'Q' and event.shift:
            self._set_modifiers_paused(context, not self._suspended_mods)
            state = "PAUSED" if self._suspended_mods else "LIVE"
            self.report({'INFO'}, f"Modifiers: {state}")
            return {'RUNNING_MODAL'}

        if event.type == 'Q':
            self._clean_view = not self._clean_view
            context.space_data.overlay.show_overlays = not self._clean_view
            state = "ON" if self._clean_view else "OFF"
            self.report({'INFO'}, f"Clean view {state}")
            return {'RUNNING_MODAL'}

        if event.type == 'V':
            if self._align_view_to_island(context):
                self.report({'INFO'}, "View aligned to island")
            return {'RUNNING_MODAL'}

        if event.type == 'P':
            modes = [PIVOT_CENTER, PIVOT_CURSOR]
            ci = (modes.index(self.pivot_mode)
                  if self.pivot_mode in modes else 0)
            self.pivot_mode = modes[(ci + 1) % len(modes)]
            self.report({'INFO'}, f"Pivot: {self.pivot_mode}")
            return {'RUNNING_MODAL'}

        if event.type == 'TAB':
            if self.islands_data:
                self.active_island_idx = (
                    (self.active_island_idx + 1) % len(self.islands_data))
                self._sync_uv_editor(context)
            return {'RUNNING_MODAL'}

        return {'RUNNING_MODAL'}

    # ------------------------------------------------------------------
    # Edge chain
    # ------------------------------------------------------------------

    def _find_edge_chain(self, idata, start_edge_uv):
        uv = self.uv_layer
        edge_map = {}
        for loop in idata['loops']:
            for fl in loop.face.loops:
                ka = (round(fl[uv].uv.x, 5), round(fl[uv].uv.y, 5))
                nl = fl.link_loop_next
                kb = (round(nl[uv].uv.x, 5), round(nl[uv].uv.y, 5))
                ek = (ka, kb) if ka < kb else (kb, ka)
                edge_map.setdefault(ek, []).append(fl)

        sa = (round(start_edge_uv[0].x, 5), round(start_edge_uv[0].y, 5))
        sb = (round(start_edge_uv[1].x, 5), round(start_edge_uv[1].y, 5))
        p2e = {}
        for ek in edge_map:
            for pt in ek:
                p2e.setdefault(pt, []).append(ek)

        chain = [sa, sb]
        vis = {(sa, sb) if sa < sb else (sb, sa)}
        for d in (0, 1):
            tip = chain[-1] if d == 1 else chain[0]
            while True:
                found = False
                for ek in p2e.get(tip, []):
                    if ek in vis:
                        continue
                    vis.add(ek)
                    other = ek[1] if ek[0] == tip else ek[0]
                    if d == 1:
                        chain.append(other)
                    else:
                        chain.insert(0, other)
                    tip = other
                    found = True
                    break
                if not found:
                    break

        result = []
        for key in chain:
            for loop in idata['loops']:
                lk = (round(loop[uv].uv.x, 5), round(loop[uv].uv.y, 5))
                if lk == key:
                    result.append(loop)
                    break
        return result
