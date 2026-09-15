"""Three Point Rotation — aim an object's axes at picked points, or land a
face of it onto any face in the scene. The originals stay put; a themed
ghost of the selection shows the result live and the click applies it. No
helper objects, no constraints, no tool-settings changes, one undo step.

Modes (Tab):
  FACE  hover the selected object: the face + snap point under the cursor
        is the source (sticky — it stays when the cursor leaves). Hover any
        other face: the ghost lands there, anchor onto anchor. By default
        the orientation is kept (pure move); R adds rotation — match the
        normals, or normals + roll from the picked edges. LMB applies. One
        click.
  AIM   pivot = object origin (Shift+LMB picks another point on the object);
        hover aims the primary local axis at the point under the cursor,
        click locks it; hover then rolls the secondary axis, click locks;
        Space applies.
"""
import bpy
import gpu
from mathutils import Vector, Matrix
from bpy_extras.view3d_utils import (
    region_2d_to_vector_3d, region_2d_to_origin_3d, location_3d_to_region_2d,
)

from ..ui.draw import primitives as iops_draw
from ..ui.draw import draw_scope, safe_handler_add, safe_handler_remove
from ..ui.draw.theme import get_theme, axis_color, Role
from ..ui.hud import text as hud_text
from ..ui.hud import (HUDOverlay, HelpOverlay, HUDSection, HUDItem,
                      HUDParam, ItemState, capture_event)
from ..utils.picking import raycast_from_mouse, hit_owner, SNAP_THRESHOLD_PX
from ..utils.three_point_core import (
    DegenerateFrame, frame_from_points, frame_from_face, axis_frame,
    align_matrix, rotation_angle_deg,
)


MODE_FACE = "FACE"
MODE_AIM = "AIM"
MODE_LABELS = {MODE_FACE: "Face to face", MODE_AIM: "Aim axes"}

AXIS_LETTERS = ("X", "Y", "Z")

# Face mode: how much of the orientation the move is allowed to change.
ROT_KEEP = "KEEP"        # translation only — anchor onto anchor, no rotation
ROT_NORMAL = "NORMAL"    # minimal rotation that lines the normals up
ROT_EDGE = "EDGE"        # normals + roll from the picked edges
ROT_CYCLE = (ROT_KEEP, ROT_NORMAL, ROT_EDGE)
ROT_LABELS = {ROT_KEEP: "keep (move only)", ROT_NORMAL: "match normals", ROT_EDGE: "normals + edge"}
GHOST_FILL_TRI_CAP = 400_000     # above this the ghost is edges only


def _flip_axis(token):
    return token[1:] if token.startswith("-") else "-" + token


def _letter(token):
    return token.lstrip("-")


def _roots(objects):
    """Selected objects whose ancestors are not selected — the ones that
    receive the delta; their children follow through the parent chain."""
    sel = set(objects)
    out = []
    for ob in objects:
        p = ob.parent
        while p is not None and p not in sel:
            p = p.parent
        if p is None:
            out.append(ob)
    return out


def _tuple_matrix(m):
    return Matrix([tuple(row) for row in m])


# --- ghost geometry -------------------------------------------------------

def _gather_ghost(context, moving):
    """World-space triangle soup + edge segments of everything that will
    move: the selected objects, their children and the geometry of any
    collection instances they own. Read once at invoke (nothing moves until
    confirm), drawn through a gpu matrix push of the delta."""
    depsgraph = context.evaluated_depsgraph_get()
    tris, edges = [], []
    for inst in depsgraph.object_instances:
        ob = inst.object
        try:
            orig = ob.original
            owner = inst.parent.original if (inst.is_instance and inst.parent is not None) else orig
        except (ReferenceError, AttributeError):
            continue
        if owner not in moving or ob.type != "MESH":
            continue
        me = ob.data
        if me is None:
            continue
        mw = inst.matrix_world.copy()
        try:
            if not me.loop_triangles:
                me.calc_loop_triangles()
            vw = [mw @ v.co for v in me.vertices]
            loops = me.loops
            for lt in me.loop_triangles:
                tris.append(vw[loops[lt.loops[0]].vertex_index])
                tris.append(vw[loops[lt.loops[1]].vertex_index])
                tris.append(vw[loops[lt.loops[2]].vertex_index])
            for e in me.edges:
                edges.append(vw[e.vertices[0]])
                edges.append(vw[e.vertices[1]])
        except (RuntimeError, ReferenceError, IndexError):
            continue
    return tris, edges


