import bpy
import bmesh
import math
import gpu
import blf
from gpu_extras.batch import batch_for_shader
from bpy_extras import view3d_utils


DIGIT_TYPES = {
    "ZERO": "0", "ONE": "1", "TWO": "2", "THREE": "3", "FOUR": "4",
    "FIVE": "5", "SIX": "6", "SEVEN": "7", "EIGHT": "8", "NINE": "9",
    "NUMPAD_0": "0", "NUMPAD_1": "1", "NUMPAD_2": "2", "NUMPAD_3": "3",
    "NUMPAD_4": "4", "NUMPAD_5": "5", "NUMPAD_6": "6", "NUMPAD_7": "7",
    "NUMPAD_8": "8", "NUMPAD_9": "9",
}


class IOPS_OT_edge_shear(bpy.types.Operator):
    """Shear selected edges in the face plane.

Active vert slides perpendicular to the edge within the face plane by
L * tan(angle). Mouse-drag or type a number to set the angle. F flips
the active vert. Enter/LMB confirms, Esc/RMB cancels."""

    bl_idname = "iops.edge_shear"
    bl_label = "Edge Shear (Face Plane)"
    bl_description = (
        "Shear selected edges in the face plane. Active vert slides "
        "perpendicular to the edge within the face plane. "
        "Mouse drag or type a number to set angle, D flips direction, "
        "F flips active vert"
    )
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and obj.mode == "EDIT"

    def invoke(self, context, event):
        obj = context.active_object
        self.obj = obj
        self.bm = bmesh.from_edit_mesh(obj.data)
        self.bm.edges.ensure_lookup_table()
        self.bm.faces.ensure_lookup_table()
        self.bm.normal_update()

        selected = [e for e in self.bm.edges
                    if e.select and len(e.link_faces) > 0]
        if not selected:
            self.report({"WARNING"},
                        "Select at least one edge with an adjacent face")
            return {"CANCELLED"}

        # Find the last BMVert added to the select history, if any.
        hist_vert = None
        try:
            for item in self.bm.select_history:
                if isinstance(item, bmesh.types.BMVert):
                    hist_vert = item
        except (TypeError, RuntimeError):
            hist_vert = None

        self.records = []
        skip_reasons = []
        for e in selected:
            face = e.link_faces[0]
            v0, v1 = e.verts
            if hist_vert is v0:
                active, fixed = v0, v1
            elif hist_vert is v1:
                active, fixed = v1, v0
            else:
                active, fixed = v1, v0

            rec, reason = self._build_record(e, face, active, fixed)
            if rec is not None:
                self.records.append(rec)
            else:
                skip_reasons.append(reason)

        if not self.records:
            msg = "No valid edges for shear"
            if skip_reasons:
                msg += f" ({skip_reasons[0]})"
            self.report({"WARNING"}, msg)
            return {"CANCELLED"}

        self.angle_deg = 45.0
        self.input_str = ""
        self.mouse_start_x = event.mouse_region_x

        bpy.ops.ed.undo_push(message="Edge Shear")

        self.shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_callback, (context,), "WINDOW", "POST_PIXEL")

        self._apply()
        context.workspace.status_text_set(self._status_text())
        context.window_manager.modal_handler_add(self)
        if context.area:
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    # ------------------------------------------------------------------
    # Records / math
    # ------------------------------------------------------------------

    def _build_record(self, edge, face, active, fixed):
        edge_vec = active.co - fixed.co
        L = edge_vec.length
        if L < 1e-9:
            return None, "edge has zero length"
        edge_dir = edge_vec / L

        normal = face.normal.copy()
        if normal.length < 1e-9:
            # Fallback: compute face normal from first non-collinear edge pair.
            verts = [l.vert.co for l in face.loops]
            if len(verts) >= 3:
                for i in range(1, len(verts) - 1):
                    a = verts[i] - verts[0]
                    b = verts[i + 1] - verts[0]
                    n = a.cross(b)
                    if n.length > 1e-9:
                        normal = n.normalized()
                        break
        if normal.length < 1e-9:
            return None, "face has zero normal"

        perp = normal.cross(edge_dir)
        if perp.length < 1e-9:
            return None, "edge is parallel to face normal"
        perp.normalize()
        rec = {
            "edge": edge,
            "face": face,
            "active": active,
            "fixed": fixed,
            "orig_active_co": active.co.copy(),
            "orig_fixed_co": fixed.co.copy(),
            "edge_length": L,
            "perp": perp.copy(),
        }
        return rec, None

    def _effective_angle(self):
        if self.input_str and self.input_str not in ("-", ".", "-."):
            try:
                return float(self.input_str)
            except ValueError:
                return self.angle_deg
        return self.angle_deg

    def _apply(self):
        a_rad = math.radians(self._effective_angle())
        c = math.cos(a_rad)
        if abs(c) < 1e-6:
            t = math.copysign(1e4, math.sin(a_rad))
        else:
            t = math.sin(a_rad) / c
        t = max(-1e4, min(1e4, t))

        for r in self.records:
            if not (r["active"].is_valid and r["fixed"].is_valid):
                continue
            shift = r["perp"] * r["edge_length"] * t
            r["active"].co = r["orig_active_co"] + shift
        self.bm.normal_update()
        bmesh.update_edit_mesh(self.obj.data)

    def _restore(self):
        for r in self.records:
            if r["active"].is_valid:
                r["active"].co = r["orig_active_co"]
        self.bm.normal_update()
        bmesh.update_edit_mesh(self.obj.data)

    def _flip(self):
        for r in self.records:
            if r["active"].is_valid:
                r["active"].co = r["orig_active_co"]
            r["active"], r["fixed"] = r["fixed"], r["active"]
            r["orig_active_co"], r["orig_fixed_co"] = (
                r["orig_fixed_co"], r["orig_active_co"]
            )
            edge_vec = r["orig_active_co"] - r["orig_fixed_co"]
            L = edge_vec.length
            if L < 1e-9:
                continue
            perp = r["face"].normal.cross(edge_vec / L)
            if perp.length < 1e-9:
                continue
            r["perp"] = perp.normalized()
            r["edge_length"] = L
        self._apply()

    # ------------------------------------------------------------------
    # Modal
    # ------------------------------------------------------------------

    def _status_text(self):
        typed = f" | typing: {self.input_str}" if self.input_str else ""
        return (
            f"Edge Shear: {self._effective_angle():.2f}°{typed} | "
            "[Mouse] drag | [0-9 . -] type | [Backspace] del | "
            "[D] flip direction | [F] flip active | "
            "[Enter/LMB] confirm | [Esc/RMB] cancel"
        )

    def modal(self, context, event):
        if context.area:
            context.area.tag_redraw()

        if (event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}
                or event.type.startswith("NDOF")):
            return {"PASS_THROUGH"}

        if event.type == "MOUSEMOVE":
            return {"RUNNING_MODAL"}

        if event.value == "PRESS":
            if event.type in DIGIT_TYPES:
                self.input_str += DIGIT_TYPES[event.type]
                self._apply()
                context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}

            if event.type in {"PERIOD", "NUMPAD_PERIOD"}:
                if "." not in self.input_str:
                    self.input_str += "."
                    context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}

            if event.type in {"MINUS", "NUMPAD_MINUS"}:
                if self.input_str.startswith("-"):
                    self.input_str = self.input_str[1:]
                else:
                    self.input_str = "-" + self.input_str
                self._apply()
                context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}

            if event.type == "BACK_SPACE":
                self.input_str = self.input_str[:-1]
                self._apply()
                context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}

            if event.type == "F":
                self._flip()
                context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}

            if event.type == "D":
                if self.input_str:
                    if self.input_str.startswith("-"):
                        self.input_str = self.input_str[1:]
                    else:
                        self.input_str = "-" + self.input_str
                else:
                    self.angle_deg = -self.angle_deg
                    self.mouse_start_x = event.mouse_region_x
                self._apply()
                context.workspace.status_text_set(self._status_text())
                return {"RUNNING_MODAL"}

            if event.type in {"LEFTMOUSE", "RET", "NUMPAD_ENTER", "SPACE"}:
                self.angle_deg = self._effective_angle()
                self.input_str = ""
                self._apply()
                self._finish(context)
                return {"FINISHED"}

            if event.type in {"RIGHTMOUSE", "ESC"}:
                self._restore()
                self._finish(context)
                return {"CANCELLED"}

        return {"RUNNING_MODAL"}

    def _finish(self, context):
        if getattr(self, "_handle", None):
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, "WINDOW")
            self._handle = None
        context.workspace.status_text_set(None)
        if context.area:
            context.area.tag_redraw()

    # ------------------------------------------------------------------
    # Draw
    # ------------------------------------------------------------------

    def _draw_callback(self, context):
        region = context.region
        rv3d = context.region_data
        if rv3d is None:
            return
        mw = self.obj.matrix_world

        gpu.state.blend_set("ALPHA")
        gpu.state.line_width_set(2.0)
        self.shader.bind()

        for r in self.records:
            if not (r["active"].is_valid and r["fixed"].is_valid):
                continue

            p_active = view3d_utils.location_3d_to_region_2d(
                region, rv3d, mw @ r["active"].co)
            p_fixed = view3d_utils.location_3d_to_region_2d(
                region, rv3d, mw @ r["fixed"].co)
            p_orig = view3d_utils.location_3d_to_region_2d(
                region, rv3d, mw @ r["orig_active_co"])

            if p_active is None or p_fixed is None:
                continue

            segs = 24
            cx, cy = p_fixed
            radius = 6.0
            ring = [
                (cx + math.cos(2 * math.pi * i / segs) * radius,
                 cy + math.sin(2 * math.pi * i / segs) * radius)
                for i in range(segs)
            ]
            tris = []
            for i in range(segs):
                j = (i + 1) % segs
                tris.extend([(cx, cy), ring[i], ring[j]])
            self.shader.uniform_float("color", (1.0, 0.7, 0.2, 1.0))
            batch = batch_for_shader(self.shader, "TRIS", {"pos": tris})
            batch.draw(self.shader)

            batch = batch_for_shader(
                self.shader, "LINES", {"pos": [p_fixed, p_active]})
            batch.draw(self.shader)

            if p_orig is not None and p_orig != p_active:
                self.shader.uniform_float("color", (0.5, 0.5, 0.5, 0.7))
                batch = batch_for_shader(
                    self.shader, "LINES", {"pos": [p_fixed, p_orig]})
                batch.draw(self.shader)

        gpu.state.line_width_set(1.0)
        gpu.state.blend_set("NONE")

        font_id = 0
        try:
            prefs = context.preferences.addons["InteractionOps"].preferences
            tCSize = getattr(prefs, "text_size", 18)
            tCPosX = getattr(prefs, "text_pos_x", 30)
            tCPosY = getattr(prefs, "text_pos_y", 90)
            tColor = getattr(prefs, "text_color", (1.0, 1.0, 1.0, 1.0))
        except (KeyError, AttributeError):
            tCSize, tCPosX, tCPosY = 18, 30, 90
            tColor = (1.0, 1.0, 1.0, 1.0)
        uifactor = context.preferences.system.ui_scale
        blf.size(font_id, int(tCSize * uifactor))
        blf.color(font_id, *tColor)
        blf.position(font_id, tCPosX * uifactor, tCPosY * uifactor, 0)
        label = f"Shear: {self._effective_angle():.2f}°"
        if self.input_str:
            label += f"  (typing: {self.input_str})"
        blf.draw(font_id, label)
