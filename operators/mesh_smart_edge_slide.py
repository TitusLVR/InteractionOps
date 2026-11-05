"""Smart Edge Slide: cut a new edge loop beside each selected chain of edges.

The loop runs at a set width from the chain, measured in the surface on one side
of it. ``utils/smart_edge_slide_core`` places the loop on a band of faces, and
``mesh_smart_edge_slide_bridge`` builds the bands and the cuts on the mesh.

The modal (``invoke``) drags the width with the mouse, mirroring Smart Inset's:
numeric entry, Shift precision, Ctrl snap to a vertex, F to flip the side of the
chain nearest the cursor, and a themed preview of the new loops.

UV Stripe (``uv_stripe_bridge``) can unwrap each new strip as one straight UV
rectangle once the loops are cut.
"""

import bmesh
import bpy
import numpy as np
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty
from bpy_extras import view3d_utils
from mathutils import Vector

from ..ui.draw import Role, draw_scope, safe_handler_add, safe_handler_remove
from ..ui.draw import primitives as draw
from ..ui.hud import HelpOverlay, HUDItem, HUDOverlay, HUDParam, HUDSection, ItemState, capture_event
from ..utils import picking
from ..utils import smart_edge_slide_core as core
from . import mesh_smart_edge_slide_bridge as bridge
from . import uv_stripe_bridge

DIGIT_TYPES = {
    "ZERO": "0", "ONE": "1", "TWO": "2", "THREE": "3", "FOUR": "4",
    "FIVE": "5", "SIX": "6", "SEVEN": "7", "EIGHT": "8", "NINE": "9",
    "NUMPAD_0": "0", "NUMPAD_1": "1", "NUMPAD_2": "2", "NUMPAD_3": "3",
    "NUMPAD_4": "4", "NUMPAD_5": "5", "NUMPAD_6": "6", "NUMPAD_7": "7",
    "NUMPAD_8": "8", "NUMPAD_9": "9",
}


# A chain whose solve or cut raises one of these is skipped with a warning, and
# the other chains still cut. ArithmeticError and RuntimeError come from
# degenerate geometry deep in the core: a zero wedge angle, a trace that never ends.
_CHAIN_SKIPS = (core.OutOfRoom, ValueError, ArithmeticError, RuntimeError)


_ACTIVE_HANDLES = set()


def _purge_handles():
    """Remove any stale draw handlers left behind by a previous reload."""
    while _ACTIVE_HANDLES:
        h = _ACTIVE_HANDLES.pop()
        try:
            safe_handler_remove(h, bpy.types.SpaceView3D, "WINDOW")
        except (ValueError, RuntimeError):
            pass


