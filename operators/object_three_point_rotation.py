"""Three Point Rotation — aim an object's axes at picked points, or land a
face of it onto any face in the scene. The object itself is the preview:
every hover recomputes the rigid delta and writes matrix_world live; a click
only locks the current pick. No helper objects, no constraints, no
tool-settings changes, one undo step.

Modes (Tab):
  AIM   pivot = object origin (Shift+LMB picks another point on the object);
        hover aims the primary local axis at the point under the cursor,
        click locks it; hover then rolls the secondary axis, click locks.
  FACE  click a face on the selected object(s) → source frame; hovering any
        other face carries the object there (anchor = snap point under the
        cursor, roll = nearest edge), click locks.
"""
import bpy
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
from ..utils.picking import raycast_from_mouse
from ..utils.three_point_core import (
    Frame, DegenerateFrame, frame_from_points, frame_from_face, axis_frame,
    align_matrix, rotation_angle_deg,
)


MODE_AIM = "AIM"
MODE_FACE = "FACE"
MODE_LABELS = {MODE_AIM: "Aim axes", MODE_FACE: "Face to face"}

AXIS_LETTERS = ("X", "Y", "Z")


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


# --- hover picking (one primitive for both modes) -------------------------

def _pick_face(context, mouse, *, restrict_to=None, exclude=None):
    """Raycast under the cursor and describe the hit face in world space:
    dict(hit, obj, normal, center, verts, mids, snaps, closest, edge_dir,
    tris, edges) or None on miss."""
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
    closest = min(snaps, key=lambda p: (p - loc).length)
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
    edge_dir = (vw[(best_i + 1) % n] - vw[best_i])
    if edge_dir.length < 1e-9:
        edge_dir = Vector((1, 0, 0))
    tris = []
    for i in range(1, n - 1):
        tris.extend([vw[0], vw[i], vw[i + 1]])
    edges = []
    for i in range(n):
        edges.extend([vw[i], vw[(i + 1) % n]])
    return {
        "hit": loc, "obj": obj, "normal": normal.normalized(),
        "center": center, "verts": vw, "snaps": snaps, "closest": closest,
        "edge_dir": edge_dir.normalized(), "edge": (vw[best_i], vw[(best_i + 1) % n]),
        "tris": tris, "edges": edges,
    }


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

def _draw_hover(op, context):
    hv = op._hover
    if not hv:
        return
    with draw_scope(blend="ALPHA", depth="LESS_EQUAL", face_culling="NONE", depth_mask=False):
        iops_draw.tris(hv["tris"], role=Role.GHOST_DEFAULT, context=context)
    with draw_scope(blend="ALPHA", depth="LESS_EQUAL"):
        iops_draw.edges_3d(hv["edges"], role=Role.GHOST_EDGE, context=context)
    with draw_scope(blend="ALPHA", depth="NONE"):
        if op.mode == MODE_FACE:
            iops_draw.edges_3d(list(hv["edge"]), role=Role.CLOSEST_LINE, context=context)
        if op.snap:
            iops_draw.points(hv["snaps"], role=Role.PREVIEW_POINT, context=context)
        iops_draw.points([op._hover_point()], role=Role.CLOSEST_POINT, context=context)


def _draw_frame(context, frame: Frame, length, *, roles):
    o = Vector(frame.origin)
    dirs = (frame.primary, frame.secondary, frame.tertiary)
    with draw_scope(blend="ALPHA", depth="NONE"):
        for i, d in enumerate(dirs):
            tip = o + Vector(d) * (length if i < 2 else length * 0.5)
            iops_draw.edges_3d([o, tip], role=roles[i], width="axis_gizmo", context=context)


