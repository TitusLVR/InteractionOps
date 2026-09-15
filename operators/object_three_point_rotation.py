"""Three Point Rotation — place the selection by point pairs, one click per
step. The originals stay put; a themed ghost shows the result live and the
click commits the step. No helper objects, no constraints, no tool-settings
changes, one undo step.

  1 Move   hover your object → point A (sticky), hover the target → A′,
           LMB: the ghost moves A onto A′. No rotation.
  2 Align  hover your object → point B (shown on the ghost), hover the
           target → B′, LMB: rotate about A′ so the ray A′→B lies on A′→B′.
           R instead turns by the face normals of A / A′ (F flips facing).
  3 Roll   third pair C → C′: turn about the axis A′→B′. LMB finishes.

Space / Enter applies at any step, Backspace steps back, Esc cancels.
"""
import bpy
import gpu
from mathutils import Vector, Matrix
from bpy_extras.view3d_utils import (
    location_3d_to_region_2d, region_2d_to_origin_3d, region_2d_to_vector_3d,
)

from ..ui.draw import primitives as iops_draw
from ..ui.draw import draw_scope, safe_handler_add, safe_handler_remove
from ..ui.draw.theme import get_theme, Role
from ..ui.hud import (HUDOverlay, HelpOverlay, HUDSection, HUDItem,
                      HUDParam, ItemState, capture_event)
from ..utils.picking import raycast_from_mouse, hit_owner, SNAP_THRESHOLD_PX
from ..utils.three_point_core import (
    DegenerateFrame, frame_from_face, align_matrix, rotation_angle_deg,
    rotate_ray_onto, roll_about_axis,
)


STEP_MOVE, STEP_ALIGN, STEP_ROLL, STEP_DONE = 0, 1, 2, 3
STEP_NAMES = {STEP_MOVE: "1 Move", STEP_ALIGN: "2 Align", STEP_ROLL: "3 Roll", STEP_DONE: "Done"}

# Align step: manual point pair, or automatic by the faces of A / A′.
ROT_POINTS = "POINTS"
ROT_NORMAL = "NORMAL"
ROT_EDGE = "EDGE"
ROT_CYCLE = (ROT_POINTS, ROT_NORMAL, ROT_EDGE)
ROT_LABELS = {ROT_POINTS: "by points", ROT_NORMAL: "by normals", ROT_EDGE: "normals + edge"}

GHOST_FILL_TRI_CAP = 400_000     # above this the ghost is edges only


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
            # a mirrored instance (negative determinant) flips the winding;
            # swap two corners so back-face culling still hides the inside
            flip = mw.to_3x3().determinant() < 0.0
            i1, i2 = (2, 1) if flip else (1, 2)
            for lt in me.loop_triangles:
                tris.append(vw[loops[lt.loops[0]].vertex_index])
                tris.append(vw[loops[lt.loops[i1]].vertex_index])
                tris.append(vw[loops[lt.loops[i2]].vertex_index])
            for e in me.edges:
                edges.append(vw[e.vertices[0]])
                edges.append(vw[e.vertices[1]])
        except (RuntimeError, ReferenceError, IndexError):
            continue
    return tris, edges


# --- hover picking ---------------------------------------------------------

def _pick_face(context, mouse, *, restrict_to=None, exclude=None, xform=None):
    """Raycast under the cursor and describe the hit face in world space.
    The snap point is chosen in screen space: a vertex, edge midpoint or the
    center when within SNAP_THRESHOLD_PX of the cursor, else the center.

    `xform` picks geometry that is *displayed* through that rigid matrix (the
    ghost): the mouse ray is cast through its inverse at the originals, the
    returned coordinates stay in original space, and screen distances are
    measured where the ghost is. `depth` is the hit distance along the mouse
    ray in display space, for choosing between overlapping picks.
    Returns a dict or None on miss."""
    region = context.region
    rv3d = context.region_data
    if region is None or rv3d is None:
        return None
    origin = region_2d_to_origin_3d(region, rv3d, mouse)
    direction = region_2d_to_vector_3d(region, rv3d, mouse)
    ray = None
    if xform is not None:
        inv = xform.inverted()
        ray = (inv @ origin, (inv.to_3x3() @ direction).normalized())
    hit, loc, normal, idx, obj, mat = raycast_from_mouse(
        context, mouse, restrict_to=restrict_to, exclude=exclude,
        visible_only=True, region=region, rv3d=rv3d, ray=ray)
    if not hit or obj is None:
        return None
    shown = (lambda p: xform @ p) if xform is not None else (lambda p: p)
    depth = (shown(loc) - origin).dot(direction)
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
    mouse_v = Vector(mouse)
    closest, best = center, SNAP_THRESHOLD_PX
    for p in snaps:
        s = location_3d_to_region_2d(region, rv3d, shown(p))
        if s is None:
            continue
        d = (mouse_v - Vector(s)).length
        if d < best:
            best, closest = d, p
    snapped = best < SNAP_THRESHOLD_PX
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
        "hit": loc, "obj": obj, "owner": owner, "index": idx, "normal": normal.normalized(),
        "center": center, "verts": vw, "snaps": snaps, "closest": closest, "snapped": snapped,
        "edge_idx": best_i, "tris": tris, "edges": edges, "depth": depth,
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


