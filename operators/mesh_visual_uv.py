import bpy
import blf
import gpu
import bmesh
import math
from mathutils import Vector
from bpy_extras.view3d_utils import location_3d_to_region_2d
from gpu_extras.batch import batch_for_shader

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
    compute_texel_density,
    match_texel_density,
    match_island_dimensions,
    randomize_island_uv,
    straighten_uv_edge_loop,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HIT_RADIUS = 14
NORMAL_OFFSET = 0.002
CORNER_SIZE = 8
MID_SIZE = 7
ROTATION_HANDLE_DISTANCE = 0.15

GRAB_SENS_DEFAULT = 1.0
GRAB_SENS_MIN = 0.05
GRAB_SENS_MAX = 3.0
GRAB_SENS_STEP = 1.25

TILE_LIMIT_DEFAULT = 2

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

PIVOT_CENTER = 'CENTER'
PIVOT_CURSOR = 'CURSOR'

HANDLE_CORNERS = ('BL', 'BR', 'TL', 'TR')
HANDLE_MIDS = ('B', 'T', 'L', 'R')

HANDLE_OPPOSITE = {
    'BL': 'TR', 'BR': 'TL', 'TL': 'BR', 'TR': 'BL',
    'B': 'T', 'T': 'B', 'L': 'R', 'R': 'L',
}

# Colors -- clean, UV-editor style palette
ISLAND_COLORS = [
    (0.40, 0.65, 1.00, 0.50),
    (1.00, 0.50, 0.30, 0.50),
    (0.35, 0.85, 0.45, 0.50),
    (0.95, 0.80, 0.25, 0.50),
    (0.70, 0.40, 0.90, 0.50),
    (0.20, 0.80, 0.75, 0.50),
    (0.90, 0.35, 0.60, 0.50),
    (0.60, 0.80, 0.20, 0.50),
]

COL_EDGE = (0.85, 0.85, 0.85, 0.45)
COL_EDGE_SELECTED = (0.95, 0.85, 0.55, 0.55)
COL_EDGE_ACTIVE = (0.95, 0.95, 0.95, 0.65)
COL_EDGE_HOVER = (1.0, 1.0, 0.4, 1.0)
COL_EDGE_ALIGN = (0.0, 1.0, 0.5, 1.0)
COL_CENTER = (1.0, 1.0, 1.0, 0.8)
COL_ROT_HANDLE = (0.3, 0.9, 0.3, 0.9)
COL_ROT_LINE = (0.3, 0.9, 0.3, 0.35)
COL_HANDLE = (1.0, 1.0, 1.0, 0.85)
COL_HANDLE_HOVER = (1.0, 0.85, 0.0, 1.0)
COL_BBOX = (0.65, 0.65, 0.65, 0.30)
COL_CURSOR = (1.0, 0.2, 0.6, 1.0)
COL_FEEDBACK = (1.0, 0.95, 0.8, 0.9)
COL_AXIS_X = (0.9, 0.25, 0.25, 0.9)
COL_AXIS_Y = (0.25, 0.75, 0.25, 0.9)


# ---------------------------------------------------------------------------
# 2D drawing helpers
# ---------------------------------------------------------------------------

def _draw_circle(cx, cy, radius, color, segs=16):
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    verts = [(cx, cy)]
    for i in range(segs + 1):
        a = 2 * math.pi * i / segs
        verts.append((cx + math.cos(a) * radius, cy + math.sin(a) * radius))
    idx = [(0, i, i + 1 if i + 1 <= segs else 1) for i in range(1, segs + 1)]
    b = batch_for_shader(shader, 'TRIS', {"pos": verts}, indices=idx)
    shader.bind()
    shader.uniform_float("color", color)
    b.draw(shader)


def _draw_ring(cx, cy, radius, color, width=2.0, segs=32):
    pts = [(cx + math.cos(2 * math.pi * i / segs) * radius,
            cy + math.sin(2 * math.pi * i / segs) * radius)
           for i in range(segs + 1)]
    _draw_polyline(pts, color, width)