def _draw_preview_3d(op, context):
    try:
        length = op._gizmo_len
    except AttributeError:
        return
    _draw_hover(op, context)

    if op.mode == MODE_AIM:
        pivot = Vector(op.pivot)
        pts_locked = [Vector(p) for p in op.targets]
        tgt = op._aim_targets()
        # lines pivot → A / B in the color of the local axis they aim
        with draw_scope(blend="ALPHA", depth="NONE"):
            for i, p in enumerate(tgt):
                if p is None:
                    continue
                letter = _letter(op.primary_axis if i == 0 else op.secondary_axis)
                r, g, b, _ = axis_color(letter)
                alpha = 1.0 if i < len(pts_locked) else 0.6
                iops_draw.edges_3d([pivot, Vector(p)], color=(r, g, b, alpha),
                                   width="axis_gizmo", context=context)
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
                    iops_draw.edges_3d([pivot, pivot + d * L], color=(r, g, b, 0.9),
                                       width="axis_gizmo", context=context)
    else:
        if op._src_face is not None:
            # source face ghost carried by the current delta — shows it landing
            d = op._delta
            tris = [d @ v for v in op._src_face["tris"]]
            edges = [d @ v for v in op._src_face["edges"]]
            with draw_scope(blend="ALPHA", depth="NONE", face_culling="NONE", depth_mask=False):
                iops_draw.tris(tris, role=Role.GHOST_LOCKED, context=context)
                iops_draw.edges_3d(edges, role=Role.LOCKED_LINE, context=context)
            sf = op._src_frame
            if sf is not None:
                moved = Frame(tuple(d @ Vector(sf.origin)),
                              tuple(d.to_3x3() @ Vector(sf.primary)),
                              tuple(d.to_3x3() @ Vector(sf.secondary)),
                              tuple(d.to_3x3() @ Vector(sf.tertiary)))
                _draw_frame(context, moved, length,
                            roles=(Role.LOCKED_LINE, Role.LOCKED_LINE, Role.PREVIEW_LINE))
        if op._dst_frame is not None:
            _draw_frame(context, op._dst_frame, length,
                        roles=(Role.ACTIVE_LINE, Role.ACTIVE_LINE, Role.PREVIEW_LINE))