# --- hover picking (one primitive for both modes) -------------------------

def _pick_face(context, mouse, *, restrict_to=None, exclude=None):
    """Raycast under the cursor and describe the hit face in world space.
    The snap point is chosen in screen space: a vertex or edge midpoint only
    when it is within SNAP_THRESHOLD_PX of the cursor, else the face center.
    Returns a dict or None on miss."""
    region = context.region
    rv3d = context.region_data
    if region is None or rv3d is None:
        return None
    hit, loc, normal, idx, obj, mat = raycast_from_mouse(
        context, mouse, restrict_to=restrict_to, exclude=exclude,
        visible_only=True, region=region, rv3d=rv3d)
    if not hit or obj is None:
        return None
    depsgraph = context.evaluated_depsgraph_get()
    owner = hit_owner(depsgraph, obj, mat, view_layer=context.view_layer)
    try:
        mesh = obj.evaluated_get(depsgraph).data
        poly = mesh.polygons[idx]
        vw = [mat @ mesh.vertices[vi].co for vi in poly.vertices]
    except (AttributeError, IndexError, ReferenceError, TypeError):
        return None
    n = len(vw)
    if n < 3:
        return None
    center = mat @ poly.center
    mids = [(vw[i] + vw[(i + 1) % n]) * 0.5 for i in range(n)]
    snaps = list(vw) + mids + [center]
    # screen-space snap: nearest vertex / midpoint within the threshold
    mouse_v = Vector(mouse)
    closest, best = center, SNAP_THRESHOLD_PX
    for p in vw + mids:
        s = location_3d_to_region_2d(region, rv3d, p)
        if s is None:
            continue
        d = (mouse_v - Vector(s)).length
        if d < best:
            best, closest = d, p
    # nearest edge to the hit point → roll direction (polygon winding)
    best_i, best_d = 0, float("inf")
    for i in range(n):
        a, b = vw[i], vw[(i + 1) % n]
        ab = b - a
        L2 = ab.length_squared
        t = 0.0 if L2 < 1e-12 else max(0.0, min(1.0, (loc - a).dot(ab) / L2))
        d = (loc - (a + ab * t)).length
        if d < best_d:
            best_d, best_i = d, i
    tris = []
    for i in range(1, n - 1):
        tris.extend([vw[0], vw[i], vw[i + 1]])
    edges = []
    for i in range(n):
        edges.extend([vw[i], vw[(i + 1) % n]])
    return {
        "hit": loc, "obj": obj, "owner": owner, "normal": normal.normalized(),
        "center": center, "verts": vw, "snaps": snaps, "closest": closest,
        "edge_idx": best_i, "tris": tris, "edges": edges,
    }


def _face_edge(face, shift=0):
    """(a, b, unit direction) of the roll edge: nearest edge to the cursor,
    cycled by `shift` steps around the polygon."""
    vw = face["verts"]
    n = len(vw)
    i = (face["edge_idx"] + shift) % n
    a, b = vw[i], vw[(i + 1) % n]
    d = b - a
    if d.length < 1e-9:
        d = Vector((1, 0, 0))
    return a, b, d.normalized()