def _draw_polyline(pts, color, width=1.0, mode='LINE_STRIP'):
    if len(pts) < 2:
        return
    shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    b = batch_for_shader(shader, mode, {"pos": pts})
    shader.bind()
    region = bpy.context.region
    shader.uniform_float("viewportSize", (region.width, region.height))
    shader.uniform_float("lineWidth", width)
    shader.uniform_float("color", color)
    b.draw(shader)


def _draw_diamond(cx, cy, half, color):
    """Filled diamond handle."""
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    verts = [(cx, cy - half), (cx + half, cy),
             (cx, cy + half), (cx - half, cy)]
    b = batch_for_shader(shader, 'TRIS', {"pos": verts},
                         indices=[(0, 1, 2), (0, 2, 3)])
    shader.bind()
    shader.uniform_float("color", color)
    b.draw(shader)


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


def _compute_screen_handles(op, context):
    """Project UV bbox corners through the mesh surface to screen space
    so handles always correspond to the UV editor layout."""
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

    bmin, bmax = idata['bbox_min'], idata['bbox_max']
    cu = (bmin.x + bmax.x) * 0.5
    cv = (bmin.y + bmax.y) * 0.5

    uv_pts = {
        'BL': (bmin.x, bmin.y), 'BR': (bmax.x, bmin.y),
        'TL': (bmin.x, bmax.y), 'TR': (bmax.x, bmax.y),
        'B': (cu, bmin.y), 'T': (cu, bmax.y),
        'L': (bmin.x, cv), 'R': (bmax.x, cv),
        '_C': (cu, cv),
    }

    result = {}
    for name, (hu, hv) in uv_pts.items():
        pos3d = _nearest_3d_for_uv(geo, hu, hv)
        if pos3d is None:
            continue
        sp = location_3d_to_region_2d(region, rv3d,
                                      pos3d + nrm * nrm_off)
        if sp is None:
            continue
        result[name] = sp

    if not all(n in result for n in HANDLE_CORNERS):
        return {}

    if 'L' in result and 'R' in result:
        result['_u_dir'] = result['R'] - result['L']
    if 'B' in result and 'T' in result:
        result['_v_dir'] = result['T'] - result['B']

    # Push handles outward along the UV axes so the gap is equal on all sides
    u_dir = result.get('_u_dir')
    v_dir = result.get('_v_dir')
    pad = 14
    if u_dir and v_dir and u_dir.length > 1 and v_dir.length > 1:
        u_hat = u_dir.normalized()
        v_hat = v_dir.normalized()
        for name in list(HANDLE_CORNERS) + list(HANDLE_MIDS):
            if name not in result:
                continue
            off = Vector((0.0, 0.0))
            if name in ('BL', 'TL', 'L'):
                off -= u_hat * pad
            elif name in ('BR', 'TR', 'R'):
                off += u_hat * pad
            if name in ('BL', 'BR', 'B'):
                off -= v_hat * pad
            elif name in ('TL', 'TR', 'T'):
                off += v_hat * pad
            result[name] = result[name] + off
    else:
        csp = result.get('_C')
        if csp:
            for name in list(HANDLE_CORNERS) + list(HANDLE_MIDS):
                if name not in result:
                    continue
                d = result[name] - csp
                if d.length > 1.0:
                    result[name] = result[name] + d.normalized() * pad

    return result


# ---------------------------------------------------------------------------
# Draw callbacks
# ---------------------------------------------------------------------------