def _draw_pixel(op, context):
    # axis letters at the tips of the aim lines
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
    """Aim the object's axes at picked points, or land one of its faces on
    any face in the scene. Live preview: the object follows the cursor,
    clicks only lock the picks"""

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
        self._src_face = None        # FACE: locked source face dict
        self._src_frame = None
        self._dst_locked = None      # FACE: locked target frame
        self._hover = None
        self._dst_frame = None
        self._delta = Matrix.Identity(4)
        self._error = ""
        self._apply_delta()

    def _tertiary_letter(self):
        used = {_letter(self.primary_axis), _letter(self.secondary_axis)}
        return next(a for a in AXIS_LETTERS if a not in used)

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
        if self.mode == MODE_AIM:
            n = len(self.targets)
            if n == 0:
                return f"aim {self.primary_axis}: click a point"
            if n == 1:
                return f"roll {self.secondary_axis}: click a point"
            return "locked — Space to apply"
        if self._src_face is None:
            return "click a face on the object"
        if self._dst_locked is None:
            return "hover a target face, click to lock"
        return "locked — Space to apply"

    # --- preview math ---

    def _source_frame(self):
        if self.mode == MODE_AIM:
            return axis_frame(self._orig_active, self.primary_axis, self.secondary_axis,
                              pivot=tuple(self.pivot))
        return self._src_frame

    def _face_frame(self, face, *, invert_normal=False, reverse_edge=False):
        anchor = face["closest"] if self.snap else face["hit"]
        n = -face["normal"] if invert_normal else face["normal"]
        e = -face["edge_dir"] if reverse_edge else face["edge_dir"]
        return frame_from_face(tuple(anchor), tuple(n), tuple(e))

    def _update(self):
        """Recompute the target frame from locks + hover, then the delta,
        then push it onto the objects."""
        self._error = ""
        self._dst_frame = None
        try:
            src = self._source_frame()
            dst = None
            if self.mode == MODE_AIM:
                a, b = self._aim_targets()
                if a is not None:
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
            else:
                if src is not None:
                    if self._dst_locked is not None:
                        dst = self._dst_locked
                    elif self._hover is not None:
                        dst = self._face_frame(self._hover, invert_normal=self.face_to_face,
                                               reverse_edge=self.reverse_roll)
            if dst is None:
                self._delta = Matrix.Identity(4)
            else:
                self._dst_frame = dst
                self._delta = _tuple_matrix(align_matrix(src, dst))
        except DegenerateFrame as exc:
            self._error = str(exc)
            self._delta = Matrix.Identity(4)
        self._apply_delta()

    def _apply_delta(self):
        for ob, mw in self._orig.items():
            try:
                ob.matrix_world = self._delta @ mw
            except ReferenceError:
                continue

    def _update_hover(self, context, event):
        mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        self._aim_hover_pt = None
        if self.mode == MODE_AIM:
            if len(self.targets) >= 2:
                self._hover = None
            else:
                self._hover = _pick_face(context, mouse, exclude=self._all_selected)
                if self._hover is not None:
                    self._aim_hover_pt = self._hover_point()
                else:
                    self._aim_hover_pt = _mouse_on_view_plane(context, mouse, Vector(self.pivot))
        else:
            if self._src_face is None:
                self._hover = _pick_face(context, mouse, restrict_to=self._all_selected)
            elif self._dst_locked is None:
                self._hover = _pick_face(context, mouse, exclude=self._all_selected)
            else:
                self._hover = None

    # --- HUD ---

    def _build_hud(self, context):
        hud = HUDOverlay("three_point_rotation")
        hud.title = "3 Point Rotation"
        hud.bind_region(context.region)
        hud.add_param(HUDParam("Mode", lambda: MODE_LABELS[self.mode], "str"))
        hud.add_param(HUDParam("Step", lambda: self._step_label(), "str"))
        hud.add_param(HUDParam("Axes", lambda: f"{self.primary_axis} → {self.secondary_axis}", "str",
                               visible_getter=lambda: self.mode == MODE_AIM))
        hud.add_param(HUDParam("Facing", lambda: "face to face" if self.face_to_face else "same side", "str",
                               visible_getter=lambda: self.mode == MODE_FACE))
        hud.add_param(HUDParam("Roll", lambda: "reversed" if self.reverse_roll else "edge", "str",
                               visible_getter=lambda: self.mode == MODE_FACE))
        hud.add_param(HUDParam("Snap", lambda: self.snap, "bool"))
        hud.add_param(HUDParam("Rotation", lambda: f"{rotation_angle_deg(self._delta):.1f}°", "str"))
        hud.add_param(HUDParam("Error", lambda: self._error, "str",
                               visible_getter=lambda: bool(self._error)))
        return hud

    def _build_help(self, context):
        helpo = HelpOverlay("three_point_rotation")
        helpo.add_section(HUDSection("3 Point Rotation", [
            HUDItem("Lock pick (aim point / face)", "LMB", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Pick pivot on the object (Aim)", "Shift+LMB", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Mode: Aim axes / Face to face", "Tab", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Primary axis (repeat flips)", "X / Y / Z", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Secondary axis (repeat flips)", "Shift+X / Y / Z", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Flip: swap A/B (Aim) / facing (Face)", "F", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Reverse roll 180° (Face)", "R", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Snap to verts / edge mids / center", "S", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Undo last pick", "Backspace", ItemState.ON, default_state=ItemState.OFF, always_show=True),
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
        self._all_selected = set(selected)
        self._orig = {ob: ob.matrix_world.copy() for ob in _roots(selected)}
        self._orig_active = active.matrix_world.copy()

        self.mode = MODE_AIM
        self.primary_axis = "Z"
        self.secondary_axis = "Y"
        self.snap = True
        self.face_to_face = True
        self.reverse_roll = False
        self.pivot = active.matrix_world.translation.copy()
        self._aim_hover_pt = None
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

    def _restore(self):
        self._delta = Matrix.Identity(4)
        self._apply_delta()

    def _lock(self):
        if self.mode == MODE_AIM:
            if len(self.targets) >= 2 or self._aim_hover_pt is None:
                return
            self.targets.append(Vector(self._aim_hover_pt))
        else:
            if self._hover is None:
                return
            if self._src_face is None:
                self._src_face = self._hover
                self._src_frame = self._face_frame(self._hover)
            elif self._dst_locked is None:
                self._dst_locked = self._face_frame(self._hover, invert_normal=self.face_to_face,
                                                    reverse_edge=self.reverse_roll)

    def _unlock(self):
        if self.mode == MODE_AIM:
            if self.targets:
                self.targets.pop()
        else:
            if self._dst_locked is not None:
                self._dst_locked = None
            elif self._src_face is not None:
                self._src_face = None
                self._src_frame = None

    def _set_axis(self, letter, *, secondary):
        cur = self.secondary_axis if secondary else self.primary_axis
        other = self.primary_axis if secondary else self.secondary_axis
        new = _flip_axis(cur) if _letter(cur) == letter else letter
        if _letter(other) == letter:
            # the other slot must move off this axis
            free = next(a for a in AXIS_LETTERS if a not in (letter, _letter(cur)))
            other = free
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

        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE",
                          "TRACKPADPAN", "TRACKPADZOOM"}:
            return {"PASS_THROUGH"}

        if event.type == "MOUSEMOVE":
            self._update_hover(context, event)
            self._update()
            return {"RUNNING_MODAL"}

        if event.value != "PRESS":
            return {"RUNNING_MODAL"}

        if event.type == "LEFTMOUSE":
            if event.shift and self.mode == MODE_AIM:
                # pivot pick: resets picks so the object is at its original
                # placement while we raycast it
                self.targets = []
                self._delta = Matrix.Identity(4)
                self._apply_delta()
                mouse = Vector((event.mouse_region_x, event.mouse_region_y))
                face = _pick_face(context, mouse, restrict_to=self._all_selected)
                if face is not None:
                    self.pivot = (face["closest"] if self.snap else face["hit"]).copy()
            else:
                self._lock()
            self._update_hover(context, event)
            self._update()
        elif event.type == "BACK_SPACE":
            self._unlock()
            self._update_hover(context, event)
            self._update()
        elif event.type == "TAB":
            self.mode = MODE_FACE if self.mode == MODE_AIM else MODE_AIM
            self._reset_picks()
            self._update_hover(context, event)
            self._update()
        elif event.type in AXIS_LETTERS and not (event.ctrl or event.alt):
            if self.mode == MODE_AIM:
                self._set_axis(event.type, secondary=event.shift)
                self._update()
        elif event.type == "F":
            if self.mode == MODE_AIM:
                if len(self.targets) == 2:
                    self.targets.reverse()
            else:
                self.face_to_face = not self.face_to_face
                if self._dst_locked is not None:
                    # relock from the stored frame: invert primary, keep anchor
                    f = self._dst_locked
                    self._dst_locked = frame_from_face(f.origin, tuple(-Vector(f.primary)), f.secondary)
            self._update()
        elif event.type == "R" and self.mode == MODE_FACE:
            self.reverse_roll = not self.reverse_roll
            if self._dst_locked is not None:
                f = self._dst_locked
                self._dst_locked = frame_from_face(f.origin, f.primary, tuple(-Vector(f.secondary)))
            self._update()
        elif event.type == "S":
            self.snap = not self.snap
            self._update_hover(context, event)
            self._update()
        elif event.type in {"ZERO", "NUMPAD_0"}:
            self.pivot = self._orig_active.translation.copy()
            self.primary_axis, self.secondary_axis = "Z", "Y"
            self.face_to_face, self.reverse_roll = True, False
            self._reset_picks()
            self._update_hover(context, event)
            self._update()
        elif event.type in {"SPACE", "RET", "NUMPAD_ENTER"}:
            self._cleanup()
            self.report({"INFO"}, f"3 Point Rotation: {rotation_angle_deg(self._delta):.1f}°")
            return {"FINISHED"}
        elif event.type in {"ESC", "RIGHTMOUSE"}:
            self._restore()
            self._cleanup()
            return {"CANCELLED"}

        return {"RUNNING_MODAL"}