# --- drawing -------------------------------------------------------------
#
# Restraint: only what the decision needs. The ghost is a soft tinted volume,
# faces are a faint wash with a hairline outline, the picked points and the
# committed axis are the only strong marks, and one hairline ties the moving
# point to its target so the eye follows the step.

def _fade(theme, role, alpha):
    r, g, b, _a = theme.color_for(role)
    return (r, g, b, alpha)


def _draw_face_wash(context, face, *, fill, outline, roll=None, roll_shift=0):
    with draw_scope(blend="ALPHA", depth="LESS_EQUAL", face_culling="NONE", depth_mask=False):
        iops_draw.tris(face["tris"], color=fill, context=context)
    with draw_scope(blend="ALPHA", depth="NONE"):
        iops_draw.edges_3d(face["edges"], color=outline, width="default", context=context)
        if roll is not None:
            a, b, _ = _face_edge(face, roll_shift)
            iops_draw.edges_3d([a, b], color=roll, width="locked", context=context)


def _draw_ghost(op, context, theme):
    """The selection carried by the current delta as one translucent shell.

    Depth pre-pass: the front faces are first written to the depth buffer
    with the color masked off, then tinted with an EQUAL depth test. Only
    the nearest surface takes color, so inner walls and overlapping shells
    never stack up and the ghost reads as a solid, however complex."""
    total = op._total()
    if _is_identity(total):
        return
    tris, edges = op._ghost
    fill = _fade(theme, Role.GHOST_PREVIEW, 0.22)
    wire = _fade(theme, Role.GHOST_PREVIEW, 0.30)
    gpu.matrix.push()
    try:
        gpu.matrix.multiply_matrix(total)
        if tris and len(tris) <= GHOST_FILL_TRI_CAP:
            with draw_scope(blend="NONE", depth="LESS_EQUAL", face_culling="BACK",
                            depth_mask=True, color_mask=(False, False, False, False)):
                iops_draw.tris(tris, color=fill, context=context)
            with draw_scope(blend="ALPHA", depth="EQUAL", face_culling="BACK", depth_mask=False):
                iops_draw.tris(tris, color=fill, context=context)
        if edges:
            with draw_scope(blend="ALPHA", depth="LESS_EQUAL"):
                iops_draw.edges_3d(edges, color=wire, width="default", context=context)
    finally:
        gpu.matrix.pop()


def _is_identity(m):
    return all(abs(m[i][j] - (1.0 if i == j else 0.0)) < 1e-9 for i in range(4) for j in range(4))


