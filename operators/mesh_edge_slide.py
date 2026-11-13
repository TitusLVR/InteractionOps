"""Edge Slide: cut a new edge loop beside each selected chain of edges.

The loop runs at a set width from the chain, measured in the surface on one side
of it. ``utils/edge_slide_core`` places the loop on a band of faces, and
``mesh_edge_slide_bridge`` builds the bands and the cuts on the mesh.

The modal (``invoke``) drags the width with the mouse, mirroring Inset's:
numeric entry, Shift precision, Ctrl snap to a vertex, F to flip the side of the
chain nearest the cursor, and a themed preview of the new loops. D switches to
the destructive mode (``utils/edge_slide_wave``), where the loop merges,
opens at walls and stops only at open edges; it implies collapse. There a loop
that comes to lie on a row of existing edges and stops (or holds its ends) is
relayed: the slide carries on from that row (``bridge.Relay``), the width adding up.

UV Stripe (``uv_stripe_bridge``) can unwrap each new strip as one straight UV
rectangle once the loops are cut.
"""

import dataclasses
import math
import re
import time
import traceback

import bmesh
import bpy
import numpy as np
from bpy.props import BoolProperty, FloatProperty, StringProperty
from bpy_extras import view3d_utils
from mathutils import Vector

from ..ui.draw import Role, draw_scope, safe_handler_add, safe_handler_remove
from ..ui.draw import primitives as draw
from ..ui.hud import HelpOverlay, HUDItem, HUDOverlay, HUDParam, HUDSection, ItemState, capture_event
from ..utils import picking
from ..utils import edge_slide_core as core
from ..utils import edge_slide_wave as wave
from . import mesh_edge_slide_bridge as bridge
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


# The angle props, in the redo panel's order: (prop, label, range in degrees). The ranges are the props'.
ANGLE_SETTINGS = (
    ("rail_bend", "Rail Bend", (1.0, 89.0)),
    ("end_edge_angle", "End Edge Angle", (1.0, 179.0)),
    ("step_agreement", "Step Agreement", (1.0, 89.0)),
    ("step_difference", "Step Difference", (2.0, 179.0)),
    ("shoot_angle", "Shoot Angle", (0.0, 89.0)),
)
_ANGLE_RANGES = {name: limits for name, _label, limits in ANGLE_SETTINGS}
AUTO_ADJUST_MAX = 8  # Auto Adjust changes a setting at most this many times for one chain in one drag
AUTO_TOLERANCE_MAX = 0.01  # Auto Adjust raises Tolerance to at most this part of the stopped band's size
AUTO_NOTE_SECONDS = 2.0  # the HUD names what Auto Adjust changed for this long, or until its next change
AUTO_NO_HELP = "Auto Adjust: no setting helps here"
AUTO_OFFER = "press Q to let it adjust"  # ends a stop note naming a setting Auto Adjust can change, while it is off

_ACTIVE_HANDLES = set()


def _purge_handles():
    """Remove any stale draw handlers left behind by a previous reload."""
    while _ACTIVE_HANDLES:
        h = _ACTIVE_HANDLES.pop()
        try:
            safe_handler_remove(h, bpy.types.SpaceView3D, "WINDOW")
        except (ValueError, RuntimeError):
            pass


def _degrees_text(angle: float) -> str:
    """An angle prop in degrees for the HUD, to a tenth and without a trailing zero: 30°, 37.5°."""
    return f"{round(math.degrees(angle), 1):g}°"


def _tolerance_text(tolerance: float) -> str:
    """The Tolerance prop for the HUD: 0 picks it automatically."""
    return "Automatic" if tolerance <= 0.0 else f"{tolerance:.3g}"


def _setting_text(setting: str, value: float) -> str:
    """The value of ``setting`` (an angle prop or "tolerance") as the HUD shows it."""
    if setting == "chain_sides":
        return "flipped"
    if setting == "use_collapse":
        return "on" if value else "off"
    return _tolerance_text(value) if setting == "tolerance" else _degrees_text(value)


def _degrees(angle: float) -> int:
    """An angle in whole degrees, rounded: what the measured angles of the stop hints read as."""
    return int(round(math.degrees(angle)))


# Why a chain stops, from the solve's OutOfRoom message past its limit (see ``_stop_hint``): the patterns of the core's
# and the wave's messages, each with the chain vertex it names when it names one.
_END_WALL = re.compile(r"the end wall at vertex (\d+) ends")
_BORDER_PATH = re.compile(r"the border path from vertex (\d+) ends")
_NO_ROOM = re.compile(r"vertex (\d+) has no room")
_WIDTH_AT = re.compile(r" (?:before|at) width [-+.\deE]+")  # the width a message names: the HUD shows the width
_FOLDS = re.compile(r"segment \d+ folds back|the collapsing loop runs out of room")
# The destructive solve's own refusals, where its events lie closer than the Tolerance can tell apart.
_WAVE_REFUSALS = (
    ("misses its partner point", "a segment of the loop misses its partner point"),
    ("leaves the band", "the loop leaves the faces"),
    ("the wave runs out of room", "the loop runs out of room"),
    ("reaches its point", "a merged group finds no point"),
    ("keeps shooting on", "an end keeps shooting on"),
    ("runs out of wall", "an end runs out of wall"),
    ("folds back", "a segment folds back"),
    ("run (nearly) parallel", "two chain edges run parallel"),
    ("run parallel", "two chain edges run parallel"),
)


def _bendable(turn: float | None) -> bool:
    """Whether Rail Bend's range reaches a turn of ``turn`` (None: no turn would do)."""
    return turn is not None and math.ceil(math.degrees(turn)) <= _ANGLE_RANGES["rail_bend"][1]


def _probe(solve, limit: float, scale: float) -> str | None:
    """Why the solve stops at ``limit``: the message of its ``OutOfRoom`` just past it, a little further each try;
    None when it fits there every time."""
    for step in (1e-7, 1e-6, 1e-5, 1e-4):
        try:
            solve(limit + step * scale)
        except core.OutOfRoom as exc:
            return str(exc)
        except _CHAIN_SKIPS:
            return None
    return None


def _band_size(build) -> float:
    """The size of ``build``'s band: the diagonal of its vertices' bounding box."""
    points = list(build.band.verts.values())
    if not points:
        return 0.0
    return math.dist([min(p[k] for p in points) for k in range(3)], [max(p[k] for p in points) for k in range(3)])