def draw_3d_callback(op, context):
    if context.area != op._area:
        return
    if op._clean_view:
        return
    prefs = bpy.context.preferences.addons["InteractionOps"].preferences
    nrm_off = getattr(prefs, 'visual_uv_normal_offset', NORMAL_OFFSET)
    fill_base = getattr(prefs, 'visual_uv_fill_alpha', 0.10)
    edge_w = getattr(prefs, 'visual_uv_edge_width', 1.5)

    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.depth_mask_set(False)

    shader_flat = gpu.shader.from_builtin("UNIFORM_COLOR")
    shader_line = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    region = context.region

    for idx, idata in enumerate(op.islands_data):
        geo = idata.get('geo3d')
        if not geo:
            continue
        is_active = (idx == op.active_island_idx)
        is_selected = idx in op.selected_islands
        island_col = ISLAND_COLORS[idx % len(ISLAND_COLORS)]
        nrm = geo['normal_avg']

        fa = fill_base * (1.8 if is_active else 1.4 if is_selected else 1.0)
        tv, ti = [], []
        for v0, v1, v2 in geo['face_tris']:
            base = len(tv)
            tv.extend([_off(v0, nrm, nrm_off), _off(v1, nrm, nrm_off),
                        _off(v2, nrm, nrm_off)])
            ti.append((base, base + 1, base + 2))
        if tv:
            batch = batch_for_shader(shader_flat, 'TRIS',
                                     {"pos": tv}, indices=ti)
            shader_flat.bind()
            shader_flat.uniform_float("color", (*island_col[:3], fa))
            batch.draw(shader_flat)

        ecol = (COL_EDGE_ACTIVE if is_active
                else COL_EDGE_SELECTED if is_selected else COL_EDGE)
        ep = []
        for pa, pb in geo['edges_3d']:
            ep.extend([_off(pa, nrm, nrm_off * 1.5),
                        _off(pb, nrm, nrm_off * 1.5)])
        if ep:
            batch = batch_for_shader(shader_line, 'LINES', {"pos": ep})
            shader_line.bind()
            shader_line.uniform_float("viewportSize",
                                      (region.width, region.height))
            shader_line.uniform_float("lineWidth", edge_w)
            shader_line.uniform_float("color", ecol)
            batch.draw(shader_line)

    if op.hover_edge_3d is not None:
        col = (COL_EDGE_ALIGN if op.state == STATE_PICK_ALIGN_EDGE
               else COL_EDGE_HOVER)
        batch = batch_for_shader(shader_line, 'LINES',
                                 {"pos": list(op.hover_edge_3d)})
        shader_line.bind()
        shader_line.uniform_float("viewportSize",
                                  (region.width, region.height))
        shader_line.uniform_float("lineWidth", 3.0)
        shader_line.uniform_float("color", col)
        batch.draw(shader_line)

    gpu.state.depth_test_set('NONE')
    gpu.state.depth_mask_set(True)
    gpu.state.blend_set('NONE')