def _mouse_on_view_plane(context, mouse, through):
    """Point where the mouse ray crosses the view-aligned plane through
    `through` — the fallback aim target when nothing is under the cursor."""
    region = context.region
    rv3d = context.region_data
    if region is None or rv3d is None:
        return None
    origin = region_2d_to_origin_3d(region, rv3d, mouse)
    direction = region_2d_to_vector_3d(region, rv3d, mouse)
    view_n = (rv3d.view_rotation @ Vector((0, 0, 1))).normalized()
    denom = direction.dot(view_n)
    if abs(denom) < 1e-9:
        return None
    t = (through - origin).dot(view_n) / denom
    return origin + direction * t


# --- drawing -------------------------------------------------------------
#
# Restraint: only what the decision needs. The ghost is a soft tinted volume,
# faces are a faint wash with a hairline outline, the anchor and the roll
# edge are the only strong marks, and one hairline ties the source anchor to
# the target anchor so the eye follows the move.

def _fade(theme, role, alpha):
    r, g, b, _a = theme.color_for(role)
    return (r, g, b, alpha)


def _draw_face_wash(context, theme, face, *, fill, outline, roll=None, roll_shift=0):
    """Faint fill + hairline outline; optional strong roll edge."""
    with draw_scope(blend="ALPHA", depth="LESS_EQUAL", face_culling="NONE", depth_mask=False):
        iops_draw.tris(face["tris"], color=fill, context=context)
    with draw_scope(blend="ALPHA", depth="NONE"):
        iops_draw.edges_3d(face["edges"], color=outline, width="default", context=context)
        if roll is not None:
            a, b, _ = _face_edge(face, roll_shift)
            iops_draw.edges_3d([a, b], color=roll, width="locked", context=context)


def _draw_anchor(context, anchor, normal, length, *, point_role, line_color):
    """Anchor disc with a short normal stub — the face frame reduced to the
    two things that matter: where, and which way it faces."""
    o = Vector(anchor)
    with draw_scope(blend="ALPHA", depth="NONE"):
        if length > 0.0:
            iops_draw.edges_3d([o, o + Vector(normal) * length], color=line_color,
                               width="default", context=context)
        iops_draw.points([o], role=point_role, context=context)


def _draw_ghost(op, context, theme):
    """The selection carried by the current delta: a soft tinted volume
    (back faces culled so overlapping shells don't stack up) with a faint
    wire so the silhouette still reads on flat shading."""
    if op._delta_is_identity():
        return
    tris, edges = op._ghost
    fill = _fade(theme, Role.GHOST_PREVIEW, 0.16)
    wire = _fade(theme, Role.GHOST_PREVIEW, 0.28)
    gpu.matrix.push()
    try:
        gpu.matrix.multiply_matrix(op._delta)
        if tris and len(tris) <= GHOST_FILL_TRI_CAP:
            with draw_scope(blend="ALPHA", depth="LESS_EQUAL", face_culling="BACK", depth_mask=False):
                iops_draw.tris(tris, color=fill, context=context)
        if edges:
            with draw_scope(blend="ALPHA", depth="LESS_EQUAL"):
                iops_draw.edges_3d(edges, color=wire, width="default", context=context)
    finally:
        gpu.matrix.pop()


