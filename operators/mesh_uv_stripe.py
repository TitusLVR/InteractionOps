"""UV Stripe: unwrap each selected strip of faces as one straight UV strip, without stretch by default.

Every edge-connected island of selected faces becomes a ``uv_stripe_core.Strip``
(``uv_stripe_select_core.strip_from_faces``), built from world positions so the
object's scale shows in the aspect. The whole island is built first and then torn
by slicing its rows at the chosen rungs: at its bends (Split at Bends) and at the
seams inside it (Split at Seams). Only an island that is no strip as a whole is
split at its seams into islands built one by one. The pieces are written into the
active UV map through ``uv_stripe_bridge``; no ``bpy.ops.uv`` call.

Invoked, the operator is modal: every option has a key, and every change restores
the UVs and seams the selected faces had and lays them out again, so the UV editor
follows live; the viewport shows each piece's outline and where the strip is torn.
Confirm keeps the result (one undo step), cancel puts the snapshot back.
"""

import math
from dataclasses import dataclass, field

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty
from bpy_extras import view3d_utils
from mathutils import Vector

from ..ui.draw import Role, draw_scope, safe_handler_add, safe_handler_remove
from ..ui.draw import primitives as draw
from ..ui.hud import HelpOverlay, HUDItem, HUDOverlay, HUDParam, HUDSection, ItemState, capture_event
from ..utils import uv_stripe_core, uv_stripe_select_core
from . import uv_stripe_bridge