def draw_pixel_callback(op, context):
    if context.area != op._area:
        return
    region = context.region
    rv3d = context.region_data
    prefs = bpy.context.preferences.addons["InteractionOps"].preferences
    nrm_off = getattr(prefs, 'visual_uv_normal_offset', NORMAL_OFFSET)
    gpu.state.blend_set('ALPHA')

    for idx, idata in enumerate(op.islands_data):
        geo = idata.get('geo3d')
        if not geo:
            continue
        is_active = (idx == op.active_island_idx)
        island_col = ISLAND_COLORS[idx % len(ISLAND_COLORS)]
        nrm = geo['normal_avg']
        center_off = geo['center_3d'] + nrm * nrm_off

        csp = location_3d_to_region_2d(region, rv3d, center_off)
        if csp and is_active:
            _draw_ring(csp.x, csp.y, 8, COL_CENTER, 2.0)
            _draw_circle(csp.x, csp.y, 3, COL_CENTER)

            rot_pos = center_off + nrm * ROTATION_HANDLE_DISTANCE
            rsp = location_3d_to_region_2d(region, rv3d, rot_pos)
            if rsp:
                _draw_polyline([csp, rsp], COL_ROT_LINE, 1.5)
                rc = (COL_HANDLE_HOVER if op.hover_rotate_handle
                      else COL_ROT_HANDLE)
                _draw_circle(rsp.x, rsp.y, 6, rc)

        if not op._clean_view:
            td = idata.get('texel_density')
            if td is not None and csp:
                blf.size(0, 12)
                blf.color(0, *island_col)
                blf.position(0, csp.x + 14, csp.y - 6, 0)
                blf.draw(0, f"TD:{td:.3f}")

    # Bounding box + handles (active island)
    handles = _compute_screen_handles(op, context)
    if handles and op.state in (STATE_IDLE, STATE_HANDLE_SCALE,
                                 STATE_PICK_ALIGN_EDGE):
        if all(n in handles for n in HANDLE_CORNERS):
            box = [(handles[n].x, handles[n].y)
                   for n in ('BL', 'BR', 'TR', 'TL', 'BL')]
            _draw_polyline(box, COL_BBOX, 1.0)

        for name in HANDLE_CORNERS:
            if name not in handles:
                continue
            h = handles[name]
            hc = COL_HANDLE_HOVER if op.hover_handle == name else COL_HANDLE
            _draw_circle(h.x, h.y, CORNER_SIZE, hc)

        for name in HANDLE_MIDS:
            if name not in handles:
                continue
            h = handles[name]
            hc = COL_HANDLE_HOVER if op.hover_handle == name else COL_HANDLE
            _draw_diamond(h.x, h.y, MID_SIZE, hc)

    # UV Cursor
    if op.cursor_3d is not None:
        csp = location_3d_to_region_2d(region, rv3d, op.cursor_3d)
        if csp:
            arm = 14
            _draw_polyline(
                [(csp.x - arm, csp.y), (csp.x + arm, csp.y),
                 (csp.x, csp.y - arm), (csp.x, csp.y + arm)],
                COL_CURSOR, 2.0, mode='LINES')
            _draw_circle(csp.x, csp.y, 3, COL_CURSOR)

    _draw_transform_feedback(op)
    gpu.state.blend_set('NONE')


def _draw_transform_feedback(op):
    mx, my = op.mouse_x, op.mouse_y

    if (op.state in (STATE_ROTATE, STATE_HANDLE_ROTATE)
            and op.drag_center_screen):
        deg = math.degrees(op.current_angle_delta)
        step_deg = ROTATION_STEPS[op.rotation_step_idx]
        blf.size(0, 14)
        blf.color(0, *COL_FEEDBACK)
        blf.position(0, mx + 18, my + 10, 0)
        blf.draw(0, f"R {deg:.1f}\u00b0  [Ctrl snap {step_deg}\u00b0]")

    elif (op.state in (STATE_SCALE, STATE_HANDLE_SCALE)
          and op.drag_center_screen):
        blf.size(0, 14)
        blf.position(0, mx + 18, my + 10, 0)
        sx, sy = op.current_scale_x, op.current_scale_y
        if op.grab_axis == 'X':
            blf.color(0, *COL_AXIS_X)
            blf.draw(0, f"S X {sx:.3f}")
        elif op.grab_axis == 'Y':
            blf.color(0, *COL_AXIS_Y)
            blf.draw(0, f"S Y {sy:.3f}")
        else:
            blf.color(0, *COL_FEEDBACK)
            blf.draw(0, f"S {sx:.3f} x {sy:.3f}")

    elif op.state == STATE_GRAB:
        blf.size(0, 14)
        if op.grab_axis == 'X':
            blf.color(0, *COL_AXIS_X)
            label = "G along X"
        elif op.grab_axis == 'Y':
            blf.color(0, *COL_AXIS_Y)
            label = "G along Y"
        else:
            blf.color(0, *COL_FEEDBACK)
            label = "G Move"
        sens_pct = int(op.grab_sensitivity / GRAB_SENS_DEFAULT * 100)
        blf.position(0, mx + 18, my + 10, 0)
        blf.draw(0, f"{label}  [{sens_pct}%]")