class IOPS_OT_smart_edge_slide(bpy.types.Operator):
    """Cut a new edge loop beside the selected edges at a set width"""

    bl_idname = "iops.mesh_smart_edge_slide"
    bl_label = "Smart Edge Slide"
    bl_description = (
        "Cut a new edge loop beside each selected chain of edges, at a set "
        "distance measured in the surface on one side of the chain. Where a "
        "face beside the chain is a step (a pocket lip), the cut is projected "
        "onto the faces under it"
    )
    bl_options = {"REGISTER", "UNDO"}

    width: FloatProperty(
        name="Width",
        description=(
            "Distance of the new loop from the selected edges, measured in the "
            "surface beside them. Negative values cut on the other side"
        ),
        default=0.05,
        soft_min=-10.0,
        soft_max=10.0,
        step=1,
        precision=4,
        subtype="DISTANCE",
    )
    use_exact: BoolProperty(
        name="Exact Width",
        description=(
            "Keep every new vertex at the exact width: a vertex whose edge "
            "would miss it goes to the exact corner instead, which adds cut points"
        ),
        default=False,
    )
    use_collapse: BoolProperty(
        name="Allow Collapse",
        description=(
            "Let the width run past the point where a segment of the new loop "
            "shrinks to nothing, dropping that segment. When off, the width "
            "stops there"
        ),
        default=False,
    )
    use_uv_stripe: BoolProperty(
        name="UV Stripe",
        description=(
            "Unwrap the faces between the selected edges and each new loop as "
            "one straight, even strip in the active UV map"
        ),
        default=False,
    )
    uv_stripe_mode: EnumProperty(
        name="UV Stripe Mode",
        items=[
            ("FIT", "Fit 0–1", "Stretch the strip across U 0–1, V in proportion"),
            ("IN_PLACE", "In Place", "Keep the old UV location and the neighbours' texel density"),
        ],
        default="FIT",
    )
    chain_sides: StringProperty(
        description="One + or - per selected chain: the side its new loop goes to",
        default="",
        options={'HIDDEN'},
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and obj.mode == "EDIT"

    def _skip(self, msg) -> None:
        self.report({'WARNING'}, f"Smart Edge Slide: chain skipped ({msg})")

    def _side(self, i: int) -> int:
        """The band side chain ``i`` is cut on: its stored side, the other one for a negative width."""
        side = -1 if self.chain_sides[i:i + 1] == "-" else 1
        return -side if self.width < 0.0 else side

    # ------------------------------------------------------------------
    # Modal lifecycle
    # ------------------------------------------------------------------

    def invoke(self, context, event):
        # Purge first, before any early bail: a handler leaked by a crashed
        # session must go even when this invoke turns out to have nothing to do.
        _purge_handles()
        if context.region_data is None:  # no 3D viewport region to drag the width in
            return self.execute(context)

        obj = context.active_object
        bm = bmesh.from_edit_mesh(obj.data)
        # Bands and Sliders are built exactly once. Nothing between here and
        # confirm may call update_edit_mesh: the builds hold live BMesh references.
        if not self._build_sides(bm):
            self._chains, self._sides = [], []  # keep no BMesh references
            return {'CANCELLED'}
        self._obj = obj
        self._bm = bm

        # Cancel snapshot: every prop the modal can touch, written once, here.
        self._cancel_width = self.width
        self._cancel_use_exact = self.use_exact
        self._cancel_use_collapse = self.use_collapse
        self._cancel_use_uv_stripe = self.use_uv_stripe
        self._cancel_chain_sides = self.chain_sides
        self.chain_sides = self._sides_from_view(context)

        # Sensitivity baseline: a quarter of the average chain-edge length per
        # 100 px of horizontal mouse travel.
        lengths = [
            (src.verts[(k + 1) % len(src.verts)].co - src.verts[k].co).length
            for src, found in zip(self._chains, self._sides) if found
            for k in range(len(src.verts) if src.closed else len(src.verts) - 1)
        ]
        avg = sum(lengths) / len(lengths) if lengths else 1.0
        self._pixel_to_width = max(avg * 0.25 / 100.0, 1e-6)

        # Drag anchor, re-anchored whenever Shift or Ctrl is released or numeric
        # entry is cleared, so a hand-over never jumps the value.
        self._mouse_start_x = event.mouse_region_x
        self._initial_width = self.width
        self._shift_anchor_x = None
        self._shift_anchor_width = 0.0
        # Numeric entry: digits/./-/Backspace build this; non-empty overrides
        # the mouse-driven width (see _sync_typed_width).
        self._input_str = ""
        self._snapping = False
        self._status_hint = ""  # a note for the status bar, cleared by the next key press
        self._prepare_snap()

        # Preview is cached in 3D and only re-projected per redraw.
        self._preview_segs = []
        self._preview_points = []
        self._clamped = False
        self._preview_key = None
        self._rebuild_preview()

        self._build_overlays(context.region)
        self._last_event = capture_event(event, getattr(self, "_last_event", None))

        self._handle = safe_handler_add(
            bpy.types.SpaceView3D, self._draw_callback, (context,),
            "WINDOW", "POST_PIXEL", tick=True)
        _ACTIVE_HANDLES.add(self._handle)

        context.workspace.status_text_set(self._status_text())
        context.window_manager.modal_handler_add(self)
        if context.area:
            context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def _build_sides(self, bm) -> bool:
        """Both sides' band and Slider for every selected chain; False when no chain has either.

        ``self._sides[i]`` maps each side (+1, -1) chain ``self._chains[i]`` can be
        cut on to its (build, Slider). A chain with neither side is skipped with a
        warning, as ``execute`` would skip it.
        """
        chains, warnings = bridge.collect_chains(bm)
        for msg in warnings:
            self._skip(msg)
        self._chains, self._sides = chains, []
        tris = bridge.face_triangles(bm)  # one triangulation for every band: nothing edits the mesh before confirm
        for src in chains:
            found, errors = {}, []
            for side in (1, -1):
                build, err = bridge.build_band(bm, src, side, tris)
                if build is None:
                    errors.append(err)
                else:
                    found[side] = (build, core.Slider(build.band))
            if not found:
                self._skip("; ".join(dict.fromkeys(errors)))
            self._sides.append(found)
        if any(self._sides):
            return True
        if not chains and not warnings:
            self.report({'WARNING'}, "Smart Edge Slide: no edges selected")
        return False

    def _to_region(self, context, co):
        """Object-space ``co`` in region pixels as (x, y), or None behind the view."""
        p = view3d_utils.location_3d_to_region_2d(
            context.region, context.region_data, self._obj.matrix_world @ co)
        return None if p is None else (p[0], p[1])

    def _chain_xy(self, context, src):
        """The chain's vertices in region pixels; those behind the view are left out."""
        return [p for p in (self._to_region(context, v.co) for v in src.verts) if p is not None]

    def _sides_from_view(self, context) -> str:
        """``chain_sides`` as the view shows it: per chain, the side a positive width slides into."""
        out = ""
        for src, found in zip(self._chains, self._sides):
            centroids = {1: None, -1: None}
            for side, (build, _slider) in found.items():
                # The side faces: the band runs on round an open chain's ends, often onto the other side.
                faces = [build.faces[f] for f in dict.fromkeys(build.band.side_faces) if f in build.faces]
                if faces:
                    centroid = sum((f.calc_center_median() for f in faces), Vector()) / len(faces)
                    centroids[side] = self._to_region(context, centroid)
            side = core.positive_side(self._chain_xy(context, src), centroids[1], centroids[-1], src.closed)
            out += "+" if side > 0 else "-"
        return out

    def _build_overlays(self, region):
        self._hud = HUDOverlay("smart_edge_slide")
        self._hud.title = "Smart Edge Slide"
        self._hud.bind_region(region)
        self._hud.add_param(HUDParam("Width", lambda: self.width, "float", fmt="{:.4f}"))
        self._hud.add_param(HUDParam("Exact Width (E)", lambda: self.use_exact, "bool"))
        self._hud.add_param(HUDParam("Allow Collapse (C)", lambda: self.use_collapse, "bool"))
        self._hud.add_param(HUDParam("UV Stripe (U)", lambda: self.use_uv_stripe, "bool"))
        self._hud.add_param(HUDParam("Clamped", lambda: self._clamped, "bool"))

        self._help = HelpOverlay("smart_edge_slide")
        self._help.add_section(HUDSection("Smart Edge Slide", [
            HUDItem("Adjust width",      "Mouse / Type", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Snap to vertex",    "Ctrl",         ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Exact width",       "E",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Allow collapse",    "C",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("UV Stripe",         "U",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Flip chain side",   "F",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Confirm",           "LMB / Enter",  ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Cancel",            "Esc / RMB",    ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Help / Toggle HUD", "H",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
        ]))
        self._help.bind_region(region)

    def modal(self, context, event):
        try:
            return self._modal(context, event)
        except ReferenceError:
            # bmesh element invalidated mid-modal (undo, addon reload, or some
            # other op that freed the underlying data). Tear the draw handler
            # down so the viewport is not left with a dangling callback.
            self._finish(context)
            self.report({'WARNING'},
                        "Smart Edge Slide: bmesh data became invalid — cancelled")
            return {'CANCELLED'}
        except Exception:
            self._finish(context)
            raise

    def _modal(self, context, event):
        if context.area:
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
                return {'RUNNING_MODAL'}
            if hud is not None and hud.handle_drag_event(context, event, theme_prefs):
                return {'RUNNING_MODAL'}
            # H (iops.ui_help_toggle) lives here.
            if helpo is not None and helpo.handle_toggle_event(event, theme_prefs):
                return {'RUNNING_MODAL'}
            if hud is not None and hud.handle_param_toggle_event(event, theme_prefs):
                return {'RUNNING_MODAL'}

        if (event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}
                or event.type.startswith("NDOF")):
            return {'PASS_THROUGH'}

        if event.type == "MOUSEMOVE":
            if event.ctrl:
                self._snapping = True
                self._update_snap(context, event)
            else:
                if self._snapping:
                    # Leaving snap: re-anchor the drag on the snapped width and
                    # the current mouse position, so releasing Ctrl never jumps.
                    self._snapping = False
                    self._snap_co = None
                    self._reanchor_width_mouse(event)
                if not self._input_str:
                    self._update_width(event)
            self._rebuild_preview()
            context.workspace.status_text_set(self._status_text())
            return {'RUNNING_MODAL'}

        if event.value == "PRESS":
            self._status_hint = ""
            if event.type in DIGIT_TYPES:
                self._input_str += DIGIT_TYPES[event.type]
                self._sync_typed_width()
                self._rebuild_preview()
                context.workspace.status_text_set(self._status_text())
                return {'RUNNING_MODAL'}

            if event.type in {"PERIOD", "NUMPAD_PERIOD"}:
                if "." not in self._input_str:
                    self._input_str += "."
                context.workspace.status_text_set(self._status_text())
                return {'RUNNING_MODAL'}

            if event.type in {"MINUS", "NUMPAD_MINUS"}:
                had_input = bool(self._input_str)
                if self._input_str.startswith("-"):
                    self._input_str = self._input_str[1:]
                else:
                    self._input_str = "-" + self._input_str
                self._sync_typed_width()
                if had_input and not self._input_str:
                    self._reanchor_width_mouse(event)
                self._rebuild_preview()
                context.workspace.status_text_set(self._status_text())
                return {'RUNNING_MODAL'}

            if event.type == "BACK_SPACE":
                had_input = bool(self._input_str)
                self._input_str = self._input_str[:-1]
                self._sync_typed_width()
                if had_input and not self._input_str:
                    self._reanchor_width_mouse(event)
                self._rebuild_preview()
                context.workspace.status_text_set(self._status_text())
                return {'RUNNING_MODAL'}

            if event.type == "E":
                self.use_exact = not self.use_exact
                self._rebuild_preview()
                context.workspace.status_text_set(self._status_text())
                return {'RUNNING_MODAL'}

            if event.type == "C":
                self.use_collapse = not self.use_collapse
                self._rebuild_preview()
                context.workspace.status_text_set(self._status_text())
                return {'RUNNING_MODAL'}

            if event.type == "U":  # applied on confirm; the preview does not change
                self.use_uv_stripe = not self.use_uv_stripe
                context.workspace.status_text_set(self._status_text())
                return {'RUNNING_MODAL'}

            if event.type == "F":
                self._flip_nearest_chain(context, event)
                self._rebuild_preview()
                context.workspace.status_text_set(self._status_text())
                return {'RUNNING_MODAL'}

            if event.type in {"LEFTMOUSE", "RET", "NUMPAD_ENTER"}:
                self._finish(context)
                return self.execute(context)

            if event.type in {"RIGHTMOUSE", "ESC"}:
                # Cancel means cancel: every prop the modal can touch goes
                # back to its invoke-time value, toggles and sides included.
                self.width = self._cancel_width
                self.use_exact = self._cancel_use_exact
                self.use_collapse = self._cancel_use_collapse
                self.use_uv_stripe = self._cancel_use_uv_stripe
                self.chain_sides = self._cancel_chain_sides
                self._finish(context)
                return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def _update_width(self, event):
        """Map horizontal mouse travel onto ``width``.

        Shift scales the delta accumulated *since Shift was pressed* by 0.1,
        so toggling precise mode never snaps the value.
        """
        if event.shift:
            if self._shift_anchor_x is None:
                self._shift_anchor_x = event.mouse_region_x
                self._shift_anchor_width = self.width
            delta = event.mouse_region_x - self._shift_anchor_x
            self.width = self._shift_anchor_width + delta * self._pixel_to_width * 0.1
            return
        if self._shift_anchor_x is not None:
            # Leaving precise mode: re-anchor the coarse baseline on the
            # current value instead of snapping back to the invoke-time one.
            self._reanchor_width_mouse(event)
            return
        delta = event.mouse_region_x - self._mouse_start_x
        self.width = self._initial_width + delta * self._pixel_to_width

    def _sync_typed_width(self):
        """Push a valid numeric ``_input_str`` into ``self.width``.

        Silently ignored while the string is not yet a parseable float (e.g.
        just "-" or "."), so partial input never raises mid-typing.
        """
        if self._input_str and self._input_str not in ("-", "."):
            try:
                self.width = float(self._input_str)
            except ValueError:
                pass

    def _reanchor_width_mouse(self, event):
        """Re-anchor the mouse-driven width on the current mouse position and value.

        Handing control back to a frozen baseline (after typing or snapping) would
        apply however far the mouse drifted meanwhile as an instant jump. The Shift
        anchor goes too: the next Shift move anchors afresh on this value.
        """
        self._mouse_start_x = event.mouse_region_x
        self._initial_width = self.width
        self._shift_anchor_x = None

    def _flip_nearest_chain(self, context, event):
        """Flip the stored side of the chain nearest the cursor on screen.

        A chain with a band on one side only keeps that side; the status bar says why.
        """
        shown = [(i, self._chain_xy(context, src)) for i, src in enumerate(self._chains) if self._sides[i]]
        shown = [(i, xy) for i, xy in shown if xy]
        if not shown:
            return
        mouse = (event.mouse_region_x, event.mouse_region_y)
        pick = core.nearest_chain([xy for _i, xy in shown], [self._chains[i].closed for i, _xy in shown], mouse)
        i = shown[pick][0]
        if len(self._sides[i]) < 2:
            self._status_hint = "F: the nearest chain has faces on one side only"
            return
        sides = list(self.chain_sides)
        sides[i] = "+" if sides[i] == "-" else "-"
        self.chain_sides = "".join(sides)

    # ------------------------------------------------------------------
    # Ctrl snap
    # ------------------------------------------------------------------

    def _prepare_snap(self):
        """The Ctrl snap candidates: each vertex once, with the (chain, side) bands that hold it."""
        owners: dict = {}
        builds = [build for found in self._sides for build, _slider in found.values()]
        for v, i, side in bridge.snap_candidates(builds):
            owners.setdefault(v, []).append((i, side))
        self._snap_verts = list(owners)
        self._snap_owners = list(owners.values())
        self._snap_points = [("vertex", v.co.copy()) for v in self._snap_verts]
        # Object coordinates, for ``picking.snap_points_in_reach`` on every Ctrl move.
        self._snap_cos = np.array([tuple(co) for _kind, co in self._snap_points], dtype=float).reshape(-1, 3)
        self._snap_reach = {}
        self._snap_co = None
        self._bvh_cache = {}
        cos = [co for _kind, co in self._snap_points]
        self._snap_depth = sum(cos, Vector()) / len(cos) if cos else Vector()

    def _mouse_world(self, context, mouse):
        """The mesh surface under the mouse in world space; off the mesh, the mouse ray at the candidates' depth."""
        hit = picking.raycast_edit_meshes(context, mouse, [self._obj], cache=self._bvh_cache)
        if hit[0]:
            return hit[1]
        return view3d_utils.region_2d_to_location_3d(
            context.region, context.region_data, mouse, self._obj.matrix_world @ self._snap_depth)

    def _update_snap(self, context, event):
        """Ctrl held: snap the width to the candidate vertex nearest the cursor, when the loop reaches it.

        Every band vertex is a candidate, so only those ``closest_snap_point``
        can pick are ranked (``snap_points_in_reach``): the pick is the same.
        """
        self._snap_co = None
        if not self._snap_points:
            return
        mouse = (event.mouse_region_x, event.mouse_region_y)
        at = self._mouse_world(context, mouse)
        mw = self._obj.matrix_world
        keep = picking.snap_points_in_reach(context, self._snap_cos, mw, mouse, at)
        shortlist = range(len(self._snap_points)) if keep is None else keep
        points = [self._snap_points[k] for k in shortlist]
        hit = picking.closest_snap_point(context, points, mw, mouse, at)
        if hit is None:
            return
        k = shortlist[next(j for j, (_kind, co) in enumerate(points) if co is hit[1])]
        width = self._snap_width(k, self._owners_by_distance(context, k))
        if width is None:
            return
        self.width = width
        self._input_str = ""
        self._snap_co = hit[1]

    def _owners_by_distance(self, context, k):
        """Snap candidate ``k``'s (chain, side) owners, the chain nearest it on screen first.

        The chains are ranked with ``core.nearest_chain`` from the candidate's screen
        position. Owners whose chain is not on screen keep their order after the others.
        """
        owners = self._snap_owners[k]
        chains = list(dict.fromkeys(i for i, _side in owners))
        at = self._to_region(context, self._snap_verts[k].co)
        if at is None or len(chains) < 2:
            return owners
        shown = {i: xy for i in chains if (xy := self._chain_xy(context, self._chains[i]))}
        rank = {}
        while shown:
            ids = list(shown)
            pick = ids[core.nearest_chain([shown[i] for i in ids], [self._chains[i].closed for i in ids], at)]
            rank[pick] = len(rank)
            del shown[pick]
        return sorted(owners, key=lambda owner: rank.get(owner[0], len(rank)))

    def _snap_width(self, k, owners=None):
        """The width at which the new loop passes through snap candidate ``k``, or None.

        The first of ``owners`` (by default every band holding the candidate, in
        build order) whose loop reaches it gives the width, signed so that its chain
        is cut on the candidate's side.
        """
        owners = tuple(self._snap_owners[k] if owners is None else owners)
        key = (k, owners, self.use_exact, self.use_collapse)
        if key not in self._snap_reach:
            self._snap_reach[key] = self._reach(k, owners)
        found = self._snap_reach[key]
        if found is None:
            return None
        width, i, side = found
        stored = -1 if self.chain_sides[i:i + 1] == "-" else 1
        return width if side == stored else -width

    def _reach(self, k, owners):
        """(width, chain index, side) of the first of ``owners`` whose loop reaches candidate ``k``, or None."""
        v = self._snap_verts[k]
        for i, side in owners:
            build, slider = self._sides[i][side]
            target = bridge.snap_target(build, v)
            if target is None:
                continue
            try:
                width = slider.snap_width(target, exact=self.use_exact, collapse=self.use_collapse)
            except _CHAIN_SKIPS:
                continue
            if width is not None:
                return width, i, side
        return None

    # ------------------------------------------------------------------
    # Teardown, status and preview
    # ------------------------------------------------------------------

    def _finish(self, context):
        h = getattr(self, "_handle", None)
        if h is not None:
            _ACTIVE_HANDLES.discard(h)
            try:
                safe_handler_remove(h, bpy.types.SpaceView3D, "WINDOW")
            except (ValueError, RuntimeError):
                pass
            self._handle = None
        context.workspace.status_text_set(None)
        if context.area:
            context.area.tag_redraw()
        # Blender keeps finished operator instances alive in the redo stack.
        # Dropping every bmesh-derived reference here stops a later addon
        # reload from dealloc'ing them against freed mesh data.
        self._chains = []
        self._sides = []
        self._snap_verts = []
        self._snap_owners = []
        self._snap_points = []
        self._snap_cos = None
        self._snap_reach = {}
        self._snap_co = None
        self._bvh_cache = {}
        self._preview_segs = []
        self._preview_points = []
        self._clamped = False
        self._preview_key = None
        self._bm = None
        self._obj = None
        self._hud = None
        self._help = None

    def _status_text(self):
        typed = f" | typing: {self._input_str}" if self._input_str else ""
        hint = getattr(self, "_status_hint", "")
        hint = f" | {hint}" if hint else ""
        return (
            f"Smart Edge Slide: width = {self.width:.4f}{typed}{hint} | "
            f"exact width = {'on' if self.use_exact else 'off'} (E) | "
            f"allow collapse = {'on' if self.use_collapse else 'off'} (C) | "
            f"UV stripe = {'on' if self.use_uv_stripe else 'off'} (U) | "
            "[Mouse] drag | [Ctrl] snap to vertex | [Shift] precise | "
            "[F] flip chain side | [Enter/LMB] confirm | [Esc/RMB] cancel"
        )

    def _rebuild_preview(self):
        """Refresh the cached 3D preview when a prop it depends on moved.

        The HUD tick keeps the draw handler firing with the mouse idle, so the
        solve runs here, keyed on every input the preview depends on, and the
        draw callback only projects the cached points.
        """
        key = (self.width, self.use_exact, self.use_collapse, self.chain_sides)
        if key == self._preview_key:
            return
        self._preview_key = key
        builds, cuts = [], []
        for i, found in enumerate(self._sides):
            entry = found.get(self._side(i))
            if entry is None:
                continue
            build, slider = entry
            try:
                cut = slider.solve(abs(self.width), exact=self.use_exact, collapse=self.use_collapse)
            except _CHAIN_SKIPS:
                continue  # execute skips this chain too: draw nothing for it
            builds.append(build)
            cuts.append(cut)
        self._preview_segs, self._preview_points, self._clamped = bridge.preview_layers(builds, cuts)

    def _draw_callback(self, context):
        region_ui = context.region
        rv3d = context.region_data
        if rv3d is None:
            return

        # Guard against an in-place addon reload freeing this operator's RNA
        # struct while the draw handler is still registered.
        try:
            mw = self._obj.matrix_world
        except (ReferenceError, AttributeError):
            h = getattr(self, "_handle", None)
            if h is not None:
                _ACTIVE_HANDLES.discard(h)
                try:
                    safe_handler_remove(h, bpy.types.SpaceView3D, "WINDOW")
                except (ValueError, RuntimeError, ReferenceError):
                    pass
            return

        # Any exception escaping a draw handler repeats every single frame and
        # can wedge the UI, so a failure draws nothing instead.
        try:
            def project(co):
                p = view3d_utils.location_3d_to_region_2d(region_ui, rv3d, mw @ co)
                return None if p is None else Vector((p[0], p[1], 0.0))

            segs = getattr(self, "_preview_segs", None) or ()
            ends = [project(co) for co in segs]
            segs_2d = [p for a, b in zip(ends[0::2], ends[1::2]) if a is not None and b is not None for p in (a, b)]
            points_2d = [p for p in map(project, getattr(self, "_preview_points", None) or ()) if p is not None]
            snap_co = getattr(self, "_snap_co", None)
            snap_2d = [p for p in ([project(snap_co)] if snap_co is not None else []) if p is not None]

            if segs_2d or points_2d or snap_2d:
                # Clamp feedback: the width asked for runs past the limit, so the
                # loop sits at the limit; flag it in the error colour.
                line_role = Role.ERROR_LINE if getattr(self, "_clamped", False) else Role.PREVIEW_LINE
                with draw_scope(blend="ALPHA"):
                    if segs_2d:
                        draw.edges_3d(segs_2d, role=line_role, context=context)
                    if points_2d:
                        draw.points(points_2d, role=Role.PREVIEW_POINT, context=context)
                    if snap_2d:
                        draw.points(snap_2d, role=Role.CLOSEST_POINT, context=context)

            hud = getattr(self, "_hud", None)
            helpo = getattr(self, "_help", None)
            last_event = getattr(self, "_last_event", None)
            if helpo is not None:
                helpo.draw(context, last_event)
            if hud is not None:
                hud.set_header(f"Width: {self.width:.4f}")
                hud.draw(context, last_event)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Execute (topology change)
    # ------------------------------------------------------------------

    def execute(self, context):
        """Cut every chain from the stored props: the width and each chain's side, never the view."""
        me = context.active_object.data
        bm = bmesh.from_edit_mesh(me)

        chains, warnings = bridge.collect_chains(bm)
        for msg in warnings:
            self._skip(msg)
        if not chains:
            if not warnings:
                self.report({'WARNING'}, "Smart Edge Slide: no edges selected")
            return {'CANCELLED'}

        width = abs(self.width)
        # Loop edges are tagged, not kept in a list: a later chain's cut may split
        # one, and edge_split copies the tag onto both halves.
        for e in bm.edges:
            e.tag = False
        edited = False
        stripes = []  # (build, applied, width cut at) of each complete cut, for UV Stripe
        tris = None  # the mesh's triangles for build_band, worked out again only after an edit
        # Once the mesh is edited it gets its update however execute ends: an error
        # escaping a later chain must not leave the edit mesh out of date.
        try:
            for i, src in enumerate(chains):
                if tris is None:
                    tris = bridge.face_triangles(bm)
                build, err = bridge.build_band(bm, src, self._side(i), tris)
                if build is None:
                    self._skip(err)
                    continue
                cutting = False
                try:
                    slider = core.Slider(build.band)
                    cut = slider.solve(width, exact=self.use_exact, collapse=self.use_collapse)
                    if not cut.points:
                        continue
                    # apply_cut raises ValueError only before it edits; past that it returns its failures.
                    cutting = True
                    applied = bridge.apply_cut(bm, build, cut, slider)
                except _CHAIN_SKIPS as exc:
                    # Any other error out of apply_cut may come after it began editing.
                    if cutting and not isinstance(exc, ValueError):
                        edited, tris = True, None
                    self._skip(exc)
                    continue
                edited, tris = True, None  # the cut changed the faces and their indices
                if applied.failures:
                    msg = "; ".join(dict.fromkeys(applied.failures))
                    self.report({'WARNING'}, f"Smart Edge Slide: chain cut incomplete ({msg})")
                    if self.use_uv_stripe:
                        self.report({'WARNING'}, f"Smart Edge Slide: UV Stripe skipped ({msg})")
                elif self.use_uv_stripe:
                    stripes.append((build, applied, cut.width))
                for e in applied.loop_edges:
                    e.tag = True

            # An edited mesh always finishes, so the change gets its update and undo step.
            if not edited:
                self.report({'WARNING'}, "Smart Edge Slide: nothing was cut")
                return {'CANCELLED'}
            if stripes:
                self._uv_stripe(bm, stripes)
            for seq in (bm.verts, bm.edges, bm.faces):
                for elem in seq:
                    elem.select = False
            for e in bm.edges:
                if e.tag:
                    e.select_set(True)
                    e.tag = False
            bm.select_flush_mode()
            return {'FINISHED'}
        finally:
            if edited:
                bmesh.update_edit_mesh(me, loop_triangles=True, destructive=True)

    def _uv_stripe(self, bm, stripes) -> None:
        """Unwrap the strip of every (build, applied, width) cut, in the mode the props set.

        Each strip's old UV placement is read from its own faces before any UV is
        written, while they still hold the UVs the cut interpolated: In Place puts
        every strip back where its own faces were. A strip that cannot be laid out
        is skipped with a warning.
        """
        bm.verts.index_update()  # stripe_for's ids
        bm.faces.index_update()
        strips, faces, contexts = [], {}, []
        for build, applied, width in stripes:
            try:
                strip, strip_faces = bridge.stripe_for(build, applied, width)
            except ValueError as exc:
                self.report({'WARNING'}, f"Smart Edge Slide: UV Stripe skipped ({exc})")
                continue
            strips.append(strip)
            faces.update(strip_faces)
            contexts.append(uv_stripe_bridge.uv_context(bm, applied.strip_faces))
        if strips:
            uv_stripe_bridge.apply_stripes(bm, strips, faces, self.uv_stripe_mode, contexts)