class IOPS_OT_edge_slide(bpy.types.Operator):
    """Cut a new edge loop beside the selected edges at a set width"""

    bl_idname = "iops.mesh_edge_slide"
    bl_label = "Edge Slide"
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
        default=0.0,
        soft_min=-10.0,
        soft_max=10.0,
        step=1,
        precision=4,
        subtype="DISTANCE",
        # Not remembered: every launch starts at 0. The redo panel still re-runs from the width last used.
        options={'SKIP_SAVE'},
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
            "stops there (Clamped)"
        ),
        default=True,
    )
    use_destructive: BoolProperty(
        name="Destructive",
        description=(
            "Let the new loop run like a skeleton: vertices that meet merge, walls open the loop, "
            "ends shoot on to a crossing edge, and pieces collapse to a point, a ridge or a tree. Where the loop comes to "
            "lie on a row of existing edges and would stop there, it carries on from that row"
        ),
        default=False,
    )
    use_auto_adjust: BoolProperty(
        name="Auto Adjust",
        description=(
            "When a chain stops, change the setting that stops it (angles, Tolerance) by itself so the slide goes on. "
            "The result can look rough"
        ),
        default=False,
    )
    tolerance: FloatProperty(
        name="Tolerance",
        description=(
            "Destructive mode: points closer than this merge, and events this close together count as one. "
            "0 picks it automatically from the mesh size. Raise it when a messy mesh makes the slide refuse; "
            "the result may be off by up to this much"
        ),
        default=0.0,
        min=0.0,
        soft_max=0.01,
        precision=5,
        subtype='DISTANCE',
    )
    use_uv_stripe: BoolProperty(
        name="UV Stripe",
        description=(
            "Unwrap the faces between the selected edges and each new loop as "
            "one straight, even strip in the active UV map"
        ),
        default=False,
    )
    rail_bend: FloatProperty(
        name="Rail Bend",
        description=(
            "The most a rail path may turn at a vertex, and the most a rail may lean from the middle of the corner, before the slide stops following it"
        ),
        default=math.radians(30.0),
        min=math.radians(_ANGLE_RANGES["rail_bend"][0]),
        max=math.radians(_ANGLE_RANGES["rail_bend"][1]),
        subtype="ANGLE",
    )
    end_edge_angle: FloatProperty(
        name="End Edge Angle",
        description=(
            "How far from the chain an open chain's end edge must leave it to end the new loop there. A lower angle takes shallower edges"
        ),
        default=math.radians(60.0),
        min=math.radians(_ANGLE_RANGES["end_edge_angle"][0]),
        max=math.radians(_ANGLE_RANGES["end_edge_angle"][1]),
        subtype="ANGLE",
    )
    step_agreement: FloatProperty(
        name="Step Agreement",
        description=(
            "How closely the faces on both sides of a step must face the same way to count as its flanks"
        ),
        default=math.radians(30.0),
        min=math.radians(_ANGLE_RANGES["step_agreement"][0]),
        max=math.radians(_ANGLE_RANGES["step_agreement"][1]),
        subtype="ANGLE",
    )
    step_difference: FloatProperty(
        name="Step Difference",
        description=(
            "How far a face must turn away from its flanks to count as part of a step"
        ),
        default=math.radians(60.0),
        min=math.radians(_ANGLE_RANGES["step_difference"][0]),
        max=math.radians(_ANGLE_RANGES["step_difference"][1]),
        subtype="ANGLE",
    )
    shoot_angle: FloatProperty(
        name="Shoot Angle",
        description=(
            "Destructive mode only: how far from square-on to its path the edge an end shoots on to "
            "may be turned. An open edge always qualifies"
        ),
        default=math.radians(30.0),
        min=math.radians(_ANGLE_RANGES["shoot_angle"][0]),
        max=math.radians(_ANGLE_RANGES["shoot_angle"][1]),
        subtype="ANGLE",
    )
    chain_sides: StringProperty(
        description="One + or - per selected chain: the side its new loop goes to",
        default="",
        options={'HIDDEN'},
    )

    def _angles(self) -> core.Angles:
        """The angle props as the core's tolerances; Step Agreement stays under Step Difference."""
        one = math.radians(1.0)
        d = core.Angles()

        def snap(value, default):
            # Props are float32: a value within 1e-6 of its default is the default, exactly.
            return default if abs(value - default) < 1e-6 else value

        step_differ = snap(self.step_difference, d.step_differ)
        return core.Angles(
            rail_bend=snap(self.rail_bend, d.rail_bend),
            end_edge=snap(self.end_edge_angle, d.end_edge),
            step_agree=snap(min(self.step_agreement, step_differ - one), d.step_agree),
            step_differ=step_differ,
            shoot=snap(self.shoot_angle, d.shoot),
        )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        for name in ("width", "use_exact"):
            layout.prop(self, name)
        row = layout.row()
        row.active = not self.use_destructive  # greyed out: the destructive mode implies collapse, as in the HUD
        row.prop(self, "use_collapse")
        layout.prop(self, "use_destructive")
        layout.prop(self, "use_auto_adjust")
        row = layout.row()
        row.active = self.use_destructive  # greyed out: only the destructive mode uses it
        row.prop(self, "tolerance")
        layout.prop(self, "use_uv_stripe")
        row = layout.row()
        row.active = False  # a muted note: the UV Stripe settings live in UV Stripe's own redo panel
        row.label(text="Settings from UV Stripe")
        header, body = layout.panel("IOPS_PT_edge_slide_angles", default_closed=True)
        header.label(text="Angles")
        if body is not None:
            for name in ("rail_bend", "end_edge_angle", "step_agreement", "step_difference"):
                body.prop(self, name)
            row = body.row()
            row.active = self.use_destructive  # greyed out: only the destructive mode uses it
            row.prop(self, "shoot_angle")

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and obj.mode == "EDIT"

    def _skip(self, msg) -> None:
        self.report({'WARNING'}, f"Edge Slide: chain skipped ({msg})")

    def _side(self, i: int) -> int:
        """The band side chain ``i`` is cut on: its stored side, the other one for a negative width."""
        side = -1 if self.chain_sides[i:i + 1] == "-" else 1
        return -side if self.width < 0.0 else side

    def _destructive_for(self, build) -> bool:
        """Whether ``build``'s chain is cut in the destructive mode: D is on, and no face of its band has more than
        ``bridge.DESTRUCTIVE_MAX_FACE_SIDES`` sides (there the chain is cut as with Allow Collapse instead)."""
        return self.use_destructive and bridge.destructive_allowed(build)

    def _mode(self, build) -> dict:
        """The solve's mode keywords for ``build``'s chain: a chain D is off for (``_destructive_for``) collapses."""
        destructive = self._destructive_for(build)
        collapse = self.use_collapse or (self.use_destructive and not destructive)
        return {"exact": self.use_exact, "collapse": collapse, "destructive": destructive}

    def _built_limit(self, bm, build, slider, width: float) -> None:
        """In the destructive mode, once ``width`` reaches the chain's limit: lower that limit to the largest width
        the bridge builds (``bridge.built_limit``), once per chain, side and mode."""
        if not self._destructive_for(build):
            return
        if width < slider.limit(exact=self.use_exact, destructive=True):
            return
        known = (self.use_exact, self.tolerance) in build.built_limits
        bridge.built_limit(bm, build, slider, self.use_exact, self.tolerance)
        if not known and getattr(self, "_snap_reach", None):
            self._snap_reach = {}  # snaps worked out up to the old limit

    def _new_slider(self, band):
        return wave.WaveSlider(band, tolerance=self.tolerance)

    def _relay(self, i: int, side: int):
        """Chain ``i``'s destructive slide on ``side`` with its relays (``bridge.Relay``), made once per modal."""
        key = (i, side)
        if key not in self._relays:
            build, slider = self._sides[i][side]
            self._relays[key] = bridge.Relay(
                self._bm, build, slider, self.tolerance, self._new_slider, self._tris, self._angles())
        return self._relays[key]

    def _solve(self, bm, build, slider, relay, width: float):
        """(build, slider, cut) of a chain at ``width``. In the destructive mode they are the relay leg's that cuts there
        (``bridge.Relay``), at the width past its start; the last leg's limit is lowered to what builds
        (``_built_limit``)."""
        mode = self._mode(build)
        if not mode["destructive"]:
            return build, slider, slider.solve(width, **mode)
        stage = relay.stage_at(width, self.use_exact)
        local = width - stage.offset
        if relay.is_last(stage, self.use_exact):
            self._built_limit(bm, stage.build, stage.slider, local)
        return stage.build, stage.slider, stage.slider.solve(local, **mode)

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
        self._cancel_use_destructive = self.use_destructive
        self._cancel_use_auto_adjust = self.use_auto_adjust
        self._cancel_use_uv_stripe = self.use_uv_stripe
        self._cancel_chain_sides = self.chain_sides
        self._cancel_settings = {name: getattr(self, name) for name in (*_ANGLE_RANGES, "tolerance")}
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

        # The drag is incremental: each move adds its own horizontal step, so
        # Shift, Ctrl, typing and the cursor wrap never jump the value.
        self._initial_width = self.width
        self._last_mouse_x = event.mouse_region_x
        self._warped_to_x = None
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
        self._stops = []  # (chain index, side, build, slider, destructive) of each chain the preview clamps
        self._hints = []  # the HUD's notes on why they stop: (text, error)
        self._hint_key = None
        self._hint_changes = []  # per note: (chain index, side, the change it names or None, the band's size)
        self._auto_counts = {}  # (chain index, side): the changes Auto Adjust made for it in this drag
        self._auto_note = None  # (text, until): the HUD's line on what Auto Adjust last changed
        self._auto_stuck = False  # a chain stops and Auto Adjust has no setting left to change for it
        self._warm_destructive()
        self._rebuild_preview()
        self._auto_adjust()

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

    def _build_sides(self, bm, quiet: bool = False) -> bool:
        """Both sides' band and Slider for every selected chain; False when no chain has either.

        ``self._sides[i]`` maps each side (+1, -1) chain ``self._chains[i]`` can be
        cut on to its (build, Slider). A chain with neither side is skipped with a
        warning, as ``execute`` would skip it. ``quiet``: built again in the modal (an
        angle changed), over the same triangulation and without the warnings again.
        """
        chains, warnings = bridge.collect_chains(bm)
        for msg in [] if quiet else warnings:
            self._skip(msg)
        self._chains, self._sides, self._relays = chains, [], {}
        if not quiet or getattr(self, "_tris", None) is None:
            # One triangulation for every band: nothing edits the mesh before confirm.
            self._tris = bridge.face_triangles(bm)
        tris = self._tris
        for src in chains:
            found, errors = {}, []
            for side in (1, -1):
                build, err = bridge.build_band(bm, src, side, tris, self._angles())
                if build is None:
                    errors.append(err)
                else:
                    found[side] = (build, wave.WaveSlider(build.band, tolerance=self.tolerance))
            if not found and not quiet:
                self._skip("; ".join(dict.fromkeys(errors)))
            self._sides.append(found)
        if any(self._sides):
            return True
        if not chains and not warnings:
            self.report({'WARNING'}, "Edge Slide: no edges selected")
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
        self._hud = HUDOverlay("edge_slide")
        self._hud.title = "Edge Slide"
        self._hud.bind_region(region)
        self._hud.add_param(HUDParam("Width", lambda: self.width, "float", fmt="{:.4f}"))
        self._hud.add_param(HUDParam("Exact Width (E)", lambda: self.use_exact, "bool"))
        # D implies collapse: C reads as on and greyed while D is on, and its own value comes back with D off.
        self._hud.add_param(HUDParam(
            "Allow Collapse / Unclamp (C)", lambda: self.use_collapse or self.use_destructive, "bool",
            active_getter=lambda: not self.use_destructive))
        self._hud.add_param(HUDParam("Destructive (D)", lambda: self.use_destructive, "bool"))
        self._hud.add_param(HUDParam("Auto Adjust (Q)", lambda: self.use_auto_adjust, "bool"))
        self._hud.add_param(HUDParam("UV Stripe (U)", lambda: self.use_uv_stripe, "bool"))
        self._hud.add_param(HUDParam("Clamped", lambda: self._clamped, "bool"))

        self._help = HelpOverlay("edge_slide")
        self._help.add_section(HUDSection("Edge Slide", [
            HUDItem("Adjust width",      "Mouse / Type", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Snap to vertex",    "Ctrl",         ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Exact width",       "E",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Allow collapse",    "C",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Destructive",       "D",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Auto adjust",       "Q",            ItemState.ON, default_state=ItemState.OFF, always_show=True),
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
                        "Edge Slide: bmesh data became invalid — cancelled")
            return {'CANCELLED'}
        except Exception:
            self._finish(context)
            raise

    def _modal(self, context, event):
        """One event (``_modal_event``); then, with Auto Adjust on, the settings that stop a chain (``_auto_adjust``)."""
        result = self._modal_event(context, event)
        if result == {'RUNNING_MODAL'} and self._auto_adjust():
            context.workspace.status_text_set(self._status_text())
            if context.area:
                context.area.tag_redraw()  # the HUD shows the new value and the note at once
        return result

    def _modal_event(self, context, event):
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
                    self._update_width(event, context)
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
                self._warm_destructive()
                self._rebuild_preview()
                context.workspace.status_text_set(self._status_text())
                return {'RUNNING_MODAL'}

            if event.type == "C":
                if not self.use_destructive:  # D implies collapse: C keeps its own value for when D goes off
                    self.use_collapse = not self.use_collapse
                    self._rebuild_preview()
                    context.workspace.status_text_set(self._status_text())
                return {'RUNNING_MODAL'}

            if event.type == "D":
                # The preview solve pays the mode's first wave and limit here, not on the next mouse move.
                self.use_destructive = not self.use_destructive
                self._warm_destructive()
                self._rebuild_preview()
                context.workspace.status_text_set(self._status_text())
                return {'RUNNING_MODAL'}

            if event.type == "Q":  # Auto Adjust: the modal changes what stops a chain (``_auto_adjust``)
                self.use_auto_adjust = not self.use_auto_adjust
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
                self.use_destructive = self._cancel_use_destructive
                self.use_auto_adjust = self._cancel_use_auto_adjust
                self.use_uv_stripe = self._cancel_use_uv_stripe
                self.chain_sides = self._cancel_chain_sides
                for name, value in getattr(self, "_cancel_settings", {}).items():
                    setattr(self, name, value)
                self._finish(context)
                return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def _update_width(self, event, context=None):
        """Add this move's horizontal step to ``width``.

        Each move adds its own step from the last position, scaled by 0.1 while
        Shift is held, so pressing or releasing Shift never jumps the value.
        At the viewport's side edges the cursor is warped to the opposite edge.
        Moves Blender still reports from before the warp land on the far side
        of the region and are ignored, so the wrap never counts a step twice.
        """
        mx = event.mouse_region_x
        region = getattr(context, "region", None) if context is not None else None
        if self._warped_to_x is not None:
            if region is not None and abs(mx - self._warped_to_x) > region.width * 0.5:
                return  # a stale move from before the warp
            self._warped_to_x = None
        step = (mx - self._last_mouse_x) * self._pixel_to_width
        if event.shift:
            step *= 0.1
        self.width += step
        self._last_mouse_x = mx
        if region is None or region.width < 8:
            return
        margin = 2
        if mx <= 0:
            wx = region.width - margin - 1
        elif mx >= region.width - 1:
            wx = margin
        else:
            return
        context.window.cursor_warp(region.x + wx, region.y + event.mouse_region_y)
        self._last_mouse_x = wx
        self._warped_to_x = wx

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
        apply however far the mouse drifted meanwhile as an instant jump.
        """
        self._last_mouse_x = event.mouse_region_x
        self._warped_to_x = None

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
        key = (k, owners, self.use_exact, self.use_collapse, self.use_destructive,
               self.tolerance if self.use_destructive else 0.0)
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
            if not self._destructive_for(build):
                target = bridge.snap_target(build, v)
                if target is None:
                    continue
                try:
                    width = slider.snap_width(target, **self._mode(build))
                except _CHAIN_SKIPS:
                    continue
                if width is not None:
                    return width, i, side
                continue
            # The destructive mode: the first relay leg whose loop reaches the vertex gives the width, past its start.
            try:
                relay = self._relay(i, side)
                stages = relay.stages(self.use_exact)
            except _CHAIN_SKIPS:
                continue
            for k, stage in enumerate(stages):
                # A leg cuts up to where the next one starts: a vertex its own slide reaches only past that is not its.
                span = stages[k + 1].offset - stage.offset if k + 1 < len(stages) else math.inf
                target = bridge.snap_target(stage.build, v)
                if target is None:
                    continue
                try:
                    width = stage.slider.snap_width(target, **self._mode(build))
                    if width is not None and relay.is_last(stage, self.use_exact):
                        top = stage.slider.limit(exact=self.use_exact, destructive=True)
                        self._built_limit(self._bm, stage.build, stage.slider, width)
                        if stage.slider.limit(exact=self.use_exact, destructive=True) < top:  # it came down: again
                            width = stage.slider.snap_width(target, **self._mode(build))
                except _CHAIN_SKIPS:
                    continue
                if width is not None and width <= span:
                    return stage.offset + width, i, side
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
        self._relays = {}
        self._tris = None
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
        self._stops = []
        self._hints = []
        self._hint_key = None
        self._hint_changes = []
        self._auto_counts = {}
        self._bm = None
        self._obj = None
        self._hud = None
        self._help = None

    def _status_text(self):
        typed = f" | typing: {self._input_str}" if self._input_str else ""
        hint = getattr(self, "_status_hint", "")
        hint = f" | {hint}" if hint else ""
        return (
            f"Edge Slide: width = {self.width:.4f}{typed}{hint} | "
            f"exact width = {'on' if self.use_exact else 'off'} (E) | "
            f"allow collapse = {'on' if self.use_collapse or self.use_destructive else 'off'} (C) | "
            f"destructive = {'on' if self.use_destructive else 'off'} (D) | "
            f"auto adjust = {'on' if self.use_auto_adjust else 'off'} (Q) | "
            f"UV stripe = {'on' if self.use_uv_stripe else 'off'} (U) | "
            "[Mouse] drag | [Ctrl] snap to vertex | [Shift] precise | "
            "[F] flip chain side | "
            "[Enter/LMB] confirm | [Esc/RMB] cancel"
        )

    # ------------------------------------------------------------------
    # The settings Auto Adjust changes: the angles and Tolerance
    # ------------------------------------------------------------------

    def _setting_label(self, setting: str) -> str:
        """``setting`` (an angle prop or "tolerance") as the redo panel names it."""
        if setting == "tolerance":
            return "Tolerance"
        if setting == "use_collapse":
            return "Allow Collapse"
        if setting == "chain_sides":
            return "Slide side"
        return next(label for name, label, _limits in ANGLE_SETTINGS if name == setting)

    def _auto_tolerance(self) -> float:
        """The weld Tolerance 0 stands for: the largest of the bands' automatic welds."""
        return max((build.weld for found in self._sides for build, _slider in found.values()), default=1e-6)

    def _rebuild_bands(self) -> bool:
        """Build every band and Slider again for the angles now set (they shape the bands); False when no chain has
        one. The relays, snaps, preview and hints go with them."""
        if not self._build_sides(self._bm, quiet=True):
            return False
        self._tolerance_stale = False  # the new Sliders have it
        self._prepare_snap()
        self._preview_key = None
        self._hint_key = None
        self._warm_destructive()
        self._rebuild_preview()
        return True

    def _retolerate(self) -> None:
        """The Tolerance changed: the Sliders are made again for it (it shapes the waves only, the bands stay), by
        ``_warm_destructive``, so only once D is on: without it nothing uses it."""
        self._tolerance_stale = True
        if self.use_destructive:
            self._preview_key = None
            self._hint_key = None
            self._warm_destructive()
            self._rebuild_preview()

    # ------------------------------------------------------------------
    # Why a chain stops: the HUD's notes
    # ------------------------------------------------------------------

    def _update_hints(self) -> None:
        """The HUD's note per chain the preview clamps (``_stop_hint``), worked out again only when which chains stop,
        or a setting that moves their limits, changed."""
        key = (tuple((i, side) for i, side, *_rest in self._stops), self.use_exact, self.use_collapse,
               self.use_destructive, self.tolerance)
        if key == getattr(self, "_hint_key", None):
            return
        self._hint_key = key
        hints, changes = [], []
        for stop in self._stops:
            try:
                text, error, change = self._stop_hint(*stop)
            except _CHAIN_SKIPS:
                continue
            hints.append((text, error))
            changes.append((stop[0], stop[1], change, _band_size(stop[2])))
        self._hints, self._hint_changes = hints, changes

    def _hint_notes(self) -> list[tuple[str, bool]]:
        """The notes as the HUD shows them: with Auto Adjust off, a note naming a setting it can change ends in
        ``AUTO_OFFER`` in place of that setting's new value."""
        notes = list(getattr(self, "_hints", []))
        if getattr(self, "use_auto_adjust", False):
            return notes
        changes = getattr(self, "_hint_changes", [])
        return [(f"{text.rsplit(': ', 1)[0]}: {AUTO_OFFER}" if error and k < len(changes) and changes[k][2] else text,
                 error) for k, (text, error) in enumerate(notes)]

    def _stop_hint(self, i: int, side: int, build, slider, mode: dict) -> tuple[str, bool, dict | None]:
        """(text, error, change) of the note on why chain ``i`` stops on ``side`` (``_stop_note``), with the change of
        the setting an error note names, {prop: value}, for Auto Adjust; None when it names none, or Allow Collapse."""
        chosen = []
        text, error = self._stop_note(chosen, i, side, build, slider, mode)
        return text, error, (chosen[0] if error and chosen else None)

    def _stop_note(self, chosen: list, i: int, side: int, build, slider, mode: dict) -> tuple[str, bool]:
        """(text, error) of the note on why chain ``i`` stops on ``side``: ``build`` and ``slider`` are the relay leg's
        that cuts at the limit. An error note names the one setting found to let it go on: its key, the way to turn
        it and about how far, tried out on the chain first (``_reach_with``). Where none does, the note only says why.
        The change that setting takes goes to ``chosen``.
        """
        stop = (i, side, build, slider)
        prefix = f"Chain {i + 1} stopped" if len(self._chains) > 1 else "Stopped"
        exact, destructive = self.use_exact, mode["destructive"]
        scale = max((abs(c) for p in build.band.verts.values() for c in p), default=1.0) or 1.0
        refused_now = destructive and (exact, self.tolerance) in build.refused
        reach = self._reach_with(stop, mode, built=refused_now)
        gain = max(1e-5 * scale, 1e-3 * reach)

        def fix(reason: str, candidates) -> tuple[str, bool]:
            for advice, change, trial in candidates:
                try:
                    further = trial()
                except _CHAIN_SKIPS:
                    continue
                if further is not None and further > reach + gain:
                    if change is not None:
                        chosen.append(change)
                    return f"{prefix}: {reason}: {advice}", True
            return f"{prefix}: {reason}", False

        if reach is not None and reach <= 1e-4 * scale:  # no width fits at all: look for a vertex the side wraps round
            wedge = self._wide_wedge(build.band)
            if wedge is not None:
                return fix(f"vertex {wedge[0]} has {_degrees(wedge[1])}° of faces on this side",
                           self._flip_candidates(i, side))

        def tolerance_candidates(refused: bool):
            base = max(self.tolerance, self._auto_tolerance())
            for factor in (4.0, 16.0, 64.0):
                value = base * factor
                yield (f"raise Tolerance to {value:.2g}", {"tolerance": value},
                       lambda value=value: self._reach_with(stop, mode, tolerance=value, built=refused))

        if destructive:
            if refused_now:
                return fix("the cut past here does not build", tolerance_candidates(True))
            limit = slider.limit(exact=exact, destructive=True)
            if slider._used_up(exact) is not None and limit >= slider._final_since(exact) - 1e-6 * scale:
                miss = slider.shoot_misses.get(exact)
                if miss is not None and math.degrees(miss) < _ANGLE_RANGES["shoot_angle"][1]:
                    value = min(math.ceil(math.degrees(miss)), int(_ANGLE_RANGES["shoot_angle"][1]))
                    found = fix(
                        f"an end found no edge to land on; the nearest leans {_degrees(miss)}° from square-on",
                        [(f"raise Shoot Angle to {value}°", {"shoot_angle": math.radians(value)},
                          lambda: self._reach_with(stop, mode, shoot_angle=math.radians(value)))])
                    if found[1]:
                        return found
                cut = slider.solve(limit, exact=exact, destructive=True)
                if any(slider._on_open(p) for p in cut.points):
                    return f"{prefix} at an open edge", False
                return f"{prefix}: the loop is used up", False
            message = _probe(lambda w: slider._solve(w, exact, True, destructive=True), limit, scale)
        else:
            limit = slider.limit(exact=exact, collapse=mode["collapse"])
            message = _probe(lambda w: slider._solve(w, exact, mode["collapse"]), limit, scale)
        if message is None:  # past the limit the solve fits again: a stretch it does not get through
            if destructive:
                return fix("the loop does not get through here", tolerance_candidates(False))
            return f"{prefix}: the loop does not get through here", False

        chain, open_verts = build.band.chain, slider._open_verts()
        if found := _END_WALL.search(message):
            u = int(found.group(1))
            at, turn = slider.end_wall_stop(u == chain[0])
            lean = build.end_leans[0 if u == chain[0] else 1]
            if lean is not None and (note := self._end_edge_fix(fix, u, lean, stop, mode))[1]:
                return note
            if _bendable(turn):
                return self._bend_fix(fix, f"the end wall at vertex {u} turns {_degrees(turn)}° at vertex {at}", turn,
                                      stop, mode)
            return (f"{prefix} at an open edge" if at in open_verts else
                    f"{prefix}: the end wall at vertex {u} ends"), False
        if found := _BORDER_PATH.search(message):
            v = int(found.group(1))
            lean = build.end_leans[0 if v == chain[0] else 1]
            if lean is None:
                return f"{prefix} at an open edge", False
            return self._end_edge_fix(fix, v, lean, stop, mode)
        if found := _NO_ROOM.search(message):
            v = int(found.group(1))
            at, turn = slider.rail_stop(chain.index(v)) if v in chain else (None, None)
            if not _bendable(turn):
                return (f"{prefix} at an open edge" if at in open_verts and at != v else
                        f"{prefix}: vertex {v} has no room"), False
            return self._bend_fix(fix, f"vertex {v} has no room; its rail turns {_degrees(turn)}° at vertex {at}",
                                  turn, stop, mode)
        if destructive:
            reason = next((text for part, text in _WAVE_REFUSALS if part in message), "the loop does not fit")
            return fix(reason, tolerance_candidates(False))
        if _FOLDS.search(message) and not mode["collapse"]:
            return fix("a segment of the loop folds back",
                       [("turn on Allow Collapse (C)", {"use_collapse": True}, lambda: self._reach_with(stop, {**mode, "collapse": True}))])
        return f"{prefix}: {_WIDTH_AT.sub('', message)}", False

    def _wide_wedge(self, band) -> tuple[int, float] | None:
        """(vertex, angle) of the chain vertex whose faces on the band's side add up to a full turn or more, the widest
        one; None when there is none. There the chain doubles back once the faces are laid flat, so the loop's edges
        run parallel and the slide cannot start."""
        bm = self._bm
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        chain, n = band.chain, len(band.chain)
        best = None
        for k in (range(n) if band.closed else range(1, n - 1)):
            v = bm.verts[chain[k]]
            ea = bm.edges.get((v, bm.verts[chain[k - 1]]))
            eb = bm.edges.get((v, bm.verts[chain[(k + 1) % n]]))
            if ea is None or eb is None:
                continue
            face, cur, total = bm.faces[band.side_faces[k - 1]], ea, 0.0
            for _ in range(64):
                loop = next((lp for lp in face.loops if lp.vert == v), None)
                if loop is None:
                    total = None
                    break
                total += loop.calc_angle()
                nxt = loop.link_loop_prev.edge if loop.edge == cur else loop.edge
                if nxt == eb:
                    break
                others = [g for g in nxt.link_faces if g != face]
                if len(others) != 1:
                    total = None
                    break
                face, cur = others[0], nxt
            else:
                total = None
            if total is not None and total >= 2.0 * math.pi - 1e-3 and (best is None or total > best[1]):
                best = (chain[k], total)
        return best

    def _flip_candidates(self, i: int, side: int) -> list:
        """The candidate of ``fix`` that slides chain ``i`` on its other side (F), if it has one."""
        other = self._sides[i].get(-side)
        if other is None:
            return []
        build, slider = other
        sides = list(self.chain_sides)
        sides[i] = "+" if sides[i] == "-" else "-"
        return [("press F to slide the other side", {"chain_sides": "".join(sides)},
                 lambda: self._reach_with((i, -side, build, slider), self._mode(build)))]

    def _end_edge_fix(self, fix, v: int, lean: float, stop: tuple, mode: dict) -> tuple[str, bool]:
        """``fix`` with the End Edge Angle lowered to take the edge at end vertex ``v`` that leans ``lean``."""
        value = max(math.floor(math.degrees(lean)), int(_ANGLE_RANGES["end_edge_angle"][0]))
        return fix(f"the edge at vertex {v} leans {_degrees(lean)}°, too shallow for an end wall",
                   [(f"lower End Edge Angle to {value}°", {"end_edge_angle": math.radians(value)},
                     lambda: self._reach_with(stop, mode, end_edge_angle=math.radians(value)))])

    def _bend_fix(self, fix, reason: str, turn: float, stop: tuple, mode: dict) -> tuple[str, bool]:
        """``fix`` with Rail Bend raised to take a turn of ``turn`` (``_bendable``)."""
        value = math.ceil(math.degrees(turn))
        return fix(reason, [(f"raise Rail Bend to {value}°", {"rail_bend": math.radians(value)},
                             lambda: self._reach_with(stop, mode, rail_bend=math.radians(value)))])

    def _reach_with(self, stop: tuple, mode: dict, tolerance: float | None = None, built: bool = False,
                    **angles) -> float | None:
        """The limit in ``mode`` of the relay leg that stops (``stop``: chain index, side, its build and Slider): with
        the settings now set, or with ``tolerance`` and the angle props in ``angles`` in their place, on a Slider and
        (for ``angles``) a band made for them. ``built``: the destructive limit up to where the cut still builds
        (``bridge.built_limit``). None where the trial has no band: the angles only rebuild a chain's own band, not a
        relay leg's."""
        i, side, build, slider = stop
        exact = self.use_exact
        tol = self.tolerance if tolerance is None else tolerance
        if angles or tolerance is not None:
            if angles:
                if build is not self._sides[i][side][0]:  # a relay leg: its row's band is the relay's to build
                    return None
                saved = {name: getattr(self, name) for name in angles}
                for name, value in angles.items():
                    setattr(self, name, value)
                try:
                    trial = self._angles()
                finally:
                    for name, value in saved.items():
                        setattr(self, name, value)
                build, _err = bridge.build_band(self._bm, self._chains[i], side, self._tris, trial)
                if build is None:
                    return None
            else:  # the chain's own band, with limits of its own: the trial leaves the chain's as they are
                build = dataclasses.replace(build, built_limits={}, refused={})
            slider = wave.WaveSlider(build.band, tolerance=tol)
        if not mode["destructive"]:
            return slider.limit(exact=exact, collapse=mode["collapse"])
        if built and (angles or tolerance is not None):
            # One trial build, at the width the chain's own cut is refused at (or the trial's limit, below it): the
            # setting helps when that cut builds with it.
            width = min(slider.limit(exact=exact, destructive=True), stop[2].refused.get((exact, self.tolerance),
                                                                                         math.inf))
            cut = slider.solve(width, exact=exact, destructive=True)
            return width if not cut.points or bridge._trial_failure(self._bm, build, cut, slider, tol) is None else None
        if built:
            return bridge.built_limit(self._bm, build, slider, exact, tol)
        top = build.refused.get((exact, tol))
        return slider.limit(exact=exact, destructive=True) if top is None else top

    # ------------------------------------------------------------------
    # Auto Adjust (Q): the modal changes what stops a chain by itself
    # ------------------------------------------------------------------

    def _auto_adjust(self) -> bool:
        """With Auto Adjust on, while a chain the preview clamps has a note naming a setting that lets it go on
        (``_update_hints``), apply that change and build again, until no note names one, the setting would leave its
        range (``_apply_change``) or the chain had ``AUTO_ADJUST_MAX`` changes in this drag. True when one was made.

        The notes are worked out only when the clamp state or a setting changed, so a mouse move between clamps
        pays nothing here.
        """
        if not getattr(self, "use_auto_adjust", False) or getattr(self, "_bm", None) is None:
            return False
        counts = getattr(self, "_auto_counts", None)
        if counts is None:
            counts = self._auto_counts = {}
        made, before = [], {}
        while True:
            self._update_hints()
            for i, side, change, size in self._hint_changes:
                if change is None or counts.get((i, side), 0) >= AUTO_ADJUST_MAX:
                    continue
                for name in change:
                    before.setdefault(name, getattr(self, name))
                if self._apply_change(change, size):
                    counts[(i, side)] = counts.get((i, side), 0) + 1
                    made.append(change)
                    break
            else:
                break
        # A chain still stops and no setting is left to change for it: the HUD says so (``_auto_notes``).
        self._auto_stuck = bool(self._hint_changes)
        if made:
            values = {name: value for change in made for name, value in change.items()}
            self._status_hint = "auto adjust: " + ", ".join(
                f"{self._setting_label(name)} {_setting_text(name, value)}" for name, value in values.items())
            self._auto_note = ("Auto Adjust: " + ", ".join(
                ("flipped the slide side" if name == "chain_sides" else
                 f"{'raised' if value > before[name] else 'lowered'} {self._setting_label(name)} to "
                 f"{_setting_text(name, value)}") for name, value in values.items() if value != before[name]),
                time.perf_counter() + AUTO_NOTE_SECONDS)
        return bool(made)

    def _auto_notes(self) -> list[tuple[str, bool]]:
        """The HUD's Auto Adjust line, in plain text: what it last changed, for ``AUTO_NOTE_SECONDS`` or until its next
        change; else, while a chain stops and no setting helps it, ``AUTO_NO_HELP``. None with Auto Adjust off."""
        if not getattr(self, "use_auto_adjust", False):
            return []
        note = getattr(self, "_auto_note", None)
        if note is not None and time.perf_counter() < note[1]:
            return [(note[0], False)]
        return [(AUTO_NO_HELP, False)] if getattr(self, "_auto_stuck", False) else []

    def _apply_change(self, change: dict, size: float) -> bool:
        """Set the one prop of ``change`` and build what it shapes again (``_rebuild_bands``, ``_retolerate``); False,
        and nothing changed, when its value leaves the prop's range (Tolerance: ``AUTO_TOLERANCE_MAX`` of the band's
        ``size``), equals the value now set, or leaves no chain a band."""
        ((name, value),) = change.items()
        old = getattr(self, name)
        if name in ("use_collapse", "chain_sides"):
            if old == value:
                return False
            setattr(self, name, value)
            self._hint_key = None
            self._preview_key = None
            self._rebuild_preview()
            return True
        if name == "tolerance":
            if value <= old or value > AUTO_TOLERANCE_MAX * size:
                return False
            self.tolerance = value
            self._hint_key = None
            self._retolerate()
            return True
        lo, hi = _ANGLE_RANGES[name]
        if not lo - 1e-6 <= math.degrees(value) <= hi + 1e-6 or abs(value - old) < 1e-7:
            return False
        setattr(self, name, value)
        if not self._rebuild_bands():
            setattr(self, name, old)
            self._rebuild_bands()
            return False
        return True

    def _warm_destructive(self):
        """With D on, work out the first wave and limit of every side of every chain, in the exact mode now set.

        The wave of a side costs 0.3 s or more on a big mesh and is kept: paid here (at D on, at invoke with D on,
        at E while D is on), no mouse move pays it, whichever side the width or a Ctrl snap goes to next.
        """
        if not self.use_destructive:
            return
        if getattr(self, "_tolerance_stale", False):  # the Tolerance changed with D off: the Sliders take it now
            self._tolerance_stale = False
            self._sides = [
                {side: (build, wave.WaveSlider(build.band, tolerance=self.tolerance))
                 for side, (build, _slider) in found.items()}
                for found in self._sides]
            self._relays, self._snap_reach, self._preview_key, self._hint_key = {}, {}, None, None
        for i, found in enumerate(self._sides):
            for side, (build, _slider) in found.items():
                if not self._destructive_for(build):
                    continue  # cut as with Allow Collapse: no wave to pay
                try:
                    self._relay(i, side).stages(self.use_exact)  # every relay leg's wave and limit with it
                except _CHAIN_SKIPS:
                    pass  # the preview and execute skip this chain too

    def _rebuild_preview(self):
        """Refresh the cached 3D preview when a prop it depends on moved.

        The HUD tick keeps the draw handler firing with the mouse idle, so the
        solve runs here, keyed on every input the preview depends on, and the
        draw callback only projects the cached points.
        """
        key = (self.width, self.use_exact, self.use_collapse, self.use_destructive,
               self.tolerance if self.use_destructive else 0.0, self.chain_sides)
        if key == self._preview_key:
            return
        self._preview_key = key
        groups = {False: ([], []), True: ([], [])}  # by the destructive mode: (builds, cuts)
        stops = []
        for i, found in enumerate(self._sides):
            entry = found.get(self._side(i))
            if entry is None:
                continue
            build, slider = entry
            mode = self._mode(build)
            try:
                relay = self._relay(i, self._side(i)) if mode["destructive"] else None
                build, stage_slider, cut = self._solve(self._bm, build, slider, relay, abs(self.width))
            except _CHAIN_SKIPS:
                continue  # execute skips this chain too: draw nothing for it
            groups[mode["destructive"]][0].append(build)
            groups[mode["destructive"]][1].append(cut)
            if cut.clamped:
                stops.append((i, self._side(i), build, stage_slider, mode))
        self._preview_segs, self._preview_points, self._clamped = [], [], False
        for destructive, (builds, cuts) in groups.items():
            segs, points, clamped = bridge.preview_layers(
                builds, cuts, destructive=destructive, tolerance=self.tolerance)
            self._preview_segs += segs
            self._preview_points += points
            self._clamped = self._clamped or clamped
        self._stops = stops  # the HUD works out why they stop as it draws (``_update_hints``)

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
                self._update_hints()
                hud.set_notes(*self._hint_notes(), *self._auto_notes())
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
                self.report({'WARNING'}, "Edge Slide: no edges selected")
            return {'CANCELLED'}

        width = abs(self.width)
        # Loop edges are tagged, not kept in a list: a later chain's cut may split
        # one, and edge_split copies the tag onto both halves.
        for e in bm.edges:
            e.tag = False
        edited = False
        lone = []  # the vertices of the pieces of destructive cuts that end as a single point: selected too
        stripes = []  # (build, applied, width cut at) of each complete cut, for UV Stripe
        tris = None  # the mesh's triangles for build_band, worked out again only after an edit
        # Once the mesh is edited it gets its update however execute ends: an error
        # escaping a later chain must not leave the edit mesh out of date.
        try:
            for i, src in enumerate(chains):
                if tris is None:
                    tris = bridge.face_triangles(bm)
                build, err = bridge.build_band(bm, src, self._side(i), tris, self._angles())
                if build is None:
                    self._skip(err)
                    continue
                mode = self._mode(build)
                destructive = mode["destructive"]
                if self.use_destructive and not destructive:
                    self.report({'WARNING'}, (
                        "Edge Slide: Destructive is off for a chain next to a face with more than "
                        f"{bridge.DESTRUCTIVE_MAX_FACE_SIDES} sides"))
                cutting = False
                try:
                    slider = self._new_slider(build.band)
                    relay = bridge.Relay(bm, build, slider, self.tolerance, self._new_slider, tris,
                                         self._angles()) if destructive else None
                    # In the destructive mode the cut is that of the relay leg cutting at the width, built outward from
                    # the leg's chain: the rows before it are existing edges.
                    build, slider, cut = self._solve(bm, build, slider, relay, width)
                    if not cut.points:
                        continue
                    # apply_cut raises ValueError only before it edits; past that it returns its failures.
                    cutting = True
                    applied = bridge.apply_cut(bm, build, cut, slider, destructive=destructive, tolerance=self.tolerance)
                except _CHAIN_SKIPS as exc:
                    # Any other error out of apply_cut may come after it began editing.
                    if cutting and not isinstance(exc, ValueError):
                        edited, tris = True, None
                    self._skip(exc)
                    continue
                except Exception as exc:
                    if not destructive:
                        raise
                    # The destructive mode lets no error out with the mesh half edited: the chain is skipped, named
                    # with the error's type, and the edits made so far get their update.
                    traceback.print_exc()
                    if cutting:
                        edited, tris = True, None
                    self._skip(f"{type(exc).__name__}: {exc}")
                    continue
                edited, tris = True, None  # the cut changed the faces and their indices
                if destructive:
                    on_edges = {v for e in applied.loop_edges for v in e.verts}
                    lone += [v for v in applied.loop_verts if v not in on_edges]
                if applied.failures:
                    msg = "; ".join(dict.fromkeys(applied.failures))
                    self.report({'WARNING'}, f"Edge Slide: chain cut incomplete ({msg})")
                    if self.use_uv_stripe:
                        self.report({'WARNING'}, f"Edge Slide: UV Stripe skipped ({msg})")
                elif self.use_uv_stripe:
                    stripes.append((build, applied, cut.width))
                for e in applied.loop_edges:
                    e.tag = True

            # An edited mesh always finishes, so the change gets its update and undo step.
            if not edited:
                self.report({'WARNING'}, "Edge Slide: nothing was cut")
                return {'CANCELLED'}
            if stripes:
                self._uv_stripe(context, bm, stripes)
            for seq in (bm.verts, bm.edges, bm.faces):
                for elem in seq:
                    elem.select = False
            for e in bm.edges:
                if e.tag:
                    e.select_set(True)
                    e.tag = False
            for v in lone:
                if v.is_valid:
                    v.select_set(True)
            bm.select_flush_mode()
            return {'FINISHED'}
        finally:
            if edited:
                bmesh.update_edit_mesh(me, loop_triangles=True, destructive=True)

    def _uv_stripe(self, context, bm, stripes) -> None:
        """Unwrap the strip of every piece of every (build, applied, width) cut, with UV Stripe's settings.

        A loop the destructive mode opened is several pieces, each with a strip of its own.
        Each strip's old UV placement is read from its own faces before any UV is
        written, while they still hold the UVs the cut interpolated: In Place puts
        every strip back where its own faces were. A strip that cannot be laid out
        is skipped with a warning. The settings are UV Stripe's last-used ones
        (``uv_stripe_bridge.StripeSettings.from_last``): the pieces go through
        ``prepare_strip`` and ``finish_stripes``, as in UV Stripe and Inset; the
        pieces one strip is split into share its Fit scale. Split at Seams and Merge
        Doubles do not apply to the new faces; Active without the active face among them
        lays out In Place, silently.
        """
        bm.verts.index_update()  # stripe_for's ids
        bm.faces.index_update()
        # In the destructive mode an unexpected error skips the strip (or, writing them, the UV Stripe) with a
        # warning naming its type, as a refusal does: it never escapes with the cut made and its UVs half written.
        unexpected = Exception if self.use_destructive else ()
        settings = uv_stripe_bridge.StripeSettings.from_last(context)
        contexts, groups, pieces_all = [], [], []
        group = 0
        for build, applied, width in stripes:
            for piece in range(len(applied.pieces)):
                try:
                    strip, strip_faces = bridge.stripe_for(build, applied, width, piece)
                    pieces, reason = uv_stripe_bridge.prepare_strip(strip, strip_faces, settings.layout,
                                                                    settings.split)
                except ValueError as exc:
                    self.report({'WARNING'}, f"Edge Slide: UV Stripe skipped ({exc})")
                    continue
                except unexpected as exc:
                    self._stripe_error(exc)
                    continue
                if reason:
                    self.report({'WARNING'}, f"Edge Slide: UV Stripe not split ({reason})")
                try:
                    contexts_here = [uv_stripe_bridge.uv_context(bm, list(f.values())) for _s, f in pieces]
                except unexpected as exc:
                    self._stripe_error(exc)
                    continue
                for (strip, strip_faces), stripe_context in zip(pieces, contexts_here):   # one Fit scale per strip
                    contexts.append(stripe_context)
                    groups.append(group)
                    pieces_all.append((strip, strip_faces))
                group += 1
        if pieces_all:
            try:
                uv_stripe_bridge.finish_stripes(bm, pieces_all, contexts, groups, settings)
            except unexpected as exc:
                self._stripe_error(exc)

    def _stripe_error(self, exc: Exception) -> None:
        """Warn that UV Stripe skipped a strip over an unexpected error, named with its type; its traceback goes to
        the console."""
        traceback.print_exception(exc)
        self.report({'WARNING'}, f"Edge Slide: UV Stripe skipped ({type(exc).__name__}: {exc})")