EPS = 1e-6
ANGLE_STEP = math.radians(5.0)
ANGLE_FINE_STEP = math.radians(1.0)
LAYOUT_CYCLE = [item[0] for item in uv_stripe_bridge.LAYOUT_ITEMS]
MODE_CYCLE = ["FIT", "IN_PLACE", "ACTIVE"]
MODE_NAMES = {"FIT": "Fit 0–1", "IN_PLACE": "In Place", "ACTIVE": "Active"}
NAVIGATION = {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE", "TRACKPADPAN", "TRACKPADZOOM"}

_ACTIVE_HANDLES = set()


def _purge_handles():
    """Remove any stale draw handlers left behind by a previous reload."""
    while _ACTIVE_HANDLES:
        h = _ACTIVE_HANDLES.pop()
        try:
            safe_handler_remove(h, bpy.types.SpaceView3D, "WINDOW")
        except (ValueError, RuntimeError):
            pass


def _world_context(ctx, faces, matrix):
    """``ctx`` with its density turned from object units into world units over ``faces``' edges.

    ``uv_context`` measures density against object-space lengths, while the strip is
    laid out in world units; the ratio of the two lengths over the strip's own edges
    brings an In Place strip back to the neighbours' texel density on a scaled object.
    """
    if ctx is None:
        return None
    edges = {e for f in faces for e in f.edges}
    local = sum(e.calc_length() for e in edges)
    world = sum((matrix @ e.verts[0].co - matrix @ e.verts[1].co).length for e in edges)
    if local <= 0.0 or world <= 0.0:
        return ctx
    return uv_stripe_bridge.StripeContext(ctx.center, ctx.density * local / world)


def _build(piece, verts, seam_edge=None):
    """The strip of one island (face id -> vertex ids) in world units; raises ValueError."""
    strip = uv_stripe_select_core.strip_from_faces(verts, piece, seam_edge)
    if uv_stripe_core.strip_length(strip) <= EPS:
        raise ValueError("the strip has no length")
    if strip.height <= EPS:
        raise ValueError("the strip has no width")
    return strip


def _inner_cuts(island, cuts):
    """The edges of ``cuts`` that lie between two faces of the island."""
    uses = {}
    for face in island.values():
        for k, a in enumerate(face):
            e = tuple(sorted((a, face[(k + 1) % len(face)])))
            uses[e] = uses.get(e, 0) + 1
    return {e for e in cuts if uses.get(e) == 2}


@dataclass
class _Result:
    """What one layout pass did, over every object in Edit Mode."""

    selected: int = 0
    done: int = 0
    anchored: bool = False        # Active: some object's strips were placed on its active face
    unanchored: bool = False      # Active: an object's active face was laid out but gave no anchor
    skipped: int = 0
    first_reason: str | None = None
    warnings: list[str] = field(default_factory=list)
    outline: list = field(default_factory=list)   # world-space segment end points, two per segment
    tears: list = field(default_factory=list)


def _collect_preview(result, pieces, matrix):
    """World-space segments of every piece's outline, and of the edges the strip is torn at."""
    piece_of = {}
    for n, (_strip, faces) in enumerate(pieces):
        for f in faces.values():
            piece_of[f] = n
    for n, (strip, faces) in enumerate(pieces):
        inside = set(faces.values())
        cut = set()
        if strip.closed and strip.rungs:
            k = strip.seam if strip.seam is not None else uv_stripe_core.sharpest_rung(strip)
            ni, fi = strip.rungs[k]
            cut = {strip.near[ni % len(strip.near)], strip.far[fi % len(strip.far)]}
        for e in {e for f in inside for e in f.edges}:
            linked = [piece_of[g] for g in e.link_faces if g in piece_of]
            ends = (matrix @ e.verts[0].co, matrix @ e.verts[1].co)
            if linked.count(n) == 1:
                result.outline.extend(ends)
            ring_cut = bool(cut) and {v.index for v in e.verts} == cut
            between = len(set(linked)) > 1 and n == min(linked)     # each tear once
            if ring_cut or between:
                result.tears.extend(ends)


class IOPS_OT_Mesh_UV_Stripe(bpy.types.Operator):
    """Unwrap each selected strip of faces as one straight UV strip, without stretch"""

    bl_idname = "iops.mesh_uv_stripe"
    bl_label = "UV Stripe"
    bl_options = {"REGISTER", "UNDO"}
    is_bindable = True

    mode: EnumProperty(
        name="Mode",
        items=[*uv_stripe_bridge.MODE_ITEMS, uv_stripe_bridge.ACTIVE_MODE_ITEM],
        default="FIT",
    )
    orientation: EnumProperty(
        name="Orientation",
        description="Whether the strip runs along U or along V",
        items=uv_stripe_bridge.ORIENTATION_ITEMS,
        default="HORIZONTAL",
    )
    layout: EnumProperty(
        name="Layout",
        description="How the strip's rows are laid out along its length",
        items=uv_stripe_bridge.LAYOUT_ITEMS,
        default="TRUE",
    )
    split_at_seams: BoolProperty(
        name="Split at Seams",
        description=(
            "Tear the strip at edges already marked as seams between two selected faces; "
            "off, the strip is laid out across them (Mark Seams then clears them)"
        ),
        default=False,
    )
    split_at_bends: BoolProperty(
        name="Split at Bends",
        description="Tear the strip at cross edges where it bends within its own surface by more than the bend angle",
        default=True,
    )
    split_angle: FloatProperty(
        name="Bend Angle",
        description="Turn of the strip, summed since the last tear, beyond which it is torn",
        subtype="ANGLE",
        default=math.radians(15.0),
        min=math.radians(1.0),
        max=math.pi,
    )
    mark_seams: BoolProperty(
        name="Mark Seams",
        description=(
            "Make the seams match the laid-out UV pieces: mark every piece's outline and clear the seams "
            "inside a piece"
        ),
        default=True,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and obj.mode == "EDIT"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "mode")
        row = layout.row()
        row.active = self.mode != "ACTIVE"   # greyed out: Active takes the direction from the active face
        row.prop(self, "orientation")
        for name in ("layout", "split_at_seams", "split_at_bends"):
            layout.prop(self, name)
        row = layout.row()
        row.enabled = self.split_at_bends
        row.prop(self, "split_angle")
        layout.prop(self, "mark_seams")

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _pieces(self, island, verts, picked, seam_cuts):
        """The laid-out pieces of one island as ([(strip, faces by id)], warning); raises ValueError.

        The whole island is built and torn at its bends and at the seams inside it that
        are its rungs. An island that is no strip as a whole, or one with a seam inside
        it that is no rung, is first split at those seams and each part built on its own.
        """
        split = self.split_angle if self.split_at_bends else None
        inner = _inner_cuts(island, seam_cuts)
        try:
            strip = _build(island, verts)
        except ValueError:
            strip = None
        if strip is not None:
            cuts = uv_stripe_select_core.rungs_at(strip, inner)
            if len(cuts) == len(inner):
                return uv_stripe_bridge.prepare_strip(strip, picked, self.layout, split, cuts)
        if not inner:
            _build(island, verts)          # raises the island's own reason
        out, reasons, failed = [], [], None
        for part in uv_stripe_select_core.face_islands(island, frozenset(inner)):
            left = _inner_cuts(part, inner)
            seam_edge = next(iter(left)) if len(left) == 1 else None
            try:
                pieces, reason = uv_stripe_bridge.prepare_strip(
                    _build(part, verts, seam_edge), picked, self.layout, split)
            except ValueError as exc:      # one part that is no strip leaves the others
                failed = failed or str(exc)
                continue
            out += pieces
            if reason:
                reasons.append(reason)
        if not out:
            raise ValueError(failed)
        if failed:
            reasons.append(f"a part between the seams is skipped: {failed}")
        return out, (reasons[0] if reasons else None)

    def _lay_out(self, context):
        """Lay out every selected strip of every mesh in Edit Mode; returns a ``_Result``."""
        result = _Result()
        for obj in context.objects_in_mode_unique_data:
            if obj.type != "MESH":
                continue
            me = obj.data
            bm = bmesh.from_edit_mesh(me)
            bm.verts.index_update()
            bm.faces.index_update()
            picked = {f.index: f for f in bm.faces if f.select and not f.hide}
            if not picked:
                continue
            result.selected += 1
            ids = {fid: tuple(v.index for v in f.verts) for fid, f in picked.items()}
            matrix = obj.matrix_world
            verts = {v.index: tuple(matrix @ v.co) for f in picked.values() for v in f.verts}
            seam_cuts = set()
            if self.split_at_seams:
                seam_cuts = {
                    tuple(sorted(v.index for v in e.verts))
                    for f in picked.values()
                    for e in f.edges
                    if e.seam and sum(g.index in picked for g in e.link_faces) == 2
                }
            strips, contexts, pieces = [], [], []
            active_face = bm.faces.active if self.mode == "ACTIVE" else None
            for island in uv_stripe_select_core.face_islands(ids):
                try:
                    laid, warning = self._pieces(island, verts, picked, seam_cuts)
                except ValueError as exc:
                    result.skipped += 1
                    result.first_reason = result.first_reason or str(exc)
                    continue
                if warning:
                    result.warnings.append(f"UV Stripe: not split ({warning})")
                for strip, faces in laid:
                    piece_faces = list(faces.values())
                    strips.append(strip)
                    pieces.append((strip, faces))
                    contexts.append(_world_context(uv_stripe_bridge.uv_context(bm, piece_faces), piece_faces, matrix))
            if not strips:
                continue
            active = next(((i, active_face.index) for i, (_s, faces) in enumerate(pieces)
                           if active_face is not None and active_face.index in faces
                           and faces[active_face.index] is active_face), None)
            anchored = uv_stripe_bridge.apply_stripes(
                bm, strips, picked, self.mode, contexts, fit_groups=[0] * len(strips),
                vertical=self.orientation == "VERTICAL", active=active)
            result.anchored |= anchored
            result.unanchored |= active is not None and not anchored
            if self.mark_seams:
                uv_stripe_bridge.match_piece_seams(pieces)
            _collect_preview(result, pieces, matrix)
            result.done += len(strips)
        if self.mode == "ACTIVE" and result.done and (result.unanchored or not result.anchored):
            result.warnings.append(uv_stripe_bridge.ACTIVE_FALLBACK)
        return result

    def _report_result(self, result):
        """Report as execute does; returns the operator's result set."""
        if not result.selected:
            self.report({"WARNING"}, "UV Stripe: no faces selected")
            return {"CANCELLED"}
        if not result.done:
            self.report({"WARNING"}, f"UV Stripe: nothing laid out ({result.first_reason})")
            return {"CANCELLED"}
        for message in dict.fromkeys(result.warnings):
            self.report({"WARNING"}, message)
        if result.skipped:
            self.report({"WARNING"}, f"UV Stripe: {result.done} strip(s), {result.skipped} skipped "
                                     f"({result.first_reason})")
        else:
            self.report({"INFO"}, f"UV Stripe: {result.done} strip(s)")
        return {"FINISHED"}

    def execute(self, context):
        result = self._lay_out(context)
        if result.done:
            for obj in context.objects_in_mode_unique_data:
                if obj.type == "MESH":
                    bmesh.update_edit_mesh(obj.data)
        return self._report_result(result)

    # ------------------------------------------------------------------
    # Snapshot: what the modal restores before every layout and on cancel
    # ------------------------------------------------------------------

    def _take_snapshot(self, context):
        """Per mesh: whether it had a UV layer, the selected faces' loop UVs and their edges' seam flags."""
        self._snapshot = []
        for obj in context.objects_in_mode_unique_data:
            if obj.type != "MESH":
                continue
            bm = bmesh.from_edit_mesh(obj.data)
            bm.faces.index_update()
            bm.edges.index_update()
            layer = bm.loops.layers.uv.active
            faces = [f for f in bm.faces if f.select and not f.hide]
            uvs = {}
            if layer is not None:
                uvs = {(f.index, k): tuple(lp[layer].uv) for f in faces for k, lp in enumerate(f.loops)}
            seams = {e.index: e.seam for f in faces for e in f.edges}
            self._snapshot.append((obj.data, layer is not None, uvs, seams))

    def _restore_snapshot(self, update=True):
        """Put the snapshot back: UVs, seams, and no UV layer where there was none."""
        for me, had_layer, uvs, seams in getattr(self, "_snapshot", []):
            bm = bmesh.from_edit_mesh(me)
            bm.faces.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            layer = bm.loops.layers.uv.active
            if not had_layer:
                if layer is not None:
                    bm.loops.layers.uv.remove(layer)
            elif layer is not None:
                for (fi, k), co in uvs.items():
                    bm.faces[fi].loops[k][layer].uv = co
            for ei, seam in seams.items():
                bm.edges[ei].seam = seam
            if update:
                bmesh.update_edit_mesh(me)

    def _relayout(self, context):
        """Restore the snapshot and lay out again with the current options."""
        self._restore_snapshot(update=False)
        self._result = self._lay_out(context)
        for me, *_rest in self._snapshot:
            bmesh.update_edit_mesh(me)
        if getattr(context, "area", None):
            context.area.tag_redraw()
        try:
            context.workspace.status_text_set(self._status_text())
        except AttributeError:
            pass

    # ------------------------------------------------------------------
    # Modal
    # ------------------------------------------------------------------

    def _start(self, context):
        """Snapshot and first layout; False (reported, restored) when nothing can be laid out."""
        self._take_snapshot(context)
        self._cancel = {name: getattr(self, name) for name in (
            "mode", "orientation", "layout", "split_at_seams", "split_at_bends", "split_angle", "mark_seams")}
        self._relayout(context)
        if not self._result.done:
            self._restore_snapshot()
            self._report_result(self._result)
            return False
        return True

    def invoke(self, context, event):
        _purge_handles()
        self._handle = None
        if not self._start(context):
            return {"CANCELLED"}
        self._build_overlays(context.region)
        self._last_event = capture_event(event, getattr(self, "_last_event", None))
        self._handle = safe_handler_add(
            bpy.types.SpaceView3D, self._draw_callback, (context,), "WINDOW", "POST_PIXEL", tick=True)
        _ACTIVE_HANDLES.add(self._handle)
        context.workspace.status_text_set(self._status_text())
        context.window_manager.modal_handler_add(self)
        if context.area:
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def _build_overlays(self, region):
        self._hud = HUDOverlay("uv_stripe")
        self._hud.title = "UV Stripe"
        self._hud.bind_region(region)
        layout_names = {item[0]: item[1] for item in uv_stripe_bridge.LAYOUT_ITEMS}
        orientation_names = {item[0]: item[1] for item in uv_stripe_bridge.ORIENTATION_ITEMS}
        self._hud.add_param(HUDParam("Orientation (R)", lambda: orientation_names[self.orientation], "enum",
                                     active_getter=lambda: self.mode != "ACTIVE"))
        self._hud.add_param(HUDParam("Mode (M)", lambda: MODE_NAMES[self.mode], "enum"))
        self._hud.add_param(HUDParam("Layout (S)", lambda: layout_names[self.layout], "enum"))
        self._hud.add_param(HUDParam("Split at Seams (E)", lambda: self.split_at_seams, "bool"))
        self._hud.add_param(HUDParam("Split at Bends (B)", lambda: self.split_at_bends, "bool"))
        self._hud.add_param(HUDParam("Bend Angle (Wheel)", lambda: math.degrees(self.split_angle), "float",
                                     fmt="{:.0f}°", active_getter=lambda: self.split_at_bends))
        self._hud.add_param(HUDParam("Mark Seams (X)", lambda: self.mark_seams, "bool"))

        def item(label, key):
            return HUDItem(label, key, ItemState.ON, default_state=ItemState.OFF, always_show=True)

        self._help = HelpOverlay("uv_stripe")
        self._help.add_section(HUDSection("UV Stripe", [
            item("Orientation", "R"),
            item("Mode", "M"),
            item("Layout", "S"),
            item("Split at seams", "E"),
            item("Split at bends", "B"),
            item("Bend angle", "Wheel / Ctrl + Wheel"),
            item("Mark seams", "X"),
            item("Confirm", "LMB / Enter / Space"),
            item("Cancel", "Esc / RMB"),
            item("Help / Toggle HUD", "H"),
        ]))
        self._help.bind_region(region)

    def modal(self, context, event):
        try:
            return self._modal(context, event)
        except ReferenceError:
            # bmesh data invalidated mid-modal (undo, addon reload): tear the handler down.
            self._finish(context)
            self.report({"WARNING"}, "UV Stripe: mesh data became invalid — cancelled")
            return {"CANCELLED"}
        except Exception:
            self._finish(context)
            raise

    def _modal(self, context, event):
        if getattr(context, "area", None):
            context.area.tag_redraw()
        self._last_event = capture_event(event, getattr(self, "_last_event", None))

        try:
            theme_prefs = context.preferences.addons["InteractionOps"].preferences.iops_theme
        except (KeyError, AttributeError):
            theme_prefs = None
        if theme_prefs is not None:
            helpo = getattr(self, "_help", None)
            hud = getattr(self, "_hud", None)
            if helpo is not None and helpo.handle_drag_event(context, event, theme_prefs):
                return {"RUNNING_MODAL"}
            if hud is not None and hud.handle_drag_event(context, event, theme_prefs):
                return {"RUNNING_MODAL"}
            if helpo is not None and helpo.handle_toggle_event(event, theme_prefs):   # H
                return {"RUNNING_MODAL"}
            if hud is not None and hud.handle_param_toggle_event(event, theme_prefs):
                return {"RUNNING_MODAL"}

        if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"} and self.split_at_bends:
            step = ANGLE_FINE_STEP if event.ctrl else ANGLE_STEP
            step = step if event.type == "WHEELUPMOUSE" else -step
            self.split_angle = min(max(self.split_angle + step, math.radians(1.0)), math.pi)
            self._relayout(context)
            return {"RUNNING_MODAL"}
        if event.type in NAVIGATION or event.type.startswith("NDOF"):
            return {"PASS_THROUGH"}

        if event.value != "PRESS":
            return {"RUNNING_MODAL"}
        if event.type == "R":
            self.orientation = "VERTICAL" if self.orientation == "HORIZONTAL" else "HORIZONTAL"
        elif event.type == "M":
            self.mode = MODE_CYCLE[(MODE_CYCLE.index(self.mode) + 1) % len(MODE_CYCLE)]
        elif event.type == "S":
            self.layout = LAYOUT_CYCLE[(LAYOUT_CYCLE.index(self.layout) + 1) % len(LAYOUT_CYCLE)]
        elif event.type == "E":
            self.split_at_seams = not self.split_at_seams
        elif event.type == "B":
            self.split_at_bends = not self.split_at_bends
        elif event.type == "X":
            self.mark_seams = not self.mark_seams
        elif event.type in {"LEFTMOUSE", "RET", "NUMPAD_ENTER", "SPACE"}:
            self._finish(context)
            return self._report_result(self._result)
        elif event.type in {"RIGHTMOUSE", "ESC"}:
            for name, value in self._cancel.items():
                setattr(self, name, value)
            self._restore_snapshot()
            self._finish(context)
            return {"CANCELLED"}
        else:
            return {"RUNNING_MODAL"}
        self._relayout(context)
        return {"RUNNING_MODAL"}

    def _finish(self, context):
        h = getattr(self, "_handle", None)
        if h is not None:
            _ACTIVE_HANDLES.discard(h)
            try:
                safe_handler_remove(h, bpy.types.SpaceView3D, "WINDOW")
            except (ValueError, RuntimeError):
                pass
            self._handle = None
        try:
            context.workspace.status_text_set(None)
        except AttributeError:
            pass
        if getattr(context, "area", None):
            context.area.tag_redraw()
        # Finished operator instances stay alive in the redo stack: drop every mesh reference.
        self._snapshot = []
        self._hud = None
        self._help = None

    def _status_text(self):
        layout_names = {item[0]: item[1] for item in uv_stripe_bridge.LAYOUT_ITEMS}
        result = getattr(self, "_result", None)
        count = f"{result.done} strip(s) | " if result is not None else ""
        bend = f"{math.degrees(self.split_angle):.0f}°" if self.split_at_bends else "off"
        return (
            f"UV Stripe: {count}"
            f"orientation = {'from the active face' if self.mode == 'ACTIVE' else self.orientation.lower()} (R) | "
            f"mode = {MODE_NAMES[self.mode].lower()} (M) | "
            f"layout = {layout_names[self.layout].lower()} (S) | "
            f"split at seams = {'on' if self.split_at_seams else 'off'} (E) | "
            f"split at bends = {bend} (B, Wheel) | "
            f"mark seams = {'on' if self.mark_seams else 'off'} (X) | "
            "[Enter/LMB/Space] confirm | [Esc/RMB] cancel"
        )

    def _draw_callback(self, context):
        region = context.region
        rv3d = context.region_data
        if rv3d is None:
            return
        result = getattr(self, "_result", None)

        def project(points):
            out = []
            for i in range(0, len(points) - 1, 2):
                a = view3d_utils.location_3d_to_region_2d(region, rv3d, points[i])
                b = view3d_utils.location_3d_to_region_2d(region, rv3d, points[i + 1])
                if a is not None and b is not None:
                    out += [Vector((a[0], a[1], 0.0)), Vector((b[0], b[1], 0.0))]
            return out

        try:
            outline = project(result.outline) if result is not None else []
            tears = project(result.tears) if result is not None else []
        except Exception:   # a draw handler must never raise: it would repeat every frame
            outline, tears = [], []
        if outline or tears:
            with draw_scope(blend="ALPHA"):
                if outline:
                    draw.edges_3d(outline, role=Role.PREVIEW_LINE, context=context)
                if tears:
                    draw.edges_3d(tears, role=Role.ERROR_LINE, context=context)
        hud = getattr(self, "_hud", None)
        helpo = getattr(self, "_help", None)
        last_event = getattr(self, "_last_event", None)
        if helpo is not None:
            helpo.draw(context, last_event)
        if hud is not None:
            hud.set_header(f"{result.done if result is not None else 0} strip(s)")
            hud.draw(context, last_event)