def _draw_preview_3d(op, context):
    try:
        length = op._gizmo_len
    except AttributeError:
        return
    theme = get_theme(context)
    _draw_ghost(op, context, theme)

    if op.mode == MODE_FACE:
        hv = op._hover
        sf = op._src_frame
        landed = not op._delta_is_identity()
        show_edge = op.rot_mode == ROT_EDGE
        show_normal = op.rot_mode != ROT_KEEP
        if op._src_face is not None and sf is not None and not landed:
            # source at rest: faint amber wash + anchor; normal stub / roll
            # edge only when the move actually uses them
            _draw_face_wash(context, theme, op._src_face,
                            fill=_fade(theme, Role.LOCKED_LINE, 0.12),
                            outline=_fade(theme, Role.LOCKED_LINE, 0.6),
                            roll=_fade(theme, Role.LOCKED_LINE, 0.9) if show_edge else None)
            _draw_anchor(context, sf.origin, sf.primary, length * 0.6 if show_normal else 0.0,
                         point_role=Role.LOCKED_POINT,
                         line_color=_fade(theme, Role.LOCKED_LINE, 0.9))
        if hv is not None and not op._hover_is_source:
            anchor = op._hover_point()
            _draw_face_wash(context, theme, hv,
                            fill=_fade(theme, Role.GHOST_DEFAULT, 0.10),
                            outline=_fade(theme, Role.ACTIVE_LINE, 0.55),
                            roll=_fade(theme, Role.CLOSEST_LINE, 0.95) if show_edge else None,
                            roll_shift=op.roll_shift)
            with draw_scope(blend="ALPHA", depth="NONE"):
                if op.snap:
                    others = [p for p in hv["snaps"] if (p - anchor).length > 1e-9]
                    if others:
                        iops_draw.points(others, color=_fade(theme, Role.POINT, 0.35),
                                         size=4.0, context=context)
            if op._dst_frame is not None:
                _draw_anchor(context, anchor, hv["normal"], length * 0.6 if show_normal else 0.0,
                             point_role=Role.CLOSEST_POINT,
                             line_color=_fade(theme, Role.ACTIVE_LINE, 0.9))
                if sf is not None:
                    # flight line: source anchor at rest -> target anchor
                    with draw_scope(blend="ALPHA", depth="NONE"):
                        iops_draw.edges_3d([Vector(sf.origin), Vector(anchor)],
                                           color=_fade(theme, Role.PREVIEW_LINE, 0.45),
                                           width="default", context=context)
            else:
                with draw_scope(blend="ALPHA", depth="NONE"):
                    iops_draw.points([anchor], role=Role.CLOSEST_POINT, context=context)
        return

    # AIM
    hv = op._hover
    if hv is not None:
        anchor = op._hover_point()
        _draw_face_wash(context, theme, hv,
                        fill=_fade(theme, Role.GHOST_DEFAULT, 0.10),
                        outline=_fade(theme, Role.ACTIVE_LINE, 0.55))
        with draw_scope(blend="ALPHA", depth="NONE"):
            if op.snap:
                others = [p for p in hv["snaps"] if (p - anchor).length > 1e-9]
                if others:
                    iops_draw.points(others, color=_fade(theme, Role.POINT, 0.35),
                                     size=4.0, context=context)
            iops_draw.points([anchor], role=Role.CLOSEST_POINT, context=context)
    pivot = Vector(op.pivot)
    pts_locked = [Vector(p) for p in op.targets]
    with draw_scope(blend="ALPHA", depth="NONE"):
        for i, p in enumerate(op._aim_targets()):
            if p is None:
                continue
            letter = _letter(op.primary_axis if i == 0 else op.secondary_axis)
            r, g, b, _ = axis_color(letter)
            alpha = 0.9 if i < len(pts_locked) else 0.5
            iops_draw.edges_3d([pivot, Vector(p)], color=(r, g, b, alpha),
                               width="default", context=context)
        if pts_locked:
            iops_draw.points(pts_locked, role=Role.LOCKED_POINT, context=context)
        iops_draw.points([pivot], role=Role.PIVOT, context=context)
    if op._dst_frame is not None:
        # the object's actual local axes at the pivot after the delta
        rot = (op._delta @ op._orig_active).to_3x3()
        main = {_letter(op.primary_axis), _letter(op.secondary_axis)}
        with draw_scope(blend="ALPHA", depth="NONE"):
            for i, letter in enumerate(AXIS_LETTERS):
                d = Vector((rot[0][i], rot[1][i], rot[2][i])).normalized()
                L = length if letter in main else length * 0.5
                r, g, b, _ = axis_color(letter)
                iops_draw.edges_3d([pivot, pivot + d * L],
                                   color=(r, g, b, 0.9 if letter in main else 0.45),
                                   width="axis_gizmo", context=context)