def draw_shortcuts_callback(op, context):
    if context.area != op._area:
        return
    prefs = bpy.context.preferences.addons["InteractionOps"].preferences
    tColor, tKColor = prefs.text_color, prefs.text_color_key
    tCSize = prefs.text_size
    tCPosX, tCPosY = prefs.text_pos_x, prefs.text_pos_y
    tShadow, tSColor = prefs.text_shadow_toggle, prefs.text_shadow_color
    tSBlur = prefs.text_shadow_blur
    tSPosX, tSPosY = prefs.text_shadow_pos_x, prefs.text_shadow_pos_y

    uf = context.preferences.system.ui_scale
    blf.size(0, tCSize)
    if tShadow:
        blf.enable(0, blf.SHADOW)
        blf.shadow(0, int(tSBlur), *tSColor)
        blf.shadow_offset(0, tSPosX, tSPosY)
    else:
        blf.disable(0, blf.SHADOW)

    st = op.state.replace('_', ' ').title()
    pv = op.pivot_mode
    uc, rc = len(op.undo_stack), len(op.redo_stack)
    sens_pct = int(op.grab_sensitivity / GRAB_SENS_DEFAULT * 100)
    rot_step = ROTATION_STEPS[op.rotation_step_idx]
    lines = [
        (f"Visual UV  [{st}]  Pivot: {pv}  Sens: {sens_pct}%  "
         f"Islands: {len(op.islands_data)}", ""),
        ("Grab / Move", "G  (X / Y axis lock)"),
        ("Rotate", "R  (Ctrl snap, Ctrl+Scroll step)"),
        ("Rotation step", f"Ctrl+Scroll ({rot_step}\u00b0)"),
        ("Scale", "S  (X / Y axis lock)"),
        ("Handle drag scale", "LMB on corner / mid"),
        ("Sensitivity", f"Alt+Scroll ({sens_pct}%)"),
        ("Place UV cursor", "C (at mouse)"),
        ("Active island", "LMB on face / Tab"),
        ("Align (hover handle / edge)", "A"),
        ("Match dimensions", "D"),
        ("Flip H / V", "F / Shift+F"),
        ("Randomize UV / U / V", "N / Shift+N / Ctrl+N"),
        ("Unwrap (seams)", "U"),
        ("Straighten chain", "T"),
        ("Toggle overlays", "Q"),
        ("Pivot", "P"),
        ("Undo / Redo", f"Ctrl+Z ({uc}) / Ctrl+Shift+Z ({rc})"),
        ("Confirm / Cancel", "Enter / Space / Esc"),
    ]

    off = tCPosY
    coffs = (tCSize * 22) * uf
    for line in reversed(lines):
        blf.color(0, *tColor)
        blf.position(0, tCPosX * uf, off, 0)
        blf.draw(0, line[0])
        if line[1]:
            blf.color(0, *tKColor)
            td = blf.dimensions(0, line[1])
            blf.position(0, coffs - td[0] + tCPosX, off, 0)
            blf.draw(0, line[1])
        off += (tCSize + 5) * uf


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
    bl_label = "IOPS Visual UV"
    bl_options = {"REGISTER", "UNDO"}

    tile_limit_prop: bpy.props.IntProperty(
        name="Tile Limit",
        description="Max tiles away from 0-1 before snapping back",
        default=TILE_LIMIT_DEFAULT, min=1, max=10)
    rotation_step_prop: bpy.props.IntProperty(
        name="Rotation Step",
        description="Ctrl-snap step in degrees",
        default=ROTATION_STEPS[ROTATION_STEP_DEFAULT_IDX],
        min=1, max=90)
    grab_sensitivity_prop: bpy.props.FloatProperty(
        name="Grab Sensitivity",
        description="Movement speed multiplier",
        default=GRAB_SENS_DEFAULT, min=GRAB_SENS_MIN, max=GRAB_SENS_MAX)

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

    def _update_mesh(self, context):
        """Full mesh update + data rebuild after a discrete UV operation."""
        bmesh.update_edit_mesh(context.active_object.data)
        self.rebuild_data(context)

    def _update_mesh_live(self, context):
        """Lightweight update for continuous transforms (every mouse move)."""
        self._check_tile_bounds()
        bmesh.update_edit_mesh(context.active_object.data,
                               loop_triangles=False)
        self._refresh_active(context)

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
        self.hover_rotate_handle = False
        self.hover_handle = None

        handles = _compute_screen_handles(self, context)

        if handles:
            for name in list(HANDLE_CORNERS) + list(HANDLE_MIDS):
                if name in handles and (mouse - handles[name]).length <= HIT_RADIUS:
                    self.hover_handle = name
                    return

        if 0 <= self.active_island_idx < len(self.islands_data):
            geo = self.islands_data[self.active_island_idx].get('geo3d')
            if geo:
                prefs = bpy.context.preferences.addons[
                    "InteractionOps"].preferences
                noff = getattr(prefs, 'visual_uv_normal_offset',
                               NORMAL_OFFSET)
                center_off = geo['center_3d'] + geo['normal_avg'] * noff
                rp = center_off + geo['normal_avg'] * ROTATION_HANDLE_DISTANCE
                rsp = location_3d_to_region_2d(region, rv3d, rp)
                if rsp and (mouse - rsp).length <= HIT_RADIUS:
                    self.hover_rotate_handle = True
                    return
                csp = location_3d_to_region_2d(region, rv3d, center_off)
                if csp and (mouse - csp).length <= HIT_RADIUS:
                    self.hover_handle = 'CENTER'
                    return

        # Vertices
        bd, bi, bk = HIT_RADIUS + 1, -1, None
        for idx, idata in enumerate(self.islands_data):
            geo = idata.get('geo3d')
            if not geo:
                continue
            for uv_key, pos3d in geo['verts_3d'].items():
                sp = location_3d_to_region_2d(region, rv3d, pos3d)
                if sp is None:
                    continue
                d = (mouse - sp).length
                if d < bd:
                    bd, bi, bk = d, idx, uv_key
        if bi >= 0:
            self.hover_island_idx = bi
            self.hover_vert_key = bk
            return

        # Edges
        bd, bi = HIT_RADIUS + 1, -1
        be3d, beuv = None, None
        for idx, idata in enumerate(self.islands_data):
            geo = idata.get('geo3d')
            if not geo:
                continue
            for (uv_a, uv_b), (pa, pb) in geo['edge_uv_pairs']:
                spa = location_3d_to_region_2d(region, rv3d, pa)
                spb = location_3d_to_region_2d(region, rv3d, pb)
                if spa is None or spb is None:
                    continue
                d = _seg_dist_2d(mouse, spa, spb)
                if d < bd:
                    bd, bi, be3d, beuv = d, idx, (pa, pb), (uv_a, uv_b)
        if bi >= 0:
            self.hover_island_idx = bi
            self.hover_edge_3d = be3d
            self.hover_edge_uv = beuv
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
        self.hover_rotate_handle = False
        self.hover_handle = None
        self.grab_axis = None
        self.tile_limit = self.tile_limit_prop
        self.grab_sensitivity = self.grab_sensitivity_prop
        step_val = self.rotation_step_prop
        self.rotation_step_idx = (
            ROTATION_STEPS.index(step_val)
            if step_val in ROTATION_STEPS else ROTATION_STEP_DEFAULT_IDX)
        self.pivot_mode = PIVOT_CENTER
        self.uv_cursor = Vector((0.5, 0.5))
        self.cursor_3d = None
        self.mouse_x = self.mouse_y = 0
        self.drag_start = None
        self.drag_start_angle = 0.0
        self.drag_center_screen = None
        self.pre_drag_cache = None
        self.density_ref_island = -1
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

        self._overlay_was_on = context.space_data.overlay.show_overlays
        self._clean_view = False

        self._handle_3d = bpy.types.SpaceView3D.draw_handler_add(
            draw_3d_callback, (self, context), 'WINDOW', 'POST_VIEW')
        self._handle_pixel = bpy.types.SpaceView3D.draw_handler_add(
            draw_pixel_callback, (self, context), 'WINDOW', 'POST_PIXEL')
        self._handle_shortcuts = bpy.types.SpaceView3D.draw_handler_add(
            draw_shortcuts_callback, (self, context), 'WINDOW', 'POST_PIXEL')
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

        if self.state in (STATE_GRAB, STATE_ROTATE, STATE_SCALE,
                          STATE_HANDLE_SCALE, STATE_HANDLE_ROTATE):
            return self._modal_transform(context, event)

        if event.type == 'ESC' and event.value == 'PRESS':
            restore_uvs(self.uv_cache, self.uv_layer)
            bmesh.update_edit_mesh(context.active_object.data)
            self._cleanup(context)
            self.report({'INFO'}, "Visual UV cancelled")
            return {'CANCELLED'}

        if (event.type in {'RET', 'NUMPAD_ENTER', 'SPACE'}
                and event.value == 'PRESS'):
            bmesh.update_edit_mesh(context.active_object.data)
            self._cleanup(context)
            self.tile_limit_prop = self.tile_limit
            self.grab_sensitivity_prop = self.grab_sensitivity
            self.rotation_step_prop = ROTATION_STEPS[self.rotation_step_idx]
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

    def _modal_transform(self, context, event):
        mx, my = event.mouse_region_x, event.mouse_region_y

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
            if self.pre_drag_cache:
                self.undo_stack.append(self.pre_drag_cache)
                self.redo_stack.clear()
            self._update_mesh(context)
            self._end_transform()
            return {'RUNNING_MODAL'}

        # Cancel
        if event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            if self.pre_drag_cache:
                restore_uvs(self.pre_drag_cache, self.uv_layer)
            self._update_mesh(context)
            self._end_transform()
            return {'RUNNING_MODAL'}

        if (event.type in {'X', 'Y'} and event.value == 'PRESS'
                and self.state in (STATE_GRAB, STATE_SCALE,
                                   STATE_HANDLE_SCALE)):
            new_axis = event.type
            self.grab_axis = new_axis if self.grab_axis != new_axis else None
            return {'RUNNING_MODAL'}

        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            return {'PASS_THROUGH'}

        if event.type == 'MOUSEMOVE':
            if self.state == STATE_GRAB:
                self._apply_grab(context, mx, my, event)
            elif self.state in (STATE_ROTATE, STATE_HANDLE_ROTATE):
                self._apply_rotate(context, mx, my, event)
            elif self.state in (STATE_SCALE, STATE_HANDLE_SCALE):
                self._apply_scale(context, mx, my, event)

        return {'RUNNING_MODAL'}

    def _cleanup(self, context):
        if hasattr(self, '_overlay_was_on'):
            context.space_data.overlay.show_overlays = self._overlay_was_on
        for h in (self._handle_3d, self._handle_pixel,
                  self._handle_shortcuts):
            if h:
                try:
                    bpy.types.SpaceView3D.draw_handler_remove(h, 'WINDOW')
                except ValueError:
                    pass
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
        context.workspace.status_text_set(None)
        self._handle_3d = self._handle_pixel = None
        self._handle_shortcuts = self._timer = None

    def _end_transform(self):
        self.state = STATE_IDLE
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
        area, snap it back so its center sits at (0.5, 0.5)."""
        uv = self.uv_layer
        lim = self.tile_limit
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
        geo = self.islands_data[self.active_island_idx].get('geo3d')
        if not geo:
            return False
        region, rv3d = context.region, context.region_data
        if pivot_screen is not None:
            csp = pivot_screen
        else:
            prefs = bpy.context.preferences.addons[
                "InteractionOps"].preferences
            noff = getattr(prefs, 'visual_uv_normal_offset', NORMAL_OFFSET)
            center = geo['center_3d'] + geo['normal_avg'] * noff
            csp = location_3d_to_region_2d(region, rv3d, center)
        if not csp:
            return False

        self.pre_drag_cache = cache_all_uvs(self.bm, self.uv_layer)
        self.drag_start = Vector((self.mouse_x, self.mouse_y))
        self.drag_center_screen = csp
        self.transform_pivot_uv = pivot_uv
        self.drag_handle_screen = handle_screen
        ref = handle_screen if handle_screen else self.drag_start
        self.drag_start_angle = math.atan2(ref.y - csp.y, ref.x - csp.x)
        self.current_angle_delta = 0.0
        self.current_scale_x = 1.0
        self.current_scale_y = 1.0

        handles = _compute_screen_handles(self, context)
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
        for si in self.selected_islands:
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
        for si in self.selected_islands:
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
        for si in self.selected_islands:
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
            if self.hover_edge_uv is not None and self.hover_island_idx >= 0:
                self._push_undo()
                self.active_island_idx = self.hover_island_idx
                idata = self.islands_data[self.active_island_idx]
                align_island_to_edge_uv(
                    idata['loops'], self.uv_layer,
                    self.hover_edge_uv[0], self.hover_edge_uv[1],
                    _get_pivot_uv(self, idata))
                self._update_mesh(context)
            self.state = STATE_IDLE
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

        # Handle drag -- scale with opposite handle as pivot
        if self.hover_handle is not None:
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

        # Click island to set active
        if self.hover_island_idx >= 0:
            self.active_island_idx = self.hover_island_idx
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
            if (self.hover_handle
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
                self.state = (STATE_PICK_ALIGN_EDGE
                              if self.state != STATE_PICK_ALIGN_EDGE
                              else STATE_IDLE)
                if self.state == STATE_PICK_ALIGN_EDGE:
                    self.report({'INFO'}, "Click an edge to align island")
            return {'RUNNING_MODAL'}

        if event.type == 'F':
            if self.selected_islands:
                self._push_undo()
                axis = 'V' if event.shift else 'H'
                active_idata = self.islands_data[self.active_island_idx]
                pivot = _get_pivot_uv(self, active_idata)
                for si in self.selected_islands:
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

        if event.type == 'N':
            if self.selected_islands:
                self._push_undo()
                if event.ctrl:
                    mode = 'V'
                elif event.shift:
                    mode = 'U'
                else:
                    mode = 'UV'
                for si in self.selected_islands:
                    if 0 <= si < len(self.islands_data):
                        sid = self.islands_data[si]
                        randomize_island_uv(
                            sid['loops'], self.uv_layer,
                            sid['bbox_min'], sid['bbox_max'], mode)
                self._update_mesh(context)
                self.report({'INFO'}, f"Randomize {mode}")
            return {'RUNNING_MODAL'}

        if event.type == 'U':
            self._push_undo()
            bpy.ops.uv.unwrap(method='ANGLE_BASED', margin=0.001)
            self._update_mesh(context)
            self.report({'INFO'}, "Unwrap (seams)")
            return {'RUNNING_MODAL'}

        if event.type == 'D':
            ai = self.active_island_idx
            targets = self.selected_islands - {ai}
            if not ((0 <= ai < len(self.islands_data)) and targets):
                return {'RUNNING_MODAL'}
            self._push_undo()
            ref = self.islands_data[ai]
            for si in targets:
                if 0 <= si < len(self.islands_data):
                    tgt = self.islands_data[si]
                    match_island_dimensions(
                        tgt['loops'], self.uv_layer,
                        tgt['bbox_min'], tgt['bbox_max'],
                        ref['bbox_min'], ref['bbox_max'])
            self._update_mesh(context)
            self.report({'INFO'},
                        f"Matched dimensions of {len(targets)} to active")
            return {'RUNNING_MODAL'}

        if event.type == 'Q':
            self._clean_view = not self._clean_view
            context.space_data.overlay.show_overlays = not self._clean_view
            state = "ON" if self._clean_view else "OFF"
            self.report({'INFO'}, f"Clean view {state}")
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
