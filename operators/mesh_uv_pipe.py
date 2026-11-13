"""UV Pipe: unwrap tubes as a straight wall, straight cap rings and cap disks.

The faces are split into parts by ``utils/uv_pipe_core.analyse``: ring seams where
the tube ends or breaks (closed loops sharper than Sharp Angle), cap rings peeled off
flat caps, the disk left in a cap's middle, walls between, and free parts that are
none of these. Each wall gets one lengthwise seam. ``uv_pipe_bridge`` lays every part
out (a wall inside a straight rectangle, a ring as a straight strip, a disk at real
size, a free part by Blender's unwrap), places them with one texel density per
object, packs them into 0-1 and marks the seams.

Scope: the selected faces; with no face selected, every visible face of the meshes
in Edit Mode.

Invoked, the operator is modal and opens with the automatic layout already done.
The edge under the cursor shows the seam loop it would make; a click marks or
unmarks that loop: a lengthwise loop becomes its wall's seam (or goes back to
automatic), a ring or open loop toggles a seam, a cross edge of a ring strip is
that ring's break (or no longer). C does the same for the single edge under the
cursor, Alt + C unmarks the whole loop. Every commit and option change restores the UVs and seams the faces
had and lays them out again; cancel puts them back. The committed loops are kept in
``picks`` for redo.
"""

import json
import math
from dataclasses import dataclass, field

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from mathutils import Vector

from ..ui.draw import Role, safe_handler_add, safe_handler_remove
from ..ui.draw import primitives as draw
from ..ui.hud import HelpOverlay, HUDItem, HUDOverlay, HUDParam, HUDSection, ItemState, capture_event
from ..utils import picking, uv_pipe_core, uv_stripe_select_core
from . import uv_pipe_bridge, uv_stripe_bridge
from .mesh_uv_stripe import _world_context

PICK_KINDS = ("added", "removed", "picked")
ANGLE_STEP = math.radians(5.0)
ANGLE_FINE_STEP = math.radians(1.0)
ANGLE_MIN = math.radians(1.0)
MODE_CYCLE = ["FIT", "IN_PLACE", "ACTIVE"]
MODE_NAMES = {"FIT": "Fit 0–1", "IN_PLACE": "In Place", "ACTIVE": "Active"}
FIT_CYCLE = [item[0] for item in uv_stripe_bridge.ACTIVE_FIT_ITEMS]
FIT_NAMES = {item[0]: item[1] for item in uv_stripe_bridge.ACTIVE_FIT_ITEMS}
OFFSET_CYCLE = [item[0] for item in uv_stripe_bridge.OFFSET_ITEMS]
OFFSET_NAMES = {item[0]: item[1] for item in uv_stripe_bridge.OFFSET_ITEMS}
LAYOUT_CYCLE = [item[0] for item in uv_pipe_bridge.LAYOUT_ITEMS]
LAYOUT_NAMES = {item[0]: item[1] for item in uv_pipe_bridge.LAYOUT_ITEMS}
SOURCE_NAMES = {item[0]: item[1] for item in uv_pipe_bridge.LOOP_SOURCE_ITEMS}
ORIENTATION_NAMES = {item[0]: item[1] for item in uv_stripe_bridge.ORIENTATION_ITEMS}
TOGGLE_TEXT = {  # (kind, already applied: all its edges cut / already the picked seam or break) -> what a toggle does
    ("RING", True): "Remove seam",
    ("RING", False): "Add ring seam",
    ("CUT", True): "Remove seam",
    ("CUT", False): "Add seam",
    ("LENGTH", True): "Automatic wall seam",
    ("LENGTH", False): "Set wall seam",
    ("BREAK", True): "Remove ring break",
    ("BREAK", False): "Set ring break",
}
SEAM_SIDE_ITEMS = [
    ("SHORTEST", "Shortest", "The shortest lengthwise loop of each wall"),
    ("BOTTOM", "Bottom (−Z)", "The lengthwise loop whose faces point most toward world −Z"),
    ("TOP", "Top (+Z)", "The lengthwise loop whose faces point most toward world +Z"),
    ("LEFT", "Left (−X)", "The lengthwise loop whose faces point most toward world −X"),
    ("RIGHT", "Right (+X)", "The lengthwise loop whose faces point most toward world +X"),
    ("FRONT", "Front (−Y)", "The lengthwise loop whose faces point most toward world −Y"),
    ("BACK", "Back (+Y)", "The lengthwise loop whose faces point most toward world +Y"),
]
SEAM_SIDE_CYCLE = [item[0] for item in SEAM_SIDE_ITEMS]
SEAM_SIDE_NAMES = {item[0]: item[1] for item in SEAM_SIDE_ITEMS}
SEAM_SIDE_DIRECTIONS = {
    "SHORTEST": None, "BOTTOM": (0.0, 0.0, -1.0), "TOP": (0.0, 0.0, 1.0), "LEFT": (-1.0, 0.0, 0.0),
    "RIGHT": (1.0, 0.0, 0.0), "FRONT": (0.0, -1.0, 0.0), "BACK": (0.0, 1.0, 0.0),
}
PASS_KEYS = {"N"}  # the sidebar still toggles while the modal runs
NAVIGATION = {"MIDDLEMOUSE", "TRACKPADPAN", "TRACKPADZOOM"}
WHEEL = {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}
MODIFIER_KEYS = {"LEFT_CTRL", "RIGHT_CTRL", "LEFT_SHIFT", "RIGHT_SHIFT", "LEFT_ALT", "RIGHT_ALT", "OSKEY"}
SETTINGS = ("mode", "active_fit", "orientation", "layout", "loop_source", "loop_angle", "sharp_angle", "hard_angle",
            "split_at_bends", "bend_angle", "split_at_seams", "seam_side", "mark_seams", "pack", "offset_axis", "offset_limit",
            "offset_seed", "merge_doubles", "picks")

_ACTIVE_HANDLES = set()


def _purge_handles():
    """Remove any stale draw handlers left behind by a previous reload."""
    while _ACTIVE_HANDLES:
        h = _ACTIVE_HANDLES.pop()
        try:
            safe_handler_remove(h, bpy.types.SpaceView3D, "WINDOW")
        except (ValueError, RuntimeError):
            pass


def _parse_picks(text):
    """``picks`` as {object name: {"added" | "removed" | "picked": [[edge index, ...], ...]}}; anything malformed
    reads as nothing."""
    try:
        data = json.loads(text) if text else {}
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for name, entry in data.items():
        if not isinstance(entry, dict):
            continue
        loops = {}
        for kind in PICK_KINDS:
            raw = entry.get(kind, [])
            if not isinstance(raw, list):
                continue
            loops[kind] = [[i for i in loop if isinstance(i, int) and not isinstance(i, bool)]
                           for loop in raw if isinstance(loop, list)]
        out[str(name)] = loops
    return out


