import bpy
import math
from itertools import combinations
from mathutils import Vector, Matrix

from ..ui.draw import safe_handler_add, safe_handler_remove
from ..ui.draw.theme import get_theme, axis_color, Role
from ..ui.hud import text as hud_text
from ..ui.hud import (
    HUDOverlay, HelpOverlay, HUDSection, HUDItem,
    HUDParam, ItemState,
    capture_event,
)


# --- HUD / Help builders ---------------------------------------------------

def _build_hud(context):
    hud = HUDOverlay("object_mirror_rotate")
    hud.title = "Mirror Rotate"
    hud.bind_region(context.region)
    return hud


def _build_help(context):
    helpo = HelpOverlay("object_mirror_rotate")
    helpo.add_section(HUDSection("Mirror Rotate", [
        HUDItem("Pivot (Cursor / Active / Pick object)", "Q", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Mirror axes: +axis / −axis / off (combos multiply)", "X / Y / Z", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Orientation (Global / Pivot frame)", "W", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Method (Mirror / Rotate / Reflect = mirror by rotation, positive scale)", "E", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Rotate angle (Rotate method)", "0–9 / Alt+Wheel", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Clone type (Duplicate / Instance / In place)", "D", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Apply transforms on confirm", "A", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Snap cursor to face (vert/edge-mid/center, Z=normal)", "C + LMB", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Reset to defaults", "B", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Apply", "Space / Enter", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Cancel", "Esc / RMB", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        HUDItem("Help / HUD", "H", ItemState.ON, default_state=ItemState.OFF, always_show=True),
    ]))
    helpo.bind_region(context.region)
    return helpo


def _draw_callback(op, context):
    _draw_axis_letters(op, context)
    helpo = getattr(op, "_help", None)
    hud = getattr(op, "_hud", None)
    last_event = getattr(op, "_last_event", None)
    if helpo is not None:
        helpo.draw(context, last_event)
    if hud is not None:
        hud.draw(context, last_event)


def _draw_axis_letters(op, context):
    """POST_PIXEL: X/Y/Z letters at the tips of the axis gizmo lines."""
    cache = getattr(op, "_ghost_cache", None)
    if cache is None:
        return
    gizmo = cache[4]
    region = context.region
    rv3d = context.region_data
    if not gizmo or region is None or rv3d is None:
        return
    from bpy_extras.view3d_utils import location_3d_to_region_2d
    theme = get_theme(context)
    for letter, label, tip, enabled in gizmo:
        p2 = location_3d_to_region_2d(region, rv3d, tip)
        if p2 is None:
            continue
        r, g, b, _ = axis_color(letter)
        a = 1.0 if enabled else 0.4
        w, h = hud_text.measure(label, theme=theme, size_token="axis_letter")
        hud_text.draw(label, int(p2.x - w * 0.5), int(p2.y + h * 0.6),
                      theme=theme, color=(r, g, b, a), size_token="axis_letter")


# --- State enums (string constants — Blender modal idiom) ----------------

PIVOT_CURSOR = "CURSOR"
PIVOT_ACTIVE = "ACTIVE"
PIVOT_PICK   = "PICK"        # LMB-click picks any object (empty) as the pivot
PIVOT_CYCLE  = (PIVOT_CURSOR, PIVOT_ACTIVE, PIVOT_PICK)

PIVOT_LABELS = {
    PIVOT_CURSOR: "Cursor",
    PIVOT_ACTIVE: "Active",
    PIVOT_PICK:   "Picked object",
}

METHOD_MIRROR = "MIRROR"     # true reflection (negative determinant)
METHOD_ROTATE = "ROTATE180"  # rigid rotation (default 180°) — no flipped normals
METHOD_REFLECT = "REFLECT"   # mirror reproduced by a proper rotation per object:
                             # mirrored placement + orientation, scale positive
METHOD_CYCLE  = (METHOD_MIRROR, METHOD_ROTATE, METHOD_REFLECT)

METHOD_LABELS = {
    METHOD_MIRROR: "Mirror",
    METHOD_ROTATE: "Rotate",
    METHOD_REFLECT: "Reflect",
}

DEFAULT_ROTATE_ANGLE = 180.0

DIGIT_TYPES = {
    "ZERO": "0", "ONE": "1", "TWO": "2", "THREE": "3", "FOUR": "4",
    "FIVE": "5", "SIX": "6", "SEVEN": "7", "EIGHT": "8", "NINE": "9",
    "NUMPAD_0": "0", "NUMPAD_1": "1", "NUMPAD_2": "2", "NUMPAD_3": "3",
    "NUMPAD_4": "4", "NUMPAD_5": "5", "NUMPAD_6": "6", "NUMPAD_7": "7",
    "NUMPAD_8": "8", "NUMPAD_9": "9",
}


def _method_label(op):
    if op.method == METHOD_ROTATE:
        return f"Rotate {op._effective_angle():g}°"
    return METHOD_LABELS[op.method]

CLONE_DUP      = "DUPLICATE"
CLONE_INST     = "INSTANCE"
CLONE_IN_PLACE = "IN_PLACE"  # transform the sources themselves, no clones
CLONE_CYCLE    = (CLONE_DUP, CLONE_INST, CLONE_IN_PLACE)

CLONE_LABELS = {
    CLONE_DUP:      "Duplicate",
    CLONE_INST:     "Instance",
    CLONE_IN_PLACE: "In place",
}

ORIENT_GLOBAL = "GLOBAL"
ORIENT_PIVOT  = "PIVOT"      # cursor axes / active local axes / picked object axes
ORIENT_CYCLE  = (ORIENT_GLOBAL, ORIENT_PIVOT)

AXIS_LETTERS = ("X", "Y", "Z")
_AXIS_UNIT = {"X": Vector((1, 0, 0)), "Y": Vector((0, 1, 0)), "Z": Vector((0, 0, 1))}


def _op_prefs():
    """The addon preferences, or None outside a registered-addon context."""
    try:
        return bpy.context.preferences.addons["InteractionOps"].preferences
    except (KeyError, AttributeError):
        return None


def _cycle(value, options):
    i = options.index(value) if value in options else 0
    return options[(i + 1) % len(options)]


def _build_subtree_data(roots):
    """[(obj), root first then children_recursive] per root — clone units."""
    out = []
    for root in roots:
        try:
            root.matrix_world  # noqa: B018 — probe for dead references
        except ReferenceError:
            continue
        out.append([root, *root.children_recursive])
    return out


def _plane_frame(normal):
    """(right, fwd) orthonormal basis spanning the plane perpendicular to normal."""
    up = normal
    right = Vector((1, 0, 0)) if abs(up.x) < 0.9 else Vector((0, 1, 0))
    right = (right - up * right.dot(up)).normalized()
    fwd = up.cross(right)
    return right, fwd


# --- Mesh geometry cache (verbatim pattern from object_radial_array) ------

def _mesh_geom_cache(obj):
    mesh = obj.data
    verts_local = [v.co.copy() for v in mesh.vertices]
    edge_pairs = [(e.vertices[0], e.vertices[1]) for e in mesh.edges]
    if not mesh.loop_triangles:
        try:
            mesh.calc_loop_triangles()
        except RuntimeError:
            pass
    loops = mesh.loops
    tri_idx = [(loops[lt.loops[0]].vertex_index,
                loops[lt.loops[1]].vertex_index,
                loops[lt.loops[2]].vertex_index)
               for lt in mesh.loop_triangles]
    return verts_local, edge_pairs, tri_idx


def _mesh_edge_segments_world(obj_mw, geom):
    verts_local, edge_pairs, _ = geom
    verts_world = [obj_mw @ v for v in verts_local]
    return [(verts_world[a], verts_world[b]) for a, b in edge_pairs]


def _mesh_face_tris_world(obj_mw, geom):
    verts_local, _, tri_idx = geom
    verts_world = [obj_mw @ v for v in verts_local]
    out = []
    for a, b, c in tri_idx:
        out.append(verts_world[a])
        out.append(verts_world[b])
        out.append(verts_world[c])
    return out


# --- Transform math --------------------------------------------------------

def _axis_reflection(normal, method, angle_rad=math.pi):
    """3x3 building block for one axis: reflection along `normal` (MIRROR) or a
    rigid spin by `angle_rad` around it (ROTATE180)."""
    if method == METHOD_MIRROR:
        return Matrix.Scale(-1.0, 3, normal)
    return Matrix.Rotation(angle_rad, 3, normal)


def _combo_deltas(op, context):
    """World-space delta matrices, one per clone. Every non-empty subset of the
    enabled axes gets a clone (X+Y → 3 clones, like the Mirror modifier); the
    IN_PLACE mode collapses to the single combined transform of all enabled
    axes, since the source can only move once.

    For the REFLECT method the delta is the true mirror of the subset — the
    per-subtree rotation that reproduces it is derived by `_subtree_delta`."""
    normals = _axis_normals(op, context)
    if not normals:
        return []
    letters = sorted(normals.keys(), key=AXIS_LETTERS.index)
    if op.clone_mode == CLONE_IN_PLACE:
        subsets = [tuple(letters)]
    else:
        subsets = [s for r in range(1, len(letters) + 1)
                   for s in combinations(letters, r)]
    T_to = Matrix.Translation(op.pivot_co)
    T_from = Matrix.Translation(-op.pivot_co)
    angle_rad = math.radians(op._effective_angle())
    method = METHOD_MIRROR if op.method == METHOD_REFLECT else op.method
    deltas = []
    for subset in subsets:
        D3 = Matrix.Identity(3)
        for letter in subset:
            D3 = _axis_reflection(normals[letter], method, angle_rad) @ D3
        deltas.append(T_to @ D3.to_4x4() @ T_from)
    return deltas


def _reflect_rotation(mirror_delta, root_mw, first_normal):
    """World delta that reproduces `mirror_delta` for the subtree rooted at
    `root_mw` with a proper rotation. The root origin lands exactly where the
    mirror puts it; its orientation is the mirrored orientation folded back
    across the root's own local axis most parallel to the mirror normal —
    so an axis-aligned piece keeps its orientation and just moves, a piece
    turned 30° about Z comes out turned −30°, exactly like the true mirror
    of a piece symmetric about that local axis. Scale is untouched."""
    S3 = mirror_delta.to_3x3()
    if S3.determinant() > 0.0:
        # An even number of reflections already is a rotation — exact.
        return mirror_delta
    t = root_mw.translation
    R3 = root_mw.to_quaternion().to_matrix()
    # Local axis (world direction) most aligned with the mirror normal.
    best = max(range(3), key=lambda i: abs(R3.col[i].dot(first_normal)))
    fold = Matrix.Scale(-1.0, 3, _AXIS_UNIT[AXIS_LETTERS[best]])
    R_new = S3 @ R3 @ fold
    D3 = R_new @ R3.inverted()
    t_new = mirror_delta @ t
    return Matrix.Translation(t_new) @ D3.to_4x4() @ Matrix.Translation(-t)


def _subtree_delta(op, context, delta, subtree):
    """World delta for one clone subtree. Mirror / Rotate share `delta`;
    Reflect derives the subtree's own rotation from its root transform."""
    if op.method != METHOD_REFLECT:
        return delta
    try:
        root_mw = subtree[0].matrix_world.copy()
    except (ReferenceError, IndexError):
        return delta
    normals = _axis_normals(op, context)
    first = next((normals[a] for a in AXIS_LETTERS if a in normals), Vector((0, 0, 1)))
    return _reflect_rotation(delta, root_mw, first)


def _pivot_frame_3x3(op, context):
    """Orthonormal frame the mirror-plane normals live in."""
    if op.orient_mode == ORIENT_GLOBAL:
        return Matrix.Identity(3)
    if op.pivot_mode == PIVOT_CURSOR:
        return context.scene.cursor.matrix.to_3x3()
    src = op.pivot_obj if op.pivot_mode == PIVOT_PICK else context.active_object
    if src is not None:
        try:
            return src.matrix_world.to_quaternion().to_matrix()
        except ReferenceError:
            pass
    return Matrix.Identity(3)


def _axis_normals(op, context):
    """{letter: world normal} for every enabled mirror axis. `op.axes` maps
    letter -> sign (+1/-1); the sign flips the normal. The mirror/rotate-180
    result is sign-invariant, but the flipped normal turns the rotation arrow
    and gizmo vector around — the readable difference."""
    frame = _pivot_frame_3x3(op, context)
    return {letter: (frame @ _AXIS_UNIT[letter] * op.axes[letter]).normalized()
            for letter in AXIS_LETTERS if letter in op.axes}


def _axes_label(op):
    return "+".join(("-" if op.axes[a] < 0 else "") + a
                    for a in AXIS_LETTERS if a in op.axes) or "—"


# --- T-pick: snap cursor to a face (pattern from object_radial_array) -----

def _tpick_update(op, context, event, region=None, rv3d=None):
    """Pass region/rv3d explicitly when the operator was invoked outside
    the 3D viewport's WINDOW region (e.g. from an N-panel button)."""
    if region is None:
        region = context.region
        rv3d = context.region_data
    if region is None or rv3d is None:
        op._tpick = None
        return
    from bpy_extras.view3d_utils import region_2d_to_origin_3d, region_2d_to_vector_3d
    mouse = Vector((event.mouse_x - region.x, event.mouse_y - region.y))
    origin = region_2d_to_origin_3d(region, rv3d, mouse)
    direction = region_2d_to_vector_3d(region, rv3d, mouse)
    depsgraph = context.evaluated_depsgraph_get()
    hit, loc, normal, idx, obj, mat = context.scene.ray_cast(depsgraph, origin, direction)
    if not hit or obj is None:
        op._tpick = None
        return
    try:
        mesh = obj.evaluated_get(depsgraph).data
        poly = mesh.polygons[idx]
        vids = list(poly.vertices)
        vw = [mat @ mesh.vertices[vi].co for vi in vids]
    except (AttributeError, IndexError, ReferenceError):
        op._tpick = None
        return
    n = len(vw)
    if n < 3:
        op._tpick = None
        return
    center = mat @ poly.center
    mids = [(vw[i] + vw[(i + 1) % n]) * 0.5 for i in range(n)]
    snaps = list(vw) + mids + [center]
    closest = min(snaps, key=lambda p: (p - loc).length)
    tris = []
    for i in range(1, n - 1):
        tris.extend([vw[0], vw[i], vw[i + 1]])
    edges = []
    for i in range(n):
        edges.append(vw[i])
        edges.append(vw[(i + 1) % n])
    nlen = sum((m - center).length for m in mids) / n if n else 0.3
    op._tpick = {
        "tris": tris, "edges": edges, "snaps": snaps,
        "closest": closest, "normal": normal.normalized(),
        "nlen": max(nlen, 1e-3),
    }


def _draw_tpick(op, context):
    tp = getattr(op, "_tpick", None)
    if not tp:
        return
    from ..ui.draw import primitives as iops_draw
    from ..ui.draw import draw_scope

    if tp["tris"]:
        with draw_scope(blend="ALPHA", depth="LESS_EQUAL",
                        face_culling="NONE", depth_mask=False):
            iops_draw.tris(tp["tris"], role=Role.GHOST_DEFAULT, context=context)
    if tp["edges"]:
        with draw_scope(blend="ALPHA", depth="LESS_EQUAL"):
            iops_draw.edges_3d(tp["edges"], role=Role.CLOSEST_LINE, context=context)
    nlen = tp.get("nlen", 0.3) or 0.3
    with draw_scope(blend="ALPHA", depth="LESS_EQUAL"):
        iops_draw.edges_3d([tp["closest"], tp["closest"] + tp["normal"] * nlen],
                           role=Role.ACTIVE_LINE, context=context)
    with draw_scope(blend="ALPHA", depth="NONE"):
        if tp["snaps"]:
            iops_draw.points(tp["snaps"], role=Role.PREVIEW_POINT, context=context)
        iops_draw.points([tp["closest"]], role=Role.CLOSEST_POINT, context=context)


# --- Preview (POST_VIEW) ----------------------------------------------------

def _sources_centroid(op):
    """Centroid of the source root origins; None when there are no sources."""
    pts = []
    for subtree in op.subtree_data:
        try:
            pts.append(subtree[0].matrix_world.translation.copy())
        except (ReferenceError, IndexError):
            continue
    if not pts:
        return None
    acc = Vector((0.0, 0.0, 0.0))
    for p in pts:
        acc += p
    return acc / len(pts)


def _rotation_arrow_edges(op, axis_n, ext, angle_rad):
    """Flat edge list for a rotation-direction arrow around `axis_n`:
    an arc from the sources' centroid to where the turn by `angle_rad` lands
    it (right-hand CCW — the same sweep `Matrix.Rotation(angle, axis)`
    performs; a negative angle sweeps the other way), with an arrowhead at
    the end."""
    if abs(angle_rad) < 1e-4:
        return []
    p = op.pivot_co
    anchor = _sources_centroid(op)
    radial = None
    if anchor is not None:
        v = anchor - p
        radial = v - axis_n * v.dot(axis_n)
    if radial is None or radial.length < 1e-4:
        radial = _plane_frame(axis_n)[0] * (ext * 0.5)
    R = radial.length
    e1 = radial.normalized()
    e2 = axis_n.cross(e1)

    edges = []
    steps = max(8, int(48 * abs(angle_rad) / math.pi))
    pts = [p + (e1 * math.cos(angle_rad * i / steps)
                + e2 * math.sin(angle_rad * i / steps)) * R
           for i in range(steps + 1)]
    for i in range(steps):
        edges.append(pts[i])
        edges.append(pts[i + 1])

    # Arrowhead at the arc end. Tangent (travel direction) at a is the sweep
    # derivative; wings swept back against it, spread along the radial.
    end = pts[-1]
    tangent = (-e1 * math.sin(angle_rad) + e2 * math.cos(angle_rad))
    if angle_rad < 0:
        tangent = -tangent
    out_dir = e1 * math.cos(angle_rad) + e2 * math.sin(angle_rad)
    wing_len = max(R * 0.12, 0.05)
    for side in (1.0, -1.0):
        edges.append(end)
        edges.append(end - tangent * wing_len + out_dir * (wing_len * 0.5 * side))
    return edges


def _sources_extent(op):
    """Radius (from the pivot) that comfortably covers the sources and their
    mirrored clones — used to size the mirror-plane quads."""
    r = 0.0
    for subtree in op.subtree_data:
        for obj in subtree:
            try:
                mw = obj.matrix_world
                for corner in obj.bound_box:
                    r = max(r, (mw @ Vector(corner) - op.pivot_co).length)
            except ReferenceError:
                continue
    return max(r * 1.1, 1.0)


def _build_ghosts(op, context):
    """(segs, tris, plane_quads, plane_outlines, axis_gizmo, rot_arcs) for the
    preview. plane_quads is a flat tri list; outlines are flat edge lists;
    axis_gizmo is [(letter, tip, enabled)]; rot_arcs is [(letter, edge_list)]
    with a 180° arrow arc per enabled axis (Rotate method only)."""
    op.subtree_data = _build_subtree_data([sub[0] for sub in op.subtree_data])

    segs = []
    tris = []
    cache = getattr(op, "_mesh_cache", {})
    for base_delta in _combo_deltas(op, context):
        for subtree in op.subtree_data:
            delta = _subtree_delta(op, context, base_delta, subtree)
            for obj in subtree:
                try:
                    clone_mw = delta @ obj.matrix_world
                except ReferenceError:
                    continue
                geom = cache.get(obj)
                if geom is not None:
                    for a, b in _mesh_edge_segments_world(clone_mw, geom):
                        segs.append(a)
                        segs.append(b)
                    tris.extend(_mesh_face_tris_world(clone_mw, geom))

    plane_quads = []
    plane_outlines = []
    rot_arcs = []
    ext = _sources_extent(op)
    if op.method in (METHOD_MIRROR, METHOD_REFLECT):
        # Mirror / Reflect: the plane IS the tool — draw it (Reflect mirrors
        # by rotation, but it is still a mirror to the user).
        for n in _axis_normals(op, context).values():
            right, fwd = _plane_frame(n)
            p = op.pivot_co
            c = [p + right * ext + fwd * ext, p - right * ext + fwd * ext,
                 p - right * ext - fwd * ext, p + right * ext - fwd * ext]
            plane_quads.extend([c[0], c[1], c[2], c[0], c[2], c[3]])
            for i in range(4):
                plane_outlines.append(c[i])
                plane_outlines.append(c[(i + 1) % 4])
    else:
        # Rotate: a plane is misleading — draw the turn itself: an arrow arc
        # around each enabled axis, from the sources' centroid to where the
        # clone lands.
        angle_rad = math.radians(op._effective_angle())
        for letter, n in _axis_normals(op, context).items():
            rot_arcs.append((letter, _rotation_arrow_edges(op, n, ext, angle_rad)))

    # Axis gizmo: all three frame directions from the pivot, the enabled ones
    # long and bright, the disabled ones short and dim — so X/Y/Z reads at a
    # glance before pressing the key.
    frame = _pivot_frame_3x3(op, context)
    gizmo_scale = get_theme(context).axis_gizmo_size
    axis_gizmo = []
    for letter in AXIS_LETTERS:
        sign = op.axes.get(letter)
        enabled = sign is not None
        d = (frame @ _AXIS_UNIT[letter] * (sign or 1)).normalized()
        tip = op.pivot_co + d * (ext * (0.55 if enabled else 0.35) * gizmo_scale)
        label = ("-" + letter) if (sign or 1) < 0 else letter
        axis_gizmo.append((letter, label, tip, enabled))
    return segs, tris, plane_quads, plane_outlines, axis_gizmo, rot_arcs


def _draw_preview_3d(op, context):
    from ..ui.draw import primitives as iops_draw
    from ..ui.draw import draw_scope

    if op._dirty or getattr(op, "_ghost_cache", None) is None:
        op._ghost_cache = _build_ghosts(op, context)
        op._dirty = False
    segs, tris, plane_quads, plane_outlines, axis_gizmo, rot_arcs = op._ghost_cache

    # Two-pass transparent fill (depth pre-pass, then color at depth=EQUAL) so
    # overlapping clones don't alpha-stack. Culling stays off — mirrored
    # geometry has inverted winding.
    if tris:
        with draw_scope(blend="NONE", depth="LESS_EQUAL",
                        face_culling="NONE", depth_mask=True,
                        color_mask=(False, False, False, False)):
            iops_draw.tris(tris, role=Role.GHOST_DEFAULT, context=context)
        with draw_scope(blend="ALPHA", depth="EQUAL",
                        face_culling="NONE", depth_mask=False):
            iops_draw.tris(tris, role=Role.GHOST_DEFAULT, context=context)
    if segs:
        with draw_scope(blend="ALPHA", depth="LESS_EQUAL"):
            iops_draw.edges_3d(segs, role=Role.GHOST_EDGE, context=context)

    if plane_quads:
        with draw_scope(blend="ALPHA", depth="LESS_EQUAL",
                        face_culling="NONE", depth_mask=False):
            iops_draw.tris(plane_quads, role=Role.GHOST_LOCKED, context=context)
        with draw_scope(blend="ALPHA", depth="LESS_EQUAL"):
            iops_draw.edges_3d(plane_outlines, role=Role.PREVIEW_LINE, context=context)
    # Rotate 180°: arrow arcs around the enabled axes, in the axis colors.
    if rot_arcs:
        with draw_scope(blend="ALPHA", depth="NONE"):
            for letter, edges in rot_arcs:
                r, g, b, _ = axis_color(letter)
                iops_draw.edges_3d(edges, color=(r, g, b, 0.9),
                                   width="axis_gizmo", context=context)

    # Axis gizmo: colored X/Y/Z direction vectors from the pivot (letters are
    # drawn at the tips by the POST_PIXEL callback).
    if axis_gizmo:
        with draw_scope(blend="ALPHA", depth="NONE"):
            for letter, _label, tip, enabled in axis_gizmo:
                r, g, b, _ = axis_color(letter)
                iops_draw.edges_3d([op.pivot_co, tip],
                                   color=(r, g, b, 1.0 if enabled else 0.35),
                                   width="axis_gizmo", context=context)
                iops_draw.points([tip], color=(r, g, b, 1.0 if enabled else 0.35),
                                 size=6.0, context=context)

    with draw_scope(blend="ALPHA", depth="NONE"):
        iops_draw.points([op.pivot_co], role=Role.PIVOT, context=context)

    if getattr(op, "pending_normal_pick", False):
        _draw_tpick(op, context)


class IOPS_OT_Object_Mirror_Rotate(bpy.types.Operator):
    """Mirror-clone selected objects across a plane through the cursor, the
    active object or any picked object — as a true mirror, a rigid rotation
    (default 180°, type digits for a custom angle) or a Reflect: the mirror
    reproduced by a proper rotation per object, scale stays positive"""

    bl_idname = "iops.object_mirror_rotate"
    bl_label = "OBJECT: Mirror Rotate"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (
            context.mode == "OBJECT"
            and context.area is not None
            and context.area.type == "VIEW_3D"
            and context.active_object is not None
        )

    def invoke(self, context, event):
        sel = list(context.selected_objects)
        if not sel:
            self.report({"WARNING"}, "Select at least one object")
            return {"CANCELLED"}

        self._load_defaults()
        self.pivot_obj = None            # picked pivot (PIVOT_PICK)
        self.pivot_co = Vector((0, 0, 0))
        self.pending_normal_pick = False
        self._tpick = None
        self._dirty = True

        self._resolve_pivot(context)
        self._rebuild_sources(context)
        if not self.subtree_data:
            self.report({"WARNING"}, "Select at least one source object")
            return {"CANCELLED"}

        self._hud = _build_hud(context)
        self._hud.add_param(HUDParam("Pivot",  lambda: self._pivot_hud_label(), "str"))
        self._hud.add_param(HUDParam("Axes",   lambda: _axes_label(self), "str"))
        self._hud.add_param(HUDParam("Orientation", lambda: "Global" if self.orient_mode == ORIENT_GLOBAL else "Pivot", "str"))
        self._hud.add_param(HUDParam("Method", lambda: _method_label(self), "str"))
        self._hud.add_param(HUDParam("Angle",  lambda: self._angle_hud_label(), "str"))
        self._hud.add_param(HUDParam("Clone",  lambda: CLONE_LABELS[self.clone_mode], "str"))
        self._hud.add_param(HUDParam("Apply transforms", lambda: self.apply_transforms, "bool"))
        self._help = _build_help(context)
        self._last_event = capture_event(event, None)
        self._handle = safe_handler_add(
            bpy.types.SpaceView3D, _draw_callback, (self, context),
            "WINDOW", "POST_PIXEL", tick=True,
        )
        self._handle_3d = safe_handler_add(
            bpy.types.SpaceView3D, _draw_preview_3d, (self, context),
            "WINDOW", "POST_VIEW", tick=False,
        )
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def _pivot_hud_label(self):
        if self.pivot_mode == PIVOT_PICK:
            if self.pivot_obj is not None:
                try:
                    return f"Picked: {self.pivot_obj.name}"
                except ReferenceError:
                    return "Picked: <gone>"
            return "Pick: click an object"
        return PIVOT_LABELS[self.pivot_mode]

    def modal(self, context, event):
        context.area.tag_redraw()
        self._last_event = capture_event(event, getattr(self, "_last_event", None))

        try:
            theme_prefs = context.preferences.addons["InteractionOps"].preferences.iops_theme
        except (KeyError, AttributeError):
            theme_prefs = None
        if theme_prefs is not None:
            for ov in (self._help, self._hud):
                if ov is None:
                    continue
                if ov.handle_drag_event(context, event, theme_prefs):
                    return {"RUNNING_MODAL"}
            if self._help.handle_toggle_event(event, theme_prefs):
                return {"RUNNING_MODAL"}
            if self._hud.handle_param_toggle_event(event, theme_prefs):
                return {"RUNNING_MODAL"}

        # Navigation always passes through.
        if event.type == "MIDDLEMOUSE":
            return {"PASS_THROUGH"}
        if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            if event.alt and self.method == METHOD_ROTATE:
                delta = 5.0 if event.type == "WHEELUPMOUSE" else -5.0
                self.rotate_angle = self._effective_angle() + delta
                self.input_str = ""
                self._dirty = True
                self.report({"INFO"}, f"Angle: {self.rotate_angle:g}°")
                return {"RUNNING_MODAL"}
            return {"PASS_THROUGH"}
        if event.type in {"TRACKPADPAN", "TRACKPADZOOM"}:
            return {"PASS_THROUGH"}

        # --- pivot cycle ---
        if event.type == "Q" and event.value == "PRESS":
            self.pivot_mode = _cycle(self.pivot_mode, PIVOT_CYCLE)
            self.pending_pivot_pick = (self.pivot_mode == PIVOT_PICK)
            self._resolve_pivot(context)
            self._rebuild_sources(context)
            self._dirty = True
            if self.pivot_mode == PIVOT_PICK:
                self.report({"INFO"}, "Pivot: click an object (empty) to set the pivot")
            else:
                self.report({"INFO"}, f"Pivot: {PIVOT_LABELS[self.pivot_mode]}")
            return {"RUNNING_MODAL"}

        # --- mirror axes: each key cycles off → +axis → −axis → off ---
        if event.type in {"X", "Y", "Z"} and event.value == "PRESS":
            letter = event.type
            sign = self.axes.get(letter)
            if sign is None:
                self.axes[letter] = 1
            elif sign > 0:
                self.axes[letter] = -1
            else:
                del self.axes[letter]
            self._dirty = True
            self.report({"INFO"}, f"Axes: {_axes_label(self)}")
            return {"RUNNING_MODAL"}

        if event.type == "W" and event.value == "PRESS":
            self.orient_mode = _cycle(self.orient_mode, ORIENT_CYCLE)
            self._dirty = True
            self.report({"INFO"}, f"Orientation: {'Global' if self.orient_mode == ORIENT_GLOBAL else 'Pivot frame'}")
            return {"RUNNING_MODAL"}

        if event.type == "E" and event.value == "PRESS":
            self.method = _cycle(self.method, METHOD_CYCLE)
            # Two workflows: Mirror bakes transforms (and flips normals on the
            # reflection), Rotate is rigid and needs no bake. Defaults per
            # method come from the preferences; A can still override afterwards.
            self.apply_transforms = self._apply_default_for_method()
            self.input_str = ""
            self._dirty = True
            self.report({"INFO"},
                        f"Method: {_method_label(self)}  |  Apply transforms: "
                        f"{'on' if self.apply_transforms else 'off'}")
            return {"RUNNING_MODAL"}

        # --- rotate angle: typed digits (Rotate method only) ---
        if self.method == METHOD_ROTATE and event.value == "PRESS":
            handled = True
            if event.type in DIGIT_TYPES:
                self.input_str += DIGIT_TYPES[event.type]
            elif event.type in {"PERIOD", "NUMPAD_PERIOD"} and "." not in self.input_str:
                self.input_str += "."
            elif event.type in {"MINUS", "NUMPAD_MINUS"}:
                if self.input_str:
                    self.input_str = (self.input_str[1:]
                                      if self.input_str.startswith("-")
                                      else "-" + self.input_str)
                else:
                    self.rotate_angle = -self.rotate_angle
            elif event.type == "BACK_SPACE" and self.input_str:
                self.input_str = self.input_str[:-1]
            else:
                handled = False
            if handled:
                self._dirty = True
                self.report({"INFO"}, f"Angle: {self._effective_angle():g}°")
                return {"RUNNING_MODAL"}

        if event.type == "D" and event.value == "PRESS":
            self.clone_mode = _cycle(self.clone_mode, CLONE_CYCLE)
            self._dirty = True
            self.report({"INFO"}, f"Clone: {CLONE_LABELS[self.clone_mode]}")
            return {"RUNNING_MODAL"}

        if event.type == "A" and event.value == "PRESS":
            self.apply_transforms = not self.apply_transforms
            self.report({"INFO"}, f"Apply transforms: {'on' if self.apply_transforms else 'off'}")
            return {"RUNNING_MODAL"}

        if event.type == "B" and event.value == "PRESS":
            self._reset_defaults()
            self._resolve_pivot(context)
            self._rebuild_sources(context)
            self.report({"INFO"}, "Mirror Rotate reset to defaults")
            return {"RUNNING_MODAL"}

        # --- face pick: snap the 3D cursor ---
        if event.type == "C" and event.value == "PRESS":
            self.pending_normal_pick = True
            _tpick_update(self, context, event)
            context.area.tag_redraw()
            self.report({"INFO"}, "Hover a face; click a vert / edge-mid / center to snap the 3D cursor there")
            return {"RUNNING_MODAL"}

        if self.pending_normal_pick and event.type == "MOUSEMOVE":
            _tpick_update(self, context, event)
            context.area.tag_redraw()
            return {"RUNNING_MODAL"}

        if self.pending_normal_pick and event.type == "LEFTMOUSE" and event.value == "PRESS":
            _tpick_update(self, context, event)
            tp = self._tpick
            if tp is not None:
                cursor = context.scene.cursor
                cursor.location = tp["closest"].copy()
                cursor.rotation_mode = "XYZ"
                cursor.rotation_euler = tp["normal"].to_track_quat("Z", "Y").to_euler()
                self.pivot_mode = PIVOT_CURSOR
                self.orient_mode = ORIENT_PIVOT
                self._resolve_pivot(context)
                self._rebuild_sources(context)
                self._dirty = True
                self.report({"INFO"}, "Cursor snapped to face (pivot = Cursor, planes in cursor frame)")
            else:
                self.report({"WARNING"}, "No face under cursor")
            self.pending_normal_pick = False
            self._tpick = None
            return {"RUNNING_MODAL"}

        # --- pivot object pick ---
        if self.pending_pivot_pick and event.type == "LEFTMOUSE" and event.value == "PRESS":
            picked = self._pick_object(context, event)
            if picked is not None:
                self.pivot_obj = picked
                self.pending_pivot_pick = False
                self._resolve_pivot(context)
                self._rebuild_sources(context)
                self._dirty = True
                self.report({"INFO"}, f"Pivot object: {picked.name}")
            else:
                self.report({"WARNING"}, "No object origin near the click")
            return {"RUNNING_MODAL"}

        if event.type in {"RET", "NUMPAD_ENTER", "SPACE"} and event.value == "PRESS":
            self._apply(context)
            self._cleanup()
            return {"FINISHED"}

        if self.pending_normal_pick and event.type == "ESC" and event.value == "PRESS":
            self.pending_normal_pick = False
            self._tpick = None
            context.area.tag_redraw()
            self.report({"INFO"}, "Face pick cancelled")
            return {"RUNNING_MODAL"}

        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            self._cleanup()
            return {"CANCELLED"}

        return {"RUNNING_MODAL"}

    # --- pivot / sources -----------------------------------------------------

    def _resolve_pivot(self, context):
        active = context.active_object
        cursor = context.scene.cursor
        if self.pivot_mode == PIVOT_ACTIVE and active is not None:
            self.pivot_co = active.matrix_world.translation.copy()
        elif self.pivot_mode == PIVOT_PICK and self.pivot_obj is not None:
            try:
                self.pivot_co = self.pivot_obj.matrix_world.translation.copy()
            except ReferenceError:
                self.pivot_obj = None
                self.pivot_co = cursor.location.copy()
        else:
            self.pivot_co = cursor.location.copy()

    def _pick_object(self, context, event):
        """Nearest visible object origin to the click, in screen space — works
        for empties too (no geometry to raycast)."""
        region = context.region
        rv3d = context.region_data
        if region is None or rv3d is None:
            return None
        from bpy_extras.view3d_utils import location_3d_to_region_2d
        mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        best, best_d = None, 1e9
        for obj in context.visible_objects:
            try:
                p2 = location_3d_to_region_2d(region, rv3d, obj.matrix_world.translation)
            except ReferenceError:
                continue
            if p2 is None:
                continue
            d = (p2 - mouse).length
            if d < best_d:
                best_d, best = d, obj
        return best if best_d <= 40.0 else None

    def _rebuild_sources(self, context):
        """Sources: the selection, minus the pivot object when it doubles as the
        pivot (active pivot / picked pivot). Children come along per subtree."""
        sel = list(context.selected_objects)
        active = context.active_object
        if self.pivot_mode == PIVOT_ACTIVE and active is not None:
            roots = [o for o in sel if o is not active]
            if not roots:
                roots = [active]     # single object mirrored around itself
        elif self.pivot_mode == PIVOT_PICK and self.pivot_obj is not None:
            roots = [o for o in sel if o is not self.pivot_obj]
        else:
            roots = sel
        self.subtree_data = _build_subtree_data(roots)
        cache = {}
        for subtree in self.subtree_data:
            for obj in subtree:
                if obj.type == "MESH" and obj.data is not None and obj not in cache:
                    try:
                        cache[obj] = _mesh_geom_cache(obj)
                    except (ReferenceError, AttributeError):
                        pass
        self._mesh_cache = cache

    def _load_defaults(self):
        """Start-up state from the addon preferences (Mirror Rotate section);
        hardcoded fallbacks when prefs are unavailable."""
        p = _op_prefs()
        self.pivot_mode = getattr(p, "mirror_rotate_pivot", PIVOT_CURSOR) if p else PIVOT_CURSOR
        self.orient_mode = getattr(p, "mirror_rotate_orientation", ORIENT_GLOBAL) if p else ORIENT_GLOBAL
        self.method = getattr(p, "mirror_rotate_method", METHOD_MIRROR) if p else METHOD_MIRROR
        self.clone_mode = getattr(p, "mirror_rotate_clone", CLONE_DUP) if p else CLONE_DUP
        self.rotate_angle = DEFAULT_ROTATE_ANGLE
        self.input_str = ""
        self.axes = {(getattr(p, "mirror_rotate_axis", "X") if p else "X"): 1}
        self.apply_transforms = self._apply_default_for_method()
        self.pending_pivot_pick = (self.pivot_mode == PIVOT_PICK)

    def _effective_angle(self):
        """Rotate angle in degrees: the typed buffer when it parses, else the
        committed value."""
        if self.input_str and self.input_str not in ("-", ".", "-."):
            try:
                return float(self.input_str)
            except ValueError:
                pass
        return self.rotate_angle

    def _angle_hud_label(self):
        if self.method != METHOD_ROTATE:
            return "—"
        if self.input_str:
            return f"{self.input_str}_"
        return f"{self.rotate_angle:g}°"

    def _apply_default_for_method(self):
        """Per-method Apply-transforms default from the preferences: two
        workflows — Mirror bakes (and flips normals), Rotate / Reflect are
        rigid and share the Rotate default."""
        p = _op_prefs()
        if self.method == METHOD_MIRROR:
            return bool(getattr(p, "mirror_rotate_apply_mirror", True)) if p else True
        return bool(getattr(p, "mirror_rotate_apply_rotate", False)) if p else False

    def _reset_defaults(self):
        self._load_defaults()
        self.pivot_obj = None
        self.pending_normal_pick = False
        self._tpick = None
        self._dirty = True

    def _cleanup(self):
        if getattr(self, "_handle", None) is not None:
            safe_handler_remove(self._handle, bpy.types.SpaceView3D, "WINDOW")
            self._handle = None
        if getattr(self, "_handle_3d", None) is not None:
            safe_handler_remove(self._handle_3d, bpy.types.SpaceView3D, "WINDOW")
            self._handle_3d = None

    # --- apply -----------------------------------------------------------------

    def _apply(self, context):
        deltas = _combo_deltas(self, context)
        if not deltas:
            self.report({"WARNING"}, "No mirror axis enabled — nothing to do")
            return
        if not self.subtree_data:
            return

        created_roots = []
        jobs = []       # (obj, target_world), parents always before children

        def _clone_subtree(subtree, delta):
            clone_map = {}
            for obj in subtree:
                new = obj.copy()
                if self.clone_mode == CLONE_DUP and obj.data is not None:
                    new.data = obj.data.copy()
                for c in obj.users_collection:
                    try:
                        c.objects.link(new)
                    except RuntimeError:
                        pass
                clone_map[obj] = new
            for obj in subtree:
                new = clone_map[obj]
                if obj.parent is not None and obj.parent in clone_map:
                    new.parent = clone_map[obj.parent]
                    new.matrix_parent_inverse = obj.matrix_parent_inverse.copy()
                else:
                    new.parent = None
                jobs.append((new, delta @ obj.matrix_world))
            created_roots.append(clone_map[subtree[0]])

        if self.clone_mode == CLONE_IN_PLACE:
            base_delta = deltas[0]
            for subtree in self.subtree_data:
                delta = _subtree_delta(self, context, base_delta, subtree)
                for obj in subtree:
                    try:
                        jobs.append((obj, delta @ obj.matrix_world))
                    except ReferenceError:
                        continue
                created_roots.append(subtree[0])
        else:
            for base_delta in deltas:
                for subtree in self.subtree_data:
                    _clone_subtree(subtree, _subtree_delta(self, context, base_delta, subtree))

        self._finalize_transforms(jobs)
        if not self.apply_transforms and self.method == METHOD_MIRROR:
            self.report({"INFO"}, "Mirror clones keep negative scale (Apply transforms is off)")

        for obj in context.view_layer.objects:
            try:
                obj.select_set(False)
            except RuntimeError:
                pass
        for r in created_roots:
            try:
                r.select_set(True)
            except RuntimeError:
                pass
        if created_roots:
            try:
                context.view_layer.objects.active = created_roots[0]
            except (AttributeError, RuntimeError):
                pass

    def _finalize_transforms(self, jobs):
        """Place every object at its computed target world matrix, optionally
        baking rotation & scale into the mesh data (with a normal flip when the
        transform is a reflection) — the negative-scale cleanup that makes
        mirrored kitbash clones export-safe.

        The target matrices are computed here from scratch and local matrices
        are derived through the parent chain explicitly: the matrix_world
        setter reads the parent's world from the depsgraph, which is stale for
        objects created or moved in the same tick.

        Linked (multi-user) mesh data is made single-user before baking so the
        reflection lands in this clone's own copy; INSTANCE clones keep their
        shared data and stay mirrored at the object level instead."""
        final = {}
        kept_shared = 0
        for obj, target in jobs:
            desired = target
            if self.apply_transforms and obj.type == "MESH" and obj.data is not None:
                data = obj.data
                if data.users > 1:
                    if self.clone_mode == CLONE_INST:
                        data = None       # instances share data — nothing to bake
                        kept_shared += 1
                    else:
                        data = data.copy()
                        obj.data = data
                if data is not None:
                    rs = target.to_3x3()
                    try:
                        data.transform(rs.to_4x4())
                        if rs.determinant() < 0.0:
                            data.flip_normals()
                        desired = Matrix.Translation(target.translation)
                    except RuntimeError:
                        desired = target
            parent = obj.parent
            if parent is not None and parent in final:
                # Local matrix through the just-final parent world — the only
                # reliable route while the depsgraph hasn't re-evaluated.
                try:
                    obj.matrix_basis = (obj.matrix_parent_inverse.inverted()
                                        @ final[parent].inverted() @ desired)
                except ValueError:
                    obj.matrix_world = desired
            else:
                try:
                    obj.matrix_world = desired
                except ReferenceError:
                    continue
            final[obj] = desired
        if kept_shared:
            self.report({"INFO"},
                        f"{kept_shared} instanced mesh(es) keep shared data (mirrored at object level)")