def _draw_preview_3d(op, context):
    try:
        length = op._gizmo_len
    except AttributeError:
        return
    theme = get_theme(context)
    _draw_ghost(op, context, theme)
    base = op._base
    hv = op._hover
    auto = op.step == STEP_ALIGN and op.rot_mode != ROT_POINTS

    # committed marks: A′ and the A′→B′ axis
    with draw_scope(blend="ALPHA", depth="NONE"):
        if op.a_dst is not None:
            if op.b_dst is not None:
                iops_draw.edges_3d([op.a_dst, op.b_dst], color=_fade(theme, Role.LOCKED_LINE, 0.7),
                                   width="default", context=context)
                iops_draw.points([op.b_dst], color=_fade(theme, Role.LOCKED_POINT, 0.8),
                                 size="default", context=context)
            iops_draw.points([op.a_dst], role=Role.LOCKED_POINT, context=context)

    # sticky source: face wash + point, carried by the committed delta so
    # it sits on the ghost
    if op._src_face is not None and op.step != STEP_DONE:
        gpu.matrix.push()
        try:
            gpu.matrix.multiply_matrix(base)
            _draw_face_wash(context, op._src_face,
                            fill=_fade(theme, Role.LOCKED_LINE, 0.10),
                            outline=_fade(theme, Role.LOCKED_LINE, 0.55),
                            roll=_fade(theme, Role.LOCKED_LINE, 0.9) if (auto and op.rot_mode == ROT_EDGE) else None)
        finally:
            gpu.matrix.pop()
        src_pt = base @ op._src_face["closest"]
        with draw_scope(blend="ALPHA", depth="NONE"):
            if op._src_locked:
                iops_draw.points([src_pt], color=_fade(theme, Role.LOCKED_POINT, 0.35),
                                 size=theme.point_size("locked") + 8.0, context=context)
            if auto:
                n = base.to_3x3() @ op._src_face["normal"]
                iops_draw.edges_3d([src_pt, src_pt + n * length * 0.6],
                                   color=_fade(theme, Role.LOCKED_LINE, 0.9), width="default", context=context)
            iops_draw.points([src_pt], role=Role.LOCKED_POINT, context=context)

    # target hover
    if hv is not None and not op._hover_is_source and op.step != STEP_DONE:
        anchor = op._hover_point()
        _draw_face_wash(context, hv,
                        fill=_fade(theme, Role.GHOST_DEFAULT, 0.10),
                        outline=_fade(theme, Role.ACTIVE_LINE, 0.55),
                        roll=_fade(theme, Role.CLOSEST_LINE, 0.95) if (auto and op.rot_mode == ROT_EDGE) else None,
                        roll_shift=op.roll_shift)
        with draw_scope(blend="ALPHA", depth="NONE"):
            if op.snap:
                others = [p for p in hv["snaps"] if (p - anchor).length > 1e-9]
                if others:
                    iops_draw.points(others, color=_fade(theme, Role.POINT, 0.35), size=4.0, context=context)
            if auto:
                iops_draw.edges_3d([anchor, anchor + hv["normal"] * length * 0.6],
                                   color=_fade(theme, Role.ACTIVE_LINE, 0.9), width="default", context=context)
            iops_draw.points([anchor], role=Role.CLOSEST_POINT, context=context)
            if op._preview is not None and op._src_face is not None and not auto:
                # flight line: the moving point (after the preview) → its target
                moved = op._preview @ base @ op._src_face["closest"]
                start = base @ op._src_face["closest"]
                iops_draw.edges_3d([start, anchor], color=_fade(theme, Role.PREVIEW_LINE, 0.45),
                                   width="default", context=context)
                iops_draw.points([moved], color=_fade(theme, Role.PREVIEW_POINT, 0.9),
                                 size="preview", context=context)


def _draw_pixel(op, context):
    for ov in (op._help, op._hud):
        if ov is not None:
            ov.draw(context, op._last_event)


# --- operator -------------------------------------------------------------