@dataclass
class _Result:
    """What one layout pass did, over every mesh in Edit Mode."""

    selected: int = 0
    done: int = 0
    kinds: dict = field(default_factory=dict)     # part kind -> count
    fitted: bool = False
    unfitted: bool = False
    fallback: int = 0
    first_reason: str | None = None
    warnings: list[str] = field(default_factory=list)
    infos: list[str] = field(default_factory=list)
    doubles: int = 0
    merged: int = 0
    # per object name: what the hover needs from this pass (``_Cache``), so a mouse move never analyses again
    objects: dict = field(default_factory=dict)
    seam_lines: list = field(default_factory=list)     # world-space segment end points, two per segment: every
    #                                                    edge the pass makes a seam (what Mark Seams marks)
    error_lines: list = field(default_factory=list)    # fallback wall seams


@dataclass
class _Cache:
    """One object's last layout pass, for the hover and the commits: world-space dicts, the analysis, lookups."""

    verts: dict
    faces: dict
    nbrs: dict
    uv: dict | None
    analysis: object
    edge_faces: dict                 # edge key -> face ids in scope
    part_of_face: dict               # face id -> part index
    edge_index: dict                 # edge key -> BMEdge.index
    part_nbrs: dict = field(default_factory=dict)        # part index -> neighbours, filled on demand
    seam_edges: set = field(default_factory=set)         # edge keys the pass makes seams

    def stops(self, i):
        return frozenset(v for b in self.analysis.parts[i].boundaries for v in b)

    def neighbours(self, i):
        if i not in self.part_nbrs:
            self.part_nbrs[i] = uv_pipe_core.neighbours(self.analysis.parts[i].faces)
        return self.part_nbrs[i]

    def segments(self, edges):
        out = []
        for a, b in edges:
            if a in self.verts and b in self.verts:
                out += [Vector(self.verts[a]), Vector(self.verts[b])]
        return out