def _draw_pixel(op, context):
    if op.mode == MODE_AIM:
        region = context.region
        rv3d = context.region_data
        if region is not None and rv3d is not None:
            theme = get_theme(context)
            for i, p in enumerate(op._aim_targets()):
                if p is None:
                    continue
                tok = op.primary_axis if i == 0 else op.secondary_axis
                p2 = location_3d_to_region_2d(region, rv3d, Vector(p))
                if p2 is None:
                    continue
                r, g, b, _ = axis_color(_letter(tok))
                w, h = hud_text.measure(tok, theme=theme, size_token="axis_letter")
                hud_text.draw(tok, int(p2.x - w * 0.5), int(p2.y + h * 0.8),
                              theme=theme, color=(r, g, b, 1.0), size_token="axis_letter")
    for ov in (op._help, op._hud):
        if ov is not None:
            ov.draw(context, op._last_event)


# --- operator -------------------------------------------------------------

class IOPS_OT_ThreePointRotation(bpy.types.Operator):
    """Land a face of the selection on any face in the scene (hover your
    object for the source, hover the target, click), or aim its axes at
    picked points. A ghost previews the result; originals move on confirm"""

    bl_idname = "iops.object_modal_three_point_rotation"
    is_bindable = True
    bl_label = "OBJECT: Three Point Rotation"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (
            context.mode == "OBJECT"
            and context.area is not None
            and context.area.type == "VIEW_3D"
            and context.active_object is not None
        )

    # --- state helpers ---

    def _reset_picks(self):
        self.targets = []            # AIM: locked world points (A, B)
        self._src_face = None        # FACE: sticky source face dict
        self._src_frame = None
        self._hover = None
        self._hover_is_source = False
        self._aim_hover_pt = None
        self._dst_frame = None
        self._delta = Matrix.Identity(4)
        self._error = ""
        self.roll_shift = 0
        self._dst_anchor = None

    def _delta_is_identity(self):
        m = self._delta
        return all(abs(m[i][j] - (1.0 if i == j else 0.0)) < 1e-9 for i in range(4) for j in range(4))

    def _hover_point(self):
        hv = self._hover
        if hv is None:
            return None
        return hv["closest"] if self.snap else hv["hit"]

    def _aim_targets(self):
        """(A, B) — locked points, the hover filling the next slot."""
        out = [Vector(p) for p in self.targets]
        if len(out) < 2 and self._aim_hover_pt is not None:
            out.append(Vector(self._aim_hover_pt))
        while len(out) < 2:
            out.append(None)
        return out

    def _step_label(self):
        if self.mode == MODE_FACE:
            if self._src_face is None:
                return "hover your object: pick the source face"
            if self._dst_frame is None:
                return "hover a target face, click to apply"
            return "click to apply"
        n = len(self.targets)
        if n == 0:
            return f"aim {self.primary_axis}: click a point"
        if n == 1:
            return f"roll {self.secondary_axis}: click a point"
        return "Space to apply"

    # --- preview math ---

    def _face_frame(self, face, *, invert_normal=False, shift=0):
        anchor = face["closest"] if self.snap else face["hit"]
        n = -face["normal"] if invert_normal else face["normal"]
        _a, _b, e = _face_edge(face, shift)
        return frame_from_face(tuple(anchor), tuple(n), tuple(e))

    def _face_delta(self, src, hv):
        """World delta for the Face mode according to `rot_mode`. Returns
        (delta, dst_frame_or_None)."""
        anchor = Vector(hv["closest"] if self.snap else hv["hit"])
        o = Vector(src.origin)
        if self.rot_mode == ROT_KEEP:
            return Matrix.Translation(anchor - o), None
        n_src = Vector(src.primary)
        n_dst = (-hv["normal"] if self.face_to_face else hv["normal"]).normalized()
        if self.rot_mode == ROT_NORMAL:
            # minimal rotation n_src -> n_dst; antiparallel is ambiguous, so
            # fold about the source roll edge (lid on a box) to stay stable
            if n_src.dot(n_dst) < -0.99999:
                rot = Matrix.Rotation(3.141592653589793, 4, Vector(src.secondary))
            else:
                rot = n_src.rotation_difference(n_dst).to_matrix().to_4x4()
            delta = Matrix.Translation(anchor) @ rot @ Matrix.Translation(-o)
            r3 = rot.to_3x3()
            dst = frame_from_face(tuple(anchor), tuple(n_dst), tuple(r3 @ Vector(src.secondary)))
            return delta, dst
        dst = self._face_frame(hv, invert_normal=self.face_to_face, shift=self.roll_shift)
        return _tuple_matrix(align_matrix(src, dst)), dst

    def _update(self):
        """Recompute the target frame from the current picks, then the delta
        the ghost is drawn with."""
        self._error = ""
        self._dst_frame = None
        self._delta = Matrix.Identity(4)
        try:
            if self.mode == MODE_FACE:
                src = self._src_frame
                hv = self._hover
                if src is None or hv is None or self._hover_is_source:
                    return
                self._delta, dst = self._face_delta(src, hv)
                # Face mode is "armed" once a target is hovered, whatever the
                # rotation mode — the click test reads _dst_frame
                self._dst_frame = dst if dst is not None else src
                return
            else:
                src = axis_frame(self._orig_active, self.primary_axis, self.secondary_axis,
                                 pivot=tuple(self.pivot))
                a, b = self._aim_targets()
                if a is None:
                    return
                try:
                    dst = frame_from_points(tuple(self.pivot), tuple(a),
                                            None if b is None else tuple(b),
                                            secondary_hint=src.secondary)
                except DegenerateFrame as exc:
                    if b is None:
                        raise
                    # B on the aim line: keep the two-point aim, flag it
                    self._error = str(exc)
                    dst = frame_from_points(tuple(self.pivot), tuple(a), None,
                                            secondary_hint=src.secondary)
            self._dst_frame = dst
            self._delta = _tuple_matrix(align_matrix(src, dst))
        except DegenerateFrame as exc:
            self._error = str(exc)
            self._delta = Matrix.Identity(4)

    def _apply(self):
        for ob, mw in self._orig.items():
            try:
                ob.matrix_world = self._delta @ mw
            except ReferenceError:
                continue

    def _update_hover(self, context, event):
        mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        self._aim_hover_pt = None
        self._hover_is_source = False
        if self.mode == MODE_FACE:
            face = _pick_face(context, mouse)
            self._hover = face
            if face is not None and face["owner"] in self._moving:
                # sticky source: follows the cursor while on the object
                self._hover_is_source = True
                self._src_face = face
                self._src_frame = self._face_frame(face)
                self.roll_shift = 0
            return
        if len(self.targets) >= 2:
            self._hover = None
            return
        self._hover = _pick_face(context, mouse, exclude=self._moving)
        if self._hover is not None:
            self._aim_hover_pt = self._hover_point()
        else:
            self._aim_hover_pt = _mouse_on_view_plane(context, mouse, Vector(self.pivot))

    # --- HUD ---

    def _build_hud(self, context):
        hud = HUDOverlay("three_point_rotation")
        hud.title = "3 Point Rotation"
        hud.bind_region(context.region)
        hud.add_param(HUDParam("Mode", lambda: MODE_LABELS[self.mode], "str"))
        hud.add_param(HUDParam("Step", lambda: self._step_label(), "str"))
        hud.add_param(HUDParam("Axes", lambda: f"{self.primary_axis} → {self.secondary_axis}", "str",
                               visible_getter=lambda: self.mode == MODE_AIM))
        hud.add_param(HUDParam("Rotate", lambda: ROT_LABELS[self.rot_mode], "str",
                               visible_getter=lambda: self.mode == MODE_FACE))
        hud.add_param(HUDParam("Facing", lambda: "face to face" if self.face_to_face else "same side", "str",
                               visible_getter=lambda: self.mode == MODE_FACE and self.rot_mode != ROT_KEEP))
        hud.add_param(HUDParam("Roll edge", lambda: self._roll_label(), "str",
                               visible_getter=lambda: self.mode == MODE_FACE and self.rot_mode == ROT_EDGE))
        hud.add_param(HUDParam("Snap", lambda: self.snap, "bool"))
        hud.add_param(HUDParam("Rotation", lambda: f"{rotation_angle_deg(self._delta):.1f}°", "str"))
        hud.add_param(HUDParam("Error", lambda: self._error, "str",
                               visible_getter=lambda: bool(self._error)))
        return hud

    def _roll_label(self):
        return "nearest" if self.roll_shift == 0 else f"nearest {self.roll_shift:+d}"

    def _build_help(self, context):
        helpo = HelpOverlay("three_point_rotation")
        helpo.add_section(HUDSection("3 Point Rotation", [
            HUDItem("Face: apply on target face  /  Aim: lock point", "LMB", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Pick pivot on the object (Aim)", "Shift+LMB", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Mode: Face to face / Aim axes", "Tab", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Rotation: keep / match normals / normals + edge (Face)", "R", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Facing: meet / same side (Face, rotating)", "F", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Roll edge: next / previous (Face, edge)", "Alt+Wheel", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Primary axis (repeat flips) (Aim)", "X / Y / Z", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Secondary axis (repeat flips) (Aim)", "Shift+X / Y / Z", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Snap to verts / edge mids / center", "S", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Undo last point (Aim)", "Backspace", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Reset", "0", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Apply", "Space / Enter", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Cancel", "Esc / RMB", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Help / HUD", "H", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        ]))
        helpo.bind_region(context.region)
        return helpo

    # --- lifecycle ---

    def invoke(self, context, event):
        active = context.active_object
        if active is None:
            self.report({"WARNING"}, "No active object")
            return {"CANCELLED"}
        selected = list(context.selected_objects)
        if active not in selected:
            selected.append(active)
        roots = _roots(selected)
        self._moving = set(roots)
        for r in roots:
            self._moving.update(r.children_recursive)
        self._orig = {ob: ob.matrix_world.copy() for ob in roots}
        self._orig_active = active.matrix_world.copy()
        self._ghost = _gather_ghost(context, self._moving)

        self.mode = MODE_FACE
        self.primary_axis = "Z"
        self.secondary_axis = "Y"
        self.snap = True
        self.face_to_face = True
        self.rot_mode = ROT_KEEP
        self.pivot = active.matrix_world.translation.copy()
        dims = [d for d in active.dimensions if d > 1e-6]
        self._gizmo_len = max(dims) * 0.35 if dims else 1.0
        self._reset_picks()

        self._hud = self._build_hud(context)
        self._help = self._build_help(context)
        self._last_event = capture_event(event, None)
        self._handle = safe_handler_add(
            bpy.types.SpaceView3D, _draw_pixel, (self, context),
            "WINDOW", "POST_PIXEL", tick=True)
        self._handle_3d = safe_handler_add(
            bpy.types.SpaceView3D, _draw_preview_3d, (self, context),
            "WINDOW", "POST_VIEW", tick=False)
        self._update_hover(context, event)
        self._update()
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def _cleanup(self):
        for attr in ("_handle", "_handle_3d"):
            h = getattr(self, attr, None)
            if h is not None:
                safe_handler_remove(h, bpy.types.SpaceView3D, "WINDOW")
                setattr(self, attr, None)

    def _finish(self):
        self._apply()
        self._cleanup()
        self.report({"INFO"}, f"3 Point Rotation: {rotation_angle_deg(self._delta):.1f}°")
        return {"FINISHED"}

    def _set_axis(self, letter, *, secondary):
        cur = self.secondary_axis if secondary else self.primary_axis
        other = self.primary_axis if secondary else self.secondary_axis
        new = _flip_axis(cur) if _letter(cur) == letter else letter
        if _letter(other) == letter:
            # the other slot must move off this axis
            other = next(a for a in AXIS_LETTERS if a not in (letter, _letter(cur)))
        if secondary:
            self.secondary_axis, self.primary_axis = new, other
        else:
            self.primary_axis, self.secondary_axis = new, other

    def modal(self, context, event):
        context.area.tag_redraw()
        self._last_event = capture_event(event, self._last_event)

        try:
            theme_prefs = context.preferences.addons["InteractionOps"].preferences.iops_theme
        except (KeyError, AttributeError):
            theme_prefs = None
        if theme_prefs is not None:
            for ov in (self._help, self._hud):
                if ov.handle_drag_event(context, event, theme_prefs):
                    return {"RUNNING_MODAL"}
            if self._help.handle_toggle_event(event, theme_prefs):
                return {"RUNNING_MODAL"}
            if self._hud.handle_param_toggle_event(event, theme_prefs):
                return {"RUNNING_MODAL"}

        if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            if event.alt and self.mode == MODE_FACE:
                if self.rot_mode != ROT_EDGE:
                    self.rot_mode = ROT_EDGE
                else:
                    self.roll_shift += 1 if event.type == "WHEELUPMOUSE" else -1
                self._update()
                return {"RUNNING_MODAL"}
            return {"PASS_THROUGH"}
        if event.type in {"MIDDLEMOUSE", "TRACKPADPAN", "TRACKPADZOOM"}:
            return {"PASS_THROUGH"}

        if event.type == "MOUSEMOVE":
            self._update_hover(context, event)
            self._update()
            return {"RUNNING_MODAL"}

        if event.value != "PRESS":
            return {"RUNNING_MODAL"}

        if event.type == "LEFTMOUSE":
            if self.mode == MODE_FACE:
                if self._dst_frame is not None:
                    return self._finish()
                return {"RUNNING_MODAL"}
            if event.shift:
                mouse = Vector((event.mouse_region_x, event.mouse_region_y))
                face = _pick_face(context, mouse, restrict_to=self._moving)
                if face is not None:
                    self.targets = []
                    self.pivot = (face["closest"] if self.snap else face["hit"]).copy()
            elif len(self.targets) < 2 and self._aim_hover_pt is not None:
                self.targets.append(Vector(self._aim_hover_pt))
            self._update_hover(context, event)
            self._update()
        elif event.type == "BACK_SPACE":
            if self.mode == MODE_AIM and self.targets:
                self.targets.pop()
                self._update_hover(context, event)
                self._update()
        elif event.type == "TAB":
            self.mode = MODE_AIM if self.mode == MODE_FACE else MODE_FACE
            self._reset_picks()
            self._update_hover(context, event)
            self._update()
        elif event.type in AXIS_LETTERS and not (event.ctrl or event.alt):
            if self.mode == MODE_AIM:
                self._set_axis(event.type, secondary=event.shift)
                self._update()
        elif event.type == "F":
            if self.mode == MODE_FACE:
                self.face_to_face = not self.face_to_face
            elif len(self.targets) == 2:
                self.targets.reverse()
            self._update()
        elif event.type == "R" and self.mode == MODE_FACE:
            i = ROT_CYCLE.index(self.rot_mode)
            self.rot_mode = ROT_CYCLE[(i + 1) % len(ROT_CYCLE)]
            self._update()
        elif event.type == "S":
            self.snap = not self.snap
            self._update_hover(context, event)
            self._update()
        elif event.type in {"ZERO", "NUMPAD_0"}:
            self.pivot = self._orig_active.translation.copy()
            self.primary_axis, self.secondary_axis = "Z", "Y"
            self.face_to_face, self.rot_mode = True, ROT_KEEP
            self._reset_picks()
            self._update_hover(context, event)
            self._update()
        elif event.type in {"SPACE", "RET", "NUMPAD_ENTER"}:
            return self._finish()
        elif event.type in {"ESC", "RIGHTMOUSE"}:
            self._cleanup()
            return {"CANCELLED"}

        return {"RUNNING_MODAL"}