class IOPS_OT_ThreePointRotation(bpy.types.Operator):
    """Place the selection by point pairs: move a point onto a point, then
    optionally align a second pair and roll a third. A ghost previews each
    step; the originals move on confirm"""

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

    # --- state ---

    def _reset(self):
        self.step = STEP_MOVE
        self._base = Matrix.Identity(4)      # committed delta
        self._history = []                   # (base, a_dst, b_dst, a_face) before each commit
        self._preview = None                 # pending step delta (left-multiplies base)
        self.a_dst = None                    # A′ world point (pivot for Align / Roll)
        self.b_dst = None                    # B′ world point (Roll axis end)
        self._a_face = None                  # source face of A (for the auto Align)
        self._a_dst_face = None              # target face of A′
        self._src_face = None                # sticky source pick for the current step
        self._src_locked = False             # LMB on the source froze the pick
        self._hover = None
        self._hover_is_source = False
        self._error = ""
        self.rot_mode = ROT_POINTS
        self.roll_shift = 0

    def _total(self):
        return self._preview @ self._base if self._preview is not None else self._base

    def _hover_point(self):
        hv = self._hover
        if hv is None:
            return None
        return hv["closest"] if self.snap else hv["hit"]

    def _step_label(self):
        if self.step == STEP_DONE:
            return "Space to apply"
        what = {STEP_MOVE: "A", STEP_ALIGN: "B", STEP_ROLL: "C"}[self.step]
        if self.step == STEP_ALIGN and self.rot_mode != ROT_POINTS:
            return "click the target to turn by normals"
        if self._src_face is None:
            return f"hover your object: point {what} (click to lock)"
        state = "locked" if self._src_locked else "sticky"
        return f"{what} {state} — hover the target: {what}′, click"

    # --- preview math ---

    def _face_frame(self, face, *, invert_normal=False, shift=0):
        anchor = face["closest"] if self.snap else face["hit"]
        n = -face["normal"] if invert_normal else face["normal"]
        _a, _b, e = _face_edge(face, shift)
        return frame_from_face(tuple(anchor), tuple(n), tuple(e))

    def _update(self):
        """Recompute the pending step delta from the sticky source and the
        hovered target."""
        self._error = ""
        self._preview = None
        hv = self._hover
        if self.step == STEP_DONE or hv is None or self._hover_is_source:
            return
        target = Vector(self._hover_point())
        try:
            if self.step == STEP_MOVE:
                if self._src_face is None:
                    return
                src = self._src_face["closest"] if self.snap else self._src_face["hit"]
                self._preview = Matrix.Translation(target - src)
            elif self.step == STEP_ALIGN:
                if self.rot_mode == ROT_POINTS:
                    if self._src_face is None:
                        return
                    b_moved = self._base @ (self._src_face["closest"] if self.snap else self._src_face["hit"])
                    self._preview = _tuple_matrix(rotate_ray_onto(
                        tuple(self.a_dst), tuple(b_moved), tuple(target)))
                else:
                    self._preview = self._auto_align(hv)
            elif self.step == STEP_ROLL:
                if self._src_face is None:
                    return
                c_moved = self._base @ (self._src_face["closest"] if self.snap else self._src_face["hit"])
                self._preview = _tuple_matrix(roll_about_axis(
                    tuple(self.a_dst), tuple(self.b_dst - self.a_dst), tuple(c_moved), tuple(target)))
        except DegenerateFrame as exc:
            self._error = str(exc)
            self._preview = None

    def _auto_align(self, hv):
        """Align step by the faces of A (source, carried by the base) and the
        hovered target face, about A′."""
        af = self._a_face
        if af is None:
            raise DegenerateFrame("no source face for A")
        r3 = self._base.to_3x3()
        n_src = (r3 @ af["normal"]).normalized()
        n_dst = (-hv["normal"] if self.face_to_face else hv["normal"]).normalized()
        piv = Vector(self.a_dst)
        if self.rot_mode == ROT_NORMAL:
            if n_src.dot(n_dst) < -0.99999:
                _a, _b, e = _face_edge(af)
                rot = Matrix.Rotation(3.141592653589793, 4, (r3 @ e).normalized())
            else:
                rot = n_src.rotation_difference(n_dst).to_matrix().to_4x4()
            return Matrix.Translation(piv) @ rot @ Matrix.Translation(-piv)
        _a, _b, e_src = _face_edge(af)
        src = frame_from_face(tuple(piv), tuple(n_src), tuple(r3 @ e_src))
        _a, _b, e_dst = _face_edge(hv, self.roll_shift)
        dst = frame_from_face(tuple(piv), tuple(n_dst), tuple(e_dst))
        return _tuple_matrix(align_matrix(src, dst))

    def _lock_source(self):
        """LMB over the source: freeze the pick where the cursor is now.
        Clicking again re-picks and stays locked."""
        if self._hover is None or not self._hover_is_source:
            return False
        self._src_face = self._hover
        self._src_locked = True
        return True

    def _commit(self):
        """LMB: bake the pending preview into the base and advance."""
        if self._preview is None or self._hover is None:
            return False
        target = Vector(self._hover_point())
        self._history.append((self._base.copy(), self.a_dst, self.b_dst, self._a_face, self._a_dst_face))
        self._base = self._preview @ self._base
        self._preview = None
        if self.step == STEP_MOVE:
            self.a_dst = target.copy()
            self._a_face = self._src_face
            self._a_dst_face = self._hover
            self.step = STEP_ALIGN
        elif self.step == STEP_ALIGN:
            if self.rot_mode == ROT_EDGE:
                self.step = STEP_DONE
            else:
                self.b_dst = target.copy() if self.rot_mode == ROT_POINTS else None
                self.step = STEP_ROLL if self.b_dst is not None else STEP_DONE
        elif self.step == STEP_ROLL:
            self.step = STEP_DONE
        self._src_face = None
        self._src_locked = False
        return True

    def _step_back(self):
        if not self._history:
            return
        self._base, self.a_dst, self.b_dst, self._a_face, self._a_dst_face = self._history.pop()
        self.step = {0: STEP_MOVE, 1: STEP_ALIGN, 2: STEP_ROLL}[len(self._history)]
        self._src_face = None
        self._src_locked = False
        self._preview = None

    def _apply(self):
        for ob, mw in self._orig.items():
            try:
                ob.matrix_world = self._base @ mw
            except ReferenceError:
                continue

    def _update_hover(self, context, event):
        mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        self._hover_is_source = False
        if self.step == STEP_DONE:
            self._hover = None
            return
        # Two casts: the scene without the selection (targets), and the
        # selection as displayed — the ghost — via the inverse of the
        # committed delta. Whichever is nearer along the ray wins, so the
        # ghost occludes what it sits on and the originals never pick.
        target = _pick_face(context, mouse, exclude=self._moving)
        source = _pick_face(context, mouse, restrict_to=self._moving, xform=self._base)
        if source is not None and (target is None or source["depth"] <= target["depth"]):
            face = source
        else:
            face = target
        self._hover = face
        if face is source and face is not None:
            # sticky source: follows the cursor while on the object, but on
            # the same face the anchor only moves when the cursor is actually
            # near another snap point — sliding off must not swap a picked
            # vertex for the face center. A click on the source locks it.
            self._hover_is_source = True
            if self._src_locked:
                return
            prev = self._src_face
            same = (prev is not None and prev["owner"] == face["owner"]
                    and prev["index"] == face["index"])
            if same and not face["snapped"]:
                face["closest"] = prev["closest"]
                face["edge_idx"] = prev["edge_idx"]
            self._src_face = face

    # --- HUD ---

    def _build_hud(self, context):
        hud = HUDOverlay("three_point_rotation")
        hud.title = "3 Point Rotation"
        hud.bind_region(context.region)
        hud.add_param(HUDParam("Step", lambda: STEP_NAMES[self.step], "str"))
        hud.add_param(HUDParam("Do", lambda: self._step_label(), "str"))
        hud.add_param(HUDParam("Align", lambda: ROT_LABELS[self.rot_mode], "str",
                               visible_getter=lambda: self.step == STEP_ALIGN))
        hud.add_param(HUDParam("Facing", lambda: "face to face" if self.face_to_face else "same side", "str",
                               visible_getter=lambda: self.step == STEP_ALIGN and self.rot_mode != ROT_POINTS))
        hud.add_param(HUDParam("Roll edge", lambda: "nearest" if self.roll_shift == 0 else f"nearest {self.roll_shift:+d}", "str",
                               visible_getter=lambda: self.step == STEP_ALIGN and self.rot_mode == ROT_EDGE))
        hud.add_param(HUDParam("Snap", lambda: self.snap, "bool"))
        hud.add_param(HUDParam("Rotation", lambda: f"{rotation_angle_deg(self._total()):.1f}°", "str"))
        hud.add_param(HUDParam("Error", lambda: self._error, "str",
                               visible_getter=lambda: bool(self._error)))
        return hud

    def _build_help(self, context):
        helpo = HelpOverlay("three_point_rotation")
        helpo.add_section(HUDSection("3 Point Rotation", [
            HUDItem("On your object: lock the point. On the target: commit the step", "LMB", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Align by: points / normals / normals + edge", "R", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Facing: meet / same side (normals)", "F", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Roll edge: next / previous (normals + edge)", "Alt+Wheel", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Snap to verts / edge mids / center", "S", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Step back", "Backspace", ItemState.ON, default_state=ItemState.OFF, always_show=True),
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
        self._ghost = _gather_ghost(context, self._moving)

        self.snap = True
        self.face_to_face = True
        dims = [d for d in active.dimensions if d > 1e-6]
        self._gizmo_len = max(dims) * 0.35 if dims else 1.0
        self._reset()

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
        if self._preview is not None:
            self._commit()
        self._apply()
        self._cleanup()
        self.report({"INFO"}, f"3 Point Rotation: {rotation_angle_deg(self._base):.1f}°")
        return {"FINISHED"}

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
            if event.alt and self.step == STEP_ALIGN:
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
            if self._hover_is_source:
                # a fresh pick under the cursor, then freeze it
                self._src_locked = False
                self._update_hover(context, event)
                self._lock_source()
            elif self._commit() and self.step == STEP_DONE:
                return self._finish()
            self._update_hover(context, event)
            self._update()
        elif event.type == "BACK_SPACE":
            self._step_back()
            self._update_hover(context, event)
            self._update()
        elif event.type == "R" and self.step == STEP_ALIGN:
            i = ROT_CYCLE.index(self.rot_mode)
            self.rot_mode = ROT_CYCLE[(i + 1) % len(ROT_CYCLE)]
            self._update()
        elif event.type == "F":
            self.face_to_face = not self.face_to_face
            self._update()
        elif event.type == "S":
            self.snap = not self.snap
            self._update_hover(context, event)
            self._update()
        elif event.type in {"ZERO", "NUMPAD_0"}:
            self.face_to_face = True
            self._reset()
            self._update_hover(context, event)
            self._update()
        elif event.type in {"SPACE", "RET", "NUMPAD_ENTER"}:
            return self._finish()
        elif event.type in {"ESC", "RIGHTMOUSE"}:
            self._cleanup()
            return {"CANCELLED"}

        return {"RUNNING_MODAL"}