class IOPS_OT_Mesh_UV_Pipe(bpy.types.Operator):
    """Unwrap tubes: the wall as one straight island, cap rings as straight strips, cap centres as disks"""

    bl_idname = "iops.mesh_uv_pipe"
    bl_label = "UV Pipe"
    bl_options = {"REGISTER", "UNDO"}
    is_bindable = True

    mode: EnumProperty(
        name="Mode",
        items=[*uv_stripe_bridge.MODE_ITEMS, uv_stripe_bridge.ACTIVE_MODE_ITEM],
        default="FIT",
    )
    active_fit: EnumProperty(
        name="Fit to Active",
        description="How Active fits the other parts onto the bounding box of the part holding the active face",
        items=uv_stripe_bridge.ACTIVE_FIT_ITEMS,
        default="WIDTH",
    )
    orientation: EnumProperty(
        name="Orientation",
        description="Whether a wall's circumference and a ring's length run along U or along V",
        items=uv_stripe_bridge.ORIENTATION_ITEMS,
        default="HORIZONTAL",
    )
    layout: EnumProperty(
        name="Layout",
        description="How walls are laid out",
        items=uv_pipe_bridge.LAYOUT_ITEMS,
        default="RECTANGLE",
    )
    loop_source: EnumProperty(
        name="Loop Source",
        description="Where the seam loops' angles are measured",
        items=uv_pipe_bridge.LOOP_SOURCE_ITEMS,
        default="GEOMETRY",
    )
    loop_angle: FloatProperty(
        name="Loop Angle",
        description="Smallest angle between consecutive edges of a seam loop; the loop stops at a sharper turn",
        subtype="ANGLE",
        default=math.radians(120.0),
        min=math.radians(1.0),
        max=math.pi,
    )
    sharp_angle: FloatProperty(
        name="Sharp Angle",
        description="Mean angle between the faces along a closed loop from which the loop is a ring seam",
        subtype="ANGLE",
        default=math.radians(60.0),
        min=math.radians(1.0),
        max=math.pi,
    )
    hard_angle: FloatProperty(
        name="Hard Edge Angle",
        description="Angle between faces from which an edge cuts a part that is not a tube; used when the mesh has "
                    "no edges marked sharp",
        subtype="ANGLE",
        default=math.radians(30.0),
        min=math.radians(1.0),
        max=math.pi,
    )
    split_at_bends: BoolProperty(
        name="Split at Bends",
        description="Cut a wall with a ring seam where the tube has turned by the bend angle",
        default=False,
    )
    bend_angle: FloatProperty(
        name="Bend Angle",
        description="Turn of the tube, summed since the last cut, at which a wall is cut",
        subtype="ANGLE",
        default=math.radians(45.0),
        min=math.radians(1.0),
        max=math.pi,
    )
    split_at_seams: BoolProperty(
        name="Split at Seams",
        description="Cut at the seams already on the mesh; a seam joining a wall's two ends is that wall's seam",
        default=False,
    )
    seam_side: EnumProperty(
        name="Seam Side",
        description="Where the automatic lengthwise seam of each wall is placed: the shortest loop, or the loop whose "
                    "faces point most toward a world direction (a seam you pick overrides it)",
        items=SEAM_SIDE_ITEMS,
        default="SHORTEST",
    )
    mark_seams: BoolProperty(
        name="Mark Seams",
        description="Make the seams follow the parts: mark every part outline, wall seam and ring cut, clear the rest",
        default=True,
    )
    pack: BoolProperty(
        name="Pack",
        description="In Fit 0–1, pack the islands into 0–1 without rotating them and with one shared scale",
        default=True,
    )
    offset_axis: EnumProperty(
        name="Random Offset",
        description="Shift the laid-out parts by random amounts (not applied when Fit 0–1 packs them)",
        items=uv_stripe_bridge.OFFSET_ITEMS,
        default="NONE",
    )
    offset_limit: FloatProperty(
        name="Offset Limit",
        description="Largest random shift, in UV units; each part moves by a random amount between minus and plus this",
        default=0.25,
        min=0.0,
        soft_max=1.0,
        step=1,
        precision=3,
    )
    offset_seed: IntProperty(
        name="Offset Seed",
        description="Change to get another random arrangement",
        default=0,
        min=0,
    )
    merge_doubles: BoolProperty(
        name="Merge Doubles",
        description="Merge the doubled vertices found in the faces before laying them out",
        default=True,
    )
    # The loops committed in the interactive mode, as JSON {object name: {"added": [[edge index, ...], ...],
    # "removed": [...], "picked": [...]}}: kept for redo, never saved as a last-used value.
    picks: StringProperty(
        name="Committed Loops",
        description="The ring seams added and removed and the lengthwise seams picked in the interactive mode",
        default="",
        options={"HIDDEN", "SKIP_SAVE"},
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
        row.active = self.mode == "ACTIVE"
        row.prop(self, "active_fit")
        for name in ("orientation", "layout", "loop_source", "loop_angle", "sharp_angle", "hard_angle",
                     "split_at_bends"):
            layout.prop(self, name)
        row = layout.row()
        row.enabled = self.split_at_bends
        row.prop(self, "bend_angle")
        for name in ("split_at_seams", "seam_side", "mark_seams"):
            layout.prop(self, name)
        row = layout.row()
        row.active = self.mode == "FIT"
        row.prop(self, "pack")
        layout.prop(self, "offset_axis")
        col = layout.column()
        col.active = self.offset_axis != "NONE" and not (self.mode == "FIT" and self.pack)
        col.prop(self, "offset_limit")
        col.prop(self, "offset_seed")
        layout.prop(self, "merge_doubles")

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _merge_doubles(self, bm, obj, merge, in_scope):
        """Count the doubled vertices of the faces in scope, per edge-connected island, and with ``merge`` weld
        them (as UV Stripe does); the count. Faces in scope that the weld rebuilds stay selected."""
        bm.verts.index_update()
        bm.verts.ensure_lookup_table()
        scoped = [f for f in bm.faces if in_scope(f)]
        bm.faces.index_update()
        ids = {f.index: tuple(v.index for v in f.verts) for f in scoped}
        verts = {v.index: tuple(obj.matrix_world @ v.co) for f in scoped for v in f.verts}
        targets = {}
        for island in uv_stripe_select_core.face_islands(ids):
            tol = uv_stripe_select_core.island_tolerance(verts, island)
            targets.update(uv_stripe_select_core.doubled_vertices(verts, island, tol))
        if merge and targets:
            was_selected = any(f.select for f in scoped)
            kept = {v for f in scoped for v in f.verts if v.index not in targets}
            bmesh.ops.weld_verts(bm, targetmap={bm.verts[v]: bm.verts[to] for v, to in targets.items()})
            if was_selected:
                for f in bm.faces:
                    if not f.hide and all(v in kept for v in f.verts):
                        f.select_set(True)
        return len(targets)

    def _lay_out(self, context, merge=False):
        """Analyse and lay out the faces in scope of every mesh in Edit Mode; returns a ``_Result``.

        ``merge`` first welds the doubled vertices in scope (Merge Doubles: execute and confirm only)."""
        result = _Result()
        picks = _parse_picks(getattr(self, "picks", ""))
        objects = [o for o in context.objects_in_mode_unique_data if o.type == "MESH"]
        meshes = [o.data for o in objects]
        any_selected = any(f.select and not f.hide for o in objects for f in bmesh.from_edit_mesh(o.data).faces)

        def in_scope(f):
            return not f.hide and (f.select or not any_selected)

        settings = uv_pipe_bridge.PipeSettings.from_operator(self)
        snapshots = {me.name_full: (had, uvs) for me, had, uvs, _seams in getattr(self, "_snapshot", None) or ()}
        for obj in objects:
            me = obj.data
            bm = bmesh.from_edit_mesh(me)
            # the committed loops name edges by index: take hold of the edges before a weld renumbers them
            bm.edges.index_update()
            bm.edges.ensure_lookup_table()
            held = {kind: [[bm.edges[i] for i in loop if 0 <= i < len(bm.edges)]
                           for loop in picks.get(obj.name, {}).get(kind, [])] for kind in PICK_KINDS}
            found = self._merge_doubles(bm, obj, merge, in_scope)
            if merge:
                result.merged += found
            else:
                result.doubles += found
            bm.verts.index_update()
            bm.edges.index_update()
            bm.faces.index_update()
            bm.faces.ensure_lookup_table()
            loops = {kind: [tuple(uv_stripe_select_core._edge(e.verts[0].index, e.verts[1].index)
                                  for e in loop if e.is_valid) for loop in held[kind]] for kind in PICK_KINDS}
            matrix = obj.matrix_world
            verts, ids = uv_pipe_bridge.mesh_dicts(bm, matrix, in_scope)
            if not ids:
                continue
            result.selected += 1
            scoped = [bm.faces[fid] for fid in ids]
            existing = uv_pipe_bridge.seam_edges(bm, scoped) if self.split_at_seams else frozenset()
            uv = None
            if self.loop_source == "UV":
                snap = snapshots.get(me.name_full)
                if snap is None:
                    uv = uv_pipe_bridge.single_uvs(bm, faces=scoped)
                elif snap[0]:          # the modal measures in the layout the mesh had when it started
                    uv = uv_pipe_bridge.single_uvs(bm, snapshot_uvs=snap[1], faces=scoped)
            analysis = uv_pipe_core.analyse(
                verts, ids, loop_angle=self.loop_angle, sharp_angle=self.sharp_angle,
                bend_angle=self.bend_angle if self.split_at_bends else None, existing=existing,
                added={e for loop in loops["added"] for e in loop},
                removed={e for loop in loops["removed"] for e in loop},
                picked=[loop for loop in loops["picked"] if loop], uv=uv,
                seam_side=SEAM_SIDE_DIRECTIONS[self.seam_side], sharp=uv_pipe_bridge.sharp_edges(bm, scoped),
                hard_angle=self.hard_angle)
            layouts = uv_pipe_bridge.lay_out_parts(bm, analysis, verts, self.layout, mesh=me, meshes=meshes)
            contexts = [_world_context(uv_stripe_bridge.uv_context(bm, list(lay.faces.values())),
                                       list(lay.faces.values()), matrix) for lay in layouts]
            active_face = bm.faces.active if self.mode == "ACTIVE" else None
            holds_active = any(active_face is not None and lay.faces.get(active_face.index) is active_face
                               for lay in layouts)
            fitted = uv_pipe_bridge.finish_pipe(bm, layouts, settings, contexts, mesh=me, meshes=meshes)
            result.fitted |= fitted
            result.unfitted |= holds_active and not fitted
            cache = _Cache(
                verts, ids, uv_pipe_core.neighbours(ids), uv, analysis, uv_pipe_core._edge_faces(ids),
                {fid: i for i, part in enumerate(analysis.parts) for fid in part.faces},
                {uv_stripe_select_core._edge(e.verts[0].index, e.verts[1].index): e.index
                 for f in scoped for e in f.edges})
            result.objects[obj.name] = cache
            marked, _cleared = uv_pipe_bridge.seam_split(layouts)
            cache.seam_edges = {uv_stripe_select_core._edge(e.verts[0].index, e.verts[1].index) for e in marked}
            result.seam_lines += cache.segments(sorted(cache.seam_edges))
            result.error_lines += cache.segments(
                sorted(e for i in analysis.fallback if i in analysis.seams for e in analysis.seams[i].edges()))
            result.done += len(layouts)
            result.fallback += len(analysis.fallback)
            for lay in layouts:
                result.kinds[lay.kind] = result.kinds.get(lay.kind, 0) + 1
                if lay.notice:
                    result.infos.append(f"UV Pipe: {lay.notice}")
            result.warnings += [f"UV Pipe: {w}" for w in analysis.warnings]
        if result.fallback:
            result.warnings.append(f"UV Pipe: {result.fallback} wall seam(s) are a fallback path: no lengthwise "
                                   "loop at this Loop Angle")
        if self.mode == "ACTIVE" and result.done and (result.unfitted or not result.fitted):
            result.infos.append("UV Pipe: no active face to fit to; laid out In Place")
        if result.merged:
            result.infos.append(f"UV Pipe: merged {result.merged} doubled vertices")
        if result.doubles:
            result.warnings.append(f"UV Pipe: {result.doubles} doubled vertices; turn on Merge Doubles or use "
                                   "Merge by Distance")
        return result

    def _summary(self, result):
        k = result.kinds
        text = f"{k.get('WALL', 0)} wall(s), {k.get('RING', 0)} ring(s), {k.get('DISK', 0)} disk(s)"
        if k.get("FREE"):
            text += f", {k['FREE']} free part(s)"
        return text

    def _report_result(self, result):
        """Report the pass; returns the operator's result set."""
        if not result.selected:
            self.report({"WARNING"}, "UV Pipe: no faces to unwrap")
            return {"CANCELLED"}
        if not result.done:
            self.report({"WARNING"}, f"UV Pipe: nothing laid out ({result.first_reason})")
            return {"CANCELLED"}
        for message in dict.fromkeys(result.infos):
            self.report({"INFO"}, message)
        for message in dict.fromkeys(result.warnings):
            self.report({"WARNING"}, message)
        self.report({"INFO"}, f"UV Pipe: {self._summary(result)}")
        return {"FINISHED"}

    def execute(self, context):
        result = self._lay_out(context, merge=self.merge_doubles)
        if result.done:
            for obj in context.objects_in_mode_unique_data:
                if obj.type == "MESH":
                    bmesh.update_edit_mesh(obj.data)
        return self._report_result(result)

    # ------------------------------------------------------------------
    # Snapshot: what every layout starts from, and what cancel puts back
    # ------------------------------------------------------------------

    def _take_snapshot(self, context):
        """Per mesh: whether it had a UV layer, the loop UVs and the edge seam flags of the faces in scope."""
        self._snapshot = []
        objects = [o for o in context.objects_in_mode_unique_data if o.type == "MESH"]
        bms = [(o.data, bmesh.from_edit_mesh(o.data)) for o in objects]
        any_selected = any(f.select and not f.hide for _me, bm in bms for f in bm.faces)
        for me, bm in bms:
            bm.faces.index_update()
            bm.edges.index_update()
            layer = bm.loops.layers.uv.active
            faces = [f for f in bm.faces if not f.hide and (f.select or not any_selected)]
            uvs = {}
            if layer is not None:
                uvs = {(f.index, k): tuple(lp[layer].uv) for f in faces for k, lp in enumerate(f.loops)}
            seams = {e.index: e.seam for f in faces for e in f.edges}
            self._snapshot.append((me, layer is not None, uvs, seams))

    def _restore_snapshot(self, update=True):
        """Put the snapshot back: UVs, seams, and no UV layer where there was none."""
        for me, had_layer, uvs, seams in getattr(self, "_snapshot", None) or ():
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

    def _has_uv_source(self):
        """Loop Source UV is available: a mesh in the snapshot had a UV layer."""
        return any(had for _me, had, _uvs, _seams in getattr(self, "_snapshot", None) or ())

    def _relayout(self, context):
        """Restore the snapshot and lay out again with the current options and committed loops."""
        self._restore_snapshot(update=False)
        self._result = self._lay_out(context)
        for me, *_rest in self._snapshot:
            bmesh.update_edit_mesh(me)
        if getattr(context, "area", None):
            context.area.tag_redraw()
        self._show_status(context)

    def _show_status(self, context):
        try:
            context.workspace.status_text_set(self._status_text())
        except AttributeError:
            pass

    # ------------------------------------------------------------------
    # Loops and edges: hover, mark / unmark, stepping the wall seam
    # ------------------------------------------------------------------

    def _classify(self, obj, key):
        """The loop through edge ``key`` (sorted vertex-index pair) of ``obj`` and its kind, from the last pass.

        "BREAK" when the edge lies between two faces of a ring strip; else the loop traced on all faces in scope
        is "RING" when it closes; else, on an edge inside a wall, the loop traced in that wall up to its
        boundaries is "LENGTH" when it joins two of them; any other loop is an open "CUT": the loop traced on all
        faces in scope by Loop Angle alone, so it runs through the seams it crosses and a seam's own edges all give
        the whole seam. Every kind can be committed. Returns (loop, kind, part index or None), or None when the
        edge is not in scope."""
        cache = getattr(self, "_result", None) or _Result()
        cache = cache.objects.get(obj.name)
        if cache is None or key not in cache.edge_faces:
            return None
        parts = {cache.part_of_face[f] for f in cache.edge_faces[key]}
        inner = len(cache.edge_faces[key]) == 2 and len(parts) == 1
        part = next(iter(parts)) if inner else None
        if part is not None and cache.analysis.parts[part].kind == "RING":
            return uv_pipe_core.Loop(list(key), False), "BREAK", part
        loop = uv_pipe_core.trace_loop(cache.verts, cache.nbrs, key, self.loop_angle, uv=cache.uv)
        if loop.closed:
            return loop, "RING", None
        if part is not None and cache.analysis.parts[part].kind == "WALL":
            inside = uv_pipe_core.trace_loop(cache.verts, cache.neighbours(part), key, self.loop_angle,
                                             cache.stops(part), cache.uv)
            if uv_pipe_core.loop_kind(inside, cache.analysis.parts[part]) == "LENGTH":
                return inside, "LENGTH", part
        return loop, "CUT", part

    def _hit(self, context, event):
        """(object, face index) under the cursor among the faces of the last pass, or None."""
        region = getattr(context, "region", None)
        rv3d = getattr(context, "region_data", None)
        result = getattr(self, "_result", None)
        if region is None or rv3d is None or result is None or not result.objects:
            return None
        objects = [o for o in context.objects_in_mode_unique_data if o.type == "MESH" and o.name in result.objects]
        if not objects:
            return None
        coord = (event.mouse_region_x, event.mouse_region_y)
        hit = picking.raycast_edit_meshes(context, coord, objects, cache=getattr(self, "_pick_cache", None),
                                          region=region, rv3d=rv3d)
        if not hit[0] or hit[3] not in result.objects[hit[4].name].part_of_face:
            return None
        return hit[4], hit[3]

    def _hover_loop(self, context, event):
        """(object, loop, kind, edge key) of the edge under the cursor (the face's edge nearest on screen) and its
        loop, or None."""
        found = self._hit(context, event)
        if found is None:
            return None
        obj, face_index = found
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        if not 0 <= face_index < len(bm.faces):
            return None
        edges = list(bm.faces[face_index].edges)
        coord = (event.mouse_region_x, event.mouse_region_y)
        k, _distance = picking.closest_edge_screen(context, edges, obj.matrix_world, coord)
        if k is None:
            return None
        key = uv_stripe_select_core._edge(edges[k].verts[0].index, edges[k].verts[1].index)
        classified = self._classify(obj, key)
        return None if classified is None else (obj, classified[0], classified[1], key)

    def _part_under_cursor(self, context, event):
        """(object, part index) of the face under the cursor, or None."""
        found = self._hit(context, event)
        if found is None:
            return None
        obj, face_index = found
        return obj, self._result.objects[obj.name].part_of_face[face_index]

    def _update_hover(self, context, event):
        self._hover = self._hover_loop(context, event)

    def _cache(self, obj):
        return (getattr(self, "_result", None) or _Result()).objects.get(obj.name)

    def _edge_entry(self, hover):
        """The single edge of ``hover`` as (object, one-edge loop, kind): "BREAK" between two faces of a ring strip,
        else "CUT"; None when nothing is hovered."""
        if hover is None or len(hover) < 4:
            return None
        obj, key = hover[0], hover[3]
        cache = self._cache(obj)
        if cache is None or key not in cache.edge_faces:
            return None
        faces = cache.edge_faces[key]
        parts = {cache.part_of_face[f] for f in faces}
        ring = len(faces) == 2 and len(parts) == 1 and cache.analysis.parts[next(iter(parts))].kind == "RING"
        return obj, uv_pipe_core.Loop(list(key), False), "BREAK" if ring else "CUT"

    def _entry(self, obj):
        """(picks, this object's entry with every kind present, the picks as JSON before any change)."""
        picks = _parse_picks(getattr(self, "picks", ""))
        entry = picks.setdefault(obj.name, {})
        for name in PICK_KINDS:
            entry.setdefault(name, [])
        return picks, entry, json.dumps(picks, sort_keys=True)

    def _apply(self, context, picks, before):
        """Store ``picks`` and lay out again when they differ from ``before``; returns whether they did."""
        after = json.dumps(picks, sort_keys=True)
        if after == before:
            return False
        self.picks = after
        self._relayout(context)
        return True

    def _set_cut(self, context, obj, edges, mark):
        """Make ``edges`` (edge keys) cuts (``mark``) or no cuts, in as few picks as that takes.

        Mark: the edges leave ``removed``; those that are still no cut are added. Unmark (only the edges that are
        cuts now): they leave ``added``; those that are still cuts for an automatic reason (ring, peel, bend or
        hard edge) go to ``removed``. Returns whether ``picks`` changed."""
        cache = self._cache(obj)
        if cache is None:
            return False
        index = {cache.edge_index[e]: e for e in edges if e in cache.edge_index}
        if not index:
            return False

        def without(loops, drop):
            return [kept for kept in ([i for i in lp if i not in drop] for lp in loops) if kept]

        changed = False
        if mark:
            picks, entry, before = self._entry(obj)
            entry["removed"] = without(entry["removed"], index)
            changed |= self._apply(context, picks, before)
            cuts = self._cache(obj).analysis.cuts
            missing = sorted(i for i, e in index.items() if e not in cuts)
            if missing:
                picks, entry, before = self._entry(obj)
                entry["added"].append(missing)
                changed |= self._apply(context, picks, before)
            return changed
        current = {i for i, e in index.items() if e in cache.analysis.cuts}
        if not current:
            return False
        picks, entry, before = self._entry(obj)
        entry["added"] = without(entry["added"], current)
        changed |= self._apply(context, picks, before)
        cuts = self._cache(obj).analysis.cuts
        still = sorted(i for i in current if index[i] in cuts)
        if still:
            picks, entry, before = self._entry(obj)
            entry["removed"].append(still)
            changed |= self._apply(context, picks, before)
        return changed

    def _set_pick(self, context, obj, loop, kind, on):
        """Make the LENGTH / BREAK ``loop`` the user's pick (``on``: replacing the picks inside the same part) or drop
        that pick. Returns whether ``picks`` changed."""
        cache = self._cache(obj)
        indices = self._indices(obj, loop)
        if cache is None or not indices:
            return False
        pick = indices if kind == "LENGTH" else indices[:1]
        picks, entry, before = self._entry(obj)
        entry["picked"] = [lp for lp in entry["picked"] if set(lp) != set(pick)]
        if on:
            parts = {cache.part_of_face[f] for e in loop.edges() for f in cache.edge_faces.get(e, ())}
            inside = set()
            for i in parts:
                inside |= {cache.edge_index[e] for e in uv_pipe_core._inner_edges(cache.analysis.parts[i])
                           if e in cache.edge_index}
            entry["picked"] = [lp for lp in entry["picked"] if not set(lp) <= inside]
            entry["picked"].append(pick)
        return self._apply(context, picks, before)

    def _toggle(self, context, obj, loop, kind):
        """Mark ``loop`` or take its mark off (LMB on a loop, C on an edge); returns whether ``picks`` changed.

        RING and CUT: a loop whose edges are all cuts is unmarked, any other marked (``_set_cut``). LENGTH (a wall's
        seam) and BREAK (a ring's break): the loop that already is the user's pick is dropped, any other becomes the
        pick (``_set_pick``)."""
        if kind in ("RING", "CUT"):
            cache = self._cache(obj)
            if cache is None:
                return False
            return self._set_cut(context, obj, loop.edges(), not set(loop.edges()) <= cache.analysis.cuts)
        return self._set_pick(context, obj, loop, kind, not self._is_picked(obj, loop, kind))

    def _toggle_loop(self, context):
        """LMB: toggle the loop under the cursor."""
        hover = getattr(self, "_hover", None)
        return hover is not None and self._toggle(context, *hover[:3])

    def _toggle_edge(self, context):
        """C: toggle the single edge under the cursor."""
        entry = self._edge_entry(getattr(self, "_hover", None))
        return entry is not None and self._toggle(context, *entry)

    def _unmark(self, context):
        """Alt + C: take the mark off the whole loop under the cursor. RING / CUT: its edges that are cuts stop
        being cuts (``_set_cut``), the rest is left alone; LENGTH / BREAK: the user's pick of it is dropped. Lays
        out again only when ``picks`` changed; returns whether they did."""
        hover = getattr(self, "_hover", None)
        if hover is None:
            return False
        obj, loop, kind = hover[:3]
        if kind in ("RING", "CUT"):
            return self._set_cut(context, obj, loop.edges(), False)
        return self._is_picked(obj, loop, kind) and self._set_pick(context, obj, loop, kind, False)

    def _indices(self, obj, loop):
        """The mesh edge indices of ``loop`` in the last pass, sorted; None when an edge is not in it."""
        cache = (getattr(self, "_result", None) or _Result()).objects.get(obj.name)
        if cache is None or not all(e in cache.edge_index for e in loop.edges()):
            return None
        return sorted(cache.edge_index[e] for e in loop.edges())

    def _is_picked(self, obj, loop, kind):
        """Whether the LENGTH / BREAK ``loop`` is already the user's pick."""
        indices = self._indices(obj, loop)
        if not indices:
            return False
        own = set(indices if kind == "LENGTH" else indices[:1])
        entry = _parse_picks(getattr(self, "picks", "")).get(obj.name, {})
        return any(set(lp) == own for lp in entry.get("picked", []))

    def _cycle_seam(self, context, obj, part_index, step):
        """Make the next (``step`` 1) or previous (-1) lengthwise loop round the wall ``part_index`` its seam
        (``uv_pipe_core.wall_candidates``, in their order round the wall); returns whether it changed."""
        result = getattr(self, "_result", None) or _Result()
        cache = result.objects.get(obj.name)
        if cache is None or not 0 <= part_index < len(cache.analysis.parts):
            return False
        part = cache.analysis.parts[part_index]
        if part.kind != "WALL":
            return False
        candidates = uv_pipe_core.wall_candidates(cache.verts, part, self.loop_angle, cache.uv)
        if not candidates:
            return False
        keys = [frozenset(c.edges()) for c in candidates]
        current = cache.analysis.seams.get(part_index)
        current = frozenset(current.edges()) if current is not None else None
        at = keys.index(current) if current in keys else (-1 if step > 0 else 0)
        chosen = candidates[(at + step) % len(candidates)]
        self._set_pick(context, obj, chosen, "LENGTH", True)
        return True

    def _drop_wall_picks(self):
        """Drop the picked loops lying in a WALL part of the last pass (hand-picked and Alt + Wheel wall seams), so
        Seam Side takes effect again; ring breaks and the added and removed ring seams stay."""
        result = getattr(self, "_result", None) or _Result()
        picks = _parse_picks(getattr(self, "picks", ""))
        changed = False
        for name, entry in picks.items():
            cache = result.objects.get(name)
            if cache is None or not entry.get("picked"):
                continue
            walls = set()
            for part in cache.analysis.parts:
                if part.kind == "WALL":
                    walls |= {cache.edge_index[e] for e in uv_pipe_core._inner_edges(part) if e in cache.edge_index}
            kept = [lp for lp in entry["picked"] if not (lp and set(lp) <= walls)]
            if len(kept) != len(entry["picked"]):
                entry["picked"] = kept
                changed = True
        if changed:
            self.picks = json.dumps(picks, sort_keys=True)

    # ------------------------------------------------------------------
    # Modal
    # ------------------------------------------------------------------

    def _start(self, context):
        """Snapshot and the automatic layout; False (reported, restored) when nothing can be laid out."""
        self._take_snapshot(context)
        self._cancel = {name: getattr(self, name) for name in SETTINGS}
        if not self._has_uv_source():
            self.loop_source = "GEOMETRY"
        self._hover = None
        self._pick_cache = {}
        self._relayout(context)
        if not self._result.done:
            self._restore_snapshot()
            self._report_result(self._result)
            return False
        if self._result.doubles:
            if self.merge_doubles:
                self.report({"INFO"}, f"UV Pipe: {self._result.doubles} doubled vertices, merged on finish")
            else:
                self.report({"WARNING"}, f"UV Pipe: {self._result.doubles} doubled vertices; turn on Merge Doubles")
        return True

    def invoke(self, context, event):
        _purge_handles()
        self._handle = self._handle_view = None
        if not self._start(context):
            return {"CANCELLED"}
        self._build_overlays(context.region)
        self._last_event = capture_event(event, getattr(self, "_last_event", None))
        self._add_handlers(context)
        self._show_status(context)
        context.window_manager.modal_handler_add(self)
        if context.area:
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def _loop_text(self, entry):
        """What a toggle does to the (object, loop, kind, ...) ``entry``, for the HUD; "None" without one."""
        if entry is None:
            return "None"
        obj, loop, kind = entry[:3]
        if kind in ("RING", "CUT"):
            cache = self._cache(obj)
            done = cache is not None and set(loop.edges()) <= cache.analysis.cuts
        else:
            done = self._is_picked(obj, loop, kind)
        return TOGGLE_TEXT[(kind, done)]

    def _edge_text(self):
        """What C does to the edge under the cursor."""
        return self._loop_text(self._edge_entry(getattr(self, "_hover", None)))

    def _preview_points(self):
        """The world-space segment end points the draw callback shows, bottom to top: "loop" (the loop under the
        cursor), "seams" (every edge the pass makes a seam), "errors" (fallback wall seams), "edge" (the edge under
        the cursor)."""
        result = getattr(self, "_result", None)
        hover = getattr(self, "_hover", None)
        loop, edge = [], []
        if result is not None and hover is not None:
            cache = result.objects.get(hover[0].name)
            if cache is not None:
                loop = cache.segments(hover[1].edges())
                edge = cache.segments([hover[3]]) if len(hover) > 3 else []
        return {"loop": loop, "seams": result.seam_lines if result is not None else [],
                "errors": result.error_lines if result is not None else [], "edge": edge}

    def _header(self):
        kinds = (getattr(self, "_result", None) or _Result()).kinds
        return f"{kinds.get('WALL', 0)} wall(s), {kinds.get('RING', 0)} ring(s), {kinds.get('DISK', 0)} disk(s)"

    def _build_overlays(self, region):
        self._hud = HUDOverlay("uv_pipe")
        self._hud.title = "UV Pipe"
        self._hud.bind_region(region)
        degrees = "{:.0f}°"

        def offset_matters():
            return self.offset_axis != "NONE" and not (self.mode == "FIT" and self.pack)

        # compact: the wheel combinations are in the help overlay, rows that do not apply are hidden
        rows = [
            HUDParam("Mode (Q)", lambda: MODE_NAMES[self.mode], "enum"),
            HUDParam("Fit to Active (D)", lambda: FIT_NAMES[self.active_fit], "enum",
                     visible_getter=lambda: self.mode == "ACTIVE"),
            HUDParam("Orientation (W)", lambda: ORIENTATION_NAMES[self.orientation], "enum"),
            HUDParam("Layout (E)", lambda: LAYOUT_NAMES[self.layout], "enum"),
            HUDParam("Loop (LMB)", lambda: self._loop_text(getattr(self, "_hover", None)), "str"),
            HUDParam("Edge (C)", self._edge_text, "str"),
            HUDParam("Seam Side (T)", lambda: SEAM_SIDE_NAMES[self.seam_side], "enum"),
            HUDParam("Loop Source (G)", lambda: SOURCE_NAMES[self.loop_source], "enum",
                     visible_getter=self._has_uv_source),
            HUDParam("Loop Angle", lambda: math.degrees(self.loop_angle), "float", fmt=degrees),
            HUDParam("Sharp Angle", lambda: math.degrees(self.sharp_angle), "float", fmt=degrees),
            HUDParam("Hard Edge Angle", lambda: math.degrees(self.hard_angle), "float", fmt=degrees),
            HUDParam("Split at Bends (A)", lambda: self.split_at_bends, "bool"),
            HUDParam("Bend Angle", lambda: math.degrees(self.bend_angle), "float", fmt=degrees,
                     visible_getter=lambda: self.split_at_bends),
            HUDParam("Split at Seams (S)", lambda: self.split_at_seams, "bool"),
            HUDParam("Mark Seams (X)", lambda: self.mark_seams, "bool"),
            HUDParam("Pack (P)", lambda: self.pack, "bool", visible_getter=lambda: self.mode == "FIT"),
            HUDParam("Random Offset (Z)", lambda: OFFSET_NAMES[self.offset_axis], "enum",
                     visible_getter=lambda: not (self.mode == "FIT" and self.pack)),
            HUDParam("Offset Limit", lambda: self.offset_limit, "float", fmt="{:.2f}", visible_getter=offset_matters),
            HUDParam("Offset Seed (R)", lambda: self.offset_seed, "int", visible_getter=offset_matters),
            HUDParam("Merge Doubles (F)", lambda: self.merge_doubles, "bool"),
        ]
        for row in rows:
            self._hud.add_param(row)

        def item(label, key):
            return HUDItem(label, key, ItemState.ON, default_state=ItemState.OFF, always_show=True)

        self._help = HelpOverlay("uv_pipe")
        self._help.add_section(HUDSection("UV Pipe", [
            item("Mark / unmark the loop under the cursor", "LMB"),
            item("Mark / unmark the edge under the cursor", "C"),
            item("Unmark the whole loop under the cursor", "Alt + C"),
            item("Step the wall seam under the cursor", "Alt + Wheel"),
            item("Loop angle", "Ctrl + Wheel"),
            item("Sharp angle", "Shift + Wheel / Ctrl + Shift + Wheel"),
            item("Bend angle", "Shift + Alt + Wheel / Ctrl + Shift + Alt + Wheel"),
            item("Hard edge angle", "Ctrl + Alt + Wheel"),
            item("Seam side", "T / Shift + T"),
            item("Loop source", "G"),
            item("Split at bends", "A"),
            item("Split at seams", "S"),
            item("Random offset", "Z"),
            item("New offset seed", "R"),
            item("Merge doubles", "F"),
            item("Pack", "P"),
            item("Mode", "Q"),
            item("Fit to active", "D"),
            item("Orientation", "W"),
            item("Layout", "E"),
            item("Mark seams", "X"),
            item("Finish", "Enter / Space"),
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
            self.report({"WARNING"}, "UV Pipe: mesh data became invalid — cancelled")
            return {"CANCELLED"}
        except Exception:
            self._finish(context)
            raise

    def _wheel(self, context, event):
        """The answer to a wheel event: Ctrl the loop angle, Alt steps the wall seam under the cursor, Ctrl + Alt
        the hard edge angle, Shift the sharp angle and Shift + Alt the bend angle (with Split at Bends), both 1
        degree instead of 5 with Ctrl. A plain wheel, and any other combination, goes on to the viewport."""
        sign = 1 if event.type == "WHEELUPMOUSE" else -1
        step = ANGLE_STEP * sign
        if event.alt and event.ctrl and not event.shift:
            self.hard_angle = min(max(self.hard_angle + step, ANGLE_MIN), math.pi)
            self._relayout(context)
            self._update_hover(context, event)
            return {"RUNNING_MODAL"}
        if event.alt and not event.shift:
            target = self._part_under_cursor(context, event)
            if target is None or not self._cycle_seam(context, target[0], target[1], sign):
                return {"PASS_THROUGH"}
            self._update_hover(context, event)
            return {"RUNNING_MODAL"}
        if event.shift:
            if event.alt and not self.split_at_bends:
                return {"PASS_THROUGH"}
            name = "bend_angle" if event.alt else "sharp_angle"
            if event.ctrl:
                step = ANGLE_FINE_STEP * sign
        elif event.ctrl:
            name = "loop_angle"
        else:
            return {"PASS_THROUGH"}
        setattr(self, name, min(max(getattr(self, name) + step, ANGLE_MIN), math.pi))
        self._relayout(context)
        self._update_hover(context, event)
        return {"RUNNING_MODAL"}

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

        if event.type in WHEEL:
            return self._wheel(context, event)
        if event.type == "MOUSEMOVE":
            self._update_hover(context, event)
            return {"RUNNING_MODAL"}
        if event.type in NAVIGATION or event.type in MODIFIER_KEYS or event.type.startswith("NDOF"):
            return {"PASS_THROUGH"}     # the viewport keeps its navigation, modifier combinations included
        if event.value != "PRESS":
            return {"RUNNING_MODAL"}

        toggles = {"LEFTMOUSE": self._toggle_loop, "C": self._toggle_edge}
        if event.type == "C" and event.alt and not (event.ctrl or event.shift):
            toggles["C"] = self._unmark
        elif event.type == "C" and (event.ctrl or event.shift or event.alt):
            return {"RUNNING_MODAL"}
        if event.type in toggles:
            self._update_hover(context, event)
            if toggles[event.type](context):
                self._update_hover(context, event)      # the HUD and the highlight follow at once
            return {"RUNNING_MODAL"}
        if event.type in {"RET", "NUMPAD_ENTER", "SPACE"}:
            result = self._result
            if self.merge_doubles and result.doubles:
                # restore the snapshot first (by index, before the topology changes), then merge and lay out
                self._restore_snapshot(update=False)
                result = self._lay_out(context, merge=True)
                for me, *_rest in self._snapshot:
                    bmesh.update_edit_mesh(me)
            self._finish(context)
            return self._report_result(result)
        if event.type in {"RIGHTMOUSE", "ESC"}:
            for name, value in self._cancel.items():
                setattr(self, name, value)
            self._restore_snapshot()
            self._finish(context)
            return {"CANCELLED"}
        relayout = True
        if event.type == "Q":
            self.mode = MODE_CYCLE[(MODE_CYCLE.index(self.mode) + 1) % len(MODE_CYCLE)]
        elif event.type == "W":
            self.orientation = "VERTICAL" if self.orientation == "HORIZONTAL" else "HORIZONTAL"
        elif event.type == "E":
            self.layout = LAYOUT_CYCLE[(LAYOUT_CYCLE.index(self.layout) + 1) % len(LAYOUT_CYCLE)]
        elif event.type == "G":
            if not self._has_uv_source():
                return {"RUNNING_MODAL"}        # no UV layout to measure in: Geometry stays
            self.loop_source = "UV" if self.loop_source == "GEOMETRY" else "GEOMETRY"
        elif event.type == "A":
            self.split_at_bends = not self.split_at_bends
        elif event.type == "S":
            self.split_at_seams = not self.split_at_seams
        elif event.type == "D":
            self.active_fit = FIT_CYCLE[(FIT_CYCLE.index(self.active_fit) + 1) % len(FIT_CYCLE)]
        elif event.type == "Z":
            self.offset_axis = OFFSET_CYCLE[(OFFSET_CYCLE.index(self.offset_axis) + 1) % len(OFFSET_CYCLE)]
        elif event.type == "T":
            step = -1 if event.shift else 1
            self.seam_side = SEAM_SIDE_CYCLE[(SEAM_SIDE_CYCLE.index(self.seam_side) + step) % len(SEAM_SIDE_CYCLE)]
            self._drop_wall_picks()
        elif event.type == "X":
            self.mark_seams = not self.mark_seams
        elif event.type == "P":
            self.pack = not self.pack
        elif event.type == "R":
            self.offset_seed += 1
        elif event.type == "F":           # applied on finish: only the HUD changes now
            self.merge_doubles = not self.merge_doubles
            relayout = False
        elif event.type in PASS_KEYS:
            return {"PASS_THROUGH"}
        else:
            return {"RUNNING_MODAL"}
        if relayout:
            self._relayout(context)
            self._update_hover(context, event)
        return {"RUNNING_MODAL"}

    def _add_handlers(self, context):
        """The two draw handlers: the lines in the scene (POST_VIEW, tested against its depth) and the HUD and
        help on top (POST_PIXEL); both tracked for the purge on reload."""
        self._handle_view = safe_handler_add(
            bpy.types.SpaceView3D, self._draw_view_callback, (context,), "WINDOW", "POST_VIEW")
        _ACTIVE_HANDLES.add(self._handle_view)
        self._handle = safe_handler_add(
            bpy.types.SpaceView3D, self._draw_callback, (context,), "WINDOW", "POST_PIXEL", tick=True)
        _ACTIVE_HANDLES.add(self._handle)

    def _remove_handlers(self):
        for name in ("_handle_view", "_handle"):
            h = getattr(self, name, None)
            if h is None:
                continue
            _ACTIVE_HANDLES.discard(h)
            try:
                safe_handler_remove(h, bpy.types.SpaceView3D, "WINDOW")
            except (ValueError, RuntimeError):
                pass
            setattr(self, name, None)

    def _finish(self, context):
        self._remove_handlers()
        try:
            context.workspace.status_text_set(None)
        except AttributeError:
            pass
        if getattr(context, "area", None):
            context.area.tag_redraw()
        # Finished operator instances stay alive in the redo stack: drop every mesh reference.
        self._snapshot = []
        self._result = None
        self._hud = None
        self._help = None
        self._hover = None
        self._pick_cache = {}

    def _status_text(self):
        result = getattr(self, "_result", None)
        count = f"{self._summary(result)} | " if result is not None else ""
        return (
            f"UV Pipe: {count}"
            "[LMB] mark / unmark the loop | [C] mark / unmark the edge | [Alt+C] unmark the loop | "
            "[Alt+Wheel] step the wall seam | "
            f"seam side = {SEAM_SIDE_NAMES[self.seam_side].lower()} (T) | "
            f"loop angle = {math.degrees(self.loop_angle):.0f}° (Ctrl+Wheel) | "
            f"sharp angle = {math.degrees(self.sharp_angle):.0f}° (Shift+Wheel) | "
            f"layout = {LAYOUT_NAMES[self.layout].lower()} (E) | "
            f"mode = {MODE_NAMES[self.mode].lower()} (Q) | "
            f"pack = {'on' if self.pack else 'off'} (P) | "
            "[Enter/Space] finish | [Esc/RMB] cancel"
        )

    def _draw_view_callback(self, context):
        """POST_VIEW: the world-space lines, dimmed where geometry hides them (``draw.edges_world``)."""
        try:
            points = self._preview_points()
            # bottom to top: the loop under the cursor, every seam (so a marked loop stays yellow), fallback wall
            # seams, the edge under the cursor
            for name, role, width in (("loop", Role.ACTIVE_LINE, "preview"), ("seams", Role.PREVIEW_LINE, "preview"),
                                      ("errors", Role.ERROR_LINE, "preview"), ("edge", Role.LOCKED_LINE, "closest")):
                if points[name]:
                    draw.edges_world(points[name], role=role, width=width, context=context)
        except Exception:   # a draw handler must never raise: it would repeat every frame
            pass

    def _draw_callback(self, context):
        """POST_PIXEL: the HUD and the help."""
        if context.region_data is None:
            return
        hud = getattr(self, "_hud", None)
        helpo = getattr(self, "_help", None)
        last_event = getattr(self, "_last_event", None)
        if helpo is not None:
            helpo.draw(context, last_event)
        if hud is not None:
            hud.set_header(self._header())
            hud.draw(context, last_event)
