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
The edge under the cursor shows the seam loop it would make; a first click makes
that loop pending, a second click on it commits it: a lengthwise loop becomes its
wall's seam, a ring loop toggles a ring seam, a cross edge of a ring strip is that
ring's break. Every commit and option change restores the UVs and seams the faces
had and lays them out again; cancel puts them back. The committed loops are kept in
``picks`` for redo.
"""

import json
import math
from dataclasses import dataclass, field

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy_extras import view3d_utils
from mathutils import Vector

from ..ui.draw import Role, draw_scope, safe_handler_add, safe_handler_remove
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
KIND_NAMES = {"RING": "ring seam", "LENGTH": "wall seam", "BREAK": "ring break", "INVALID": "invalid loop"}
PASS_KEYS = {"N", "T"}   # the sidebar and the toolbar still toggle while the modal runs
NAVIGATION = {"MIDDLEMOUSE", "TRACKPADPAN", "TRACKPADZOOM"}
WHEEL = {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}
SETTINGS = ("mode", "active_fit", "orientation", "layout", "loop_source", "loop_angle", "sharp_angle",
            "split_at_bends", "bend_angle", "split_at_seams", "mark_seams", "pack", "offset_axis", "offset_limit",
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
    cut_lines: list = field(default_factory=list)      # world-space segment end points, two per segment
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
        for name in ("orientation", "layout", "loop_source", "loop_angle", "sharp_angle", "split_at_bends"):
            layout.prop(self, name)
        row = layout.row()
        row.enabled = self.split_at_bends
        row.prop(self, "bend_angle")
        for name in ("split_at_seams", "mark_seams"):
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
                picked=[loop for loop in loops["picked"] if loop], uv=uv)
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
            seams = {e for i, loop in analysis.seams.items() if i not in analysis.fallback for e in loop.edges()}
            result.cut_lines += cache.segments(sorted(analysis.cuts | seams))
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
    # Loops: hover, pending, commit, stepping the wall seam
    # ------------------------------------------------------------------

    def _classify(self, obj, key):
        """The loop through edge ``key`` (sorted vertex-index pair) of ``obj`` and its kind, from the last pass.

        "BREAK" when the edge lies between two faces of a ring strip; else the loop traced on all faces in scope
        is "RING" when it closes; else, on an edge inside a wall, the loop traced in that wall up to its
        boundaries is "LENGTH" when it joins two of them, "INVALID" when it stops short; any other edge is
        "INVALID". Returns (loop, kind, part index or None), or None when the edge is not in scope."""
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
            loop = uv_pipe_core.trace_loop(cache.verts, cache.neighbours(part), key, self.loop_angle,
                                           cache.stops(part), cache.uv)
            return loop, uv_pipe_core.loop_kind(loop, cache.analysis.parts[part]), part
        return loop, "INVALID", None

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
        """(object, loop, kind) of the edge under the cursor (the face's edge nearest on screen), or None."""
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
        return None if classified is None else (obj, classified[0], classified[1])

    def _part_under_cursor(self, context, event):
        """(object, part index) of the face under the cursor, or None."""
        found = self._hit(context, event)
        if found is None:
            return None
        obj, face_index = found
        return obj, self._result.objects[obj.name].part_of_face[face_index]

    def _update_hover(self, context, event):
        self._hover = self._hover_loop(context, event)

    def _same(self, a, b):
        return a[0].name == b[0].name and frozenset(a[1].edges()) == frozenset(b[1].edges())

    def _click_loop(self, context, obj, loop, kind):
        """A first click makes ``loop`` pending; a second click on the same loop commits it (``_commit``). An
        INVALID loop is neither. Returns whether it was committed."""
        if kind == "INVALID":
            return False
        pending = getattr(self, "_pending", None)
        if pending is None or not self._same(pending, (obj, loop)):
            self._pending = (obj, loop, kind)
            self._show_status(context)
            return False
        self._pending = None
        self._commit(context, obj, loop, kind)
        return True

    def _commit(self, context, obj, loop, kind):
        """Store ``loop`` in ``picks`` and lay out again.

        RING: a loop the user added is dropped again, a removed one is restored; otherwise a loop whose edges are
        all current cuts is removed, any other added. LENGTH (a wall's seam) and BREAK (a ring's break) replace the
        picks lying inside the same part, then are added to ``picked``."""
        cache = self._result.objects.get(obj.name)
        if cache is None:
            return
        picks = _parse_picks(getattr(self, "picks", ""))
        entry = picks.setdefault(obj.name, {})
        for name in PICK_KINDS:
            entry.setdefault(name, [])
        indices = sorted(cache.edge_index[e] for e in loop.edges() if e in cache.edge_index)
        if not indices:
            return
        if kind == "RING":
            own = set(indices)
            if any(set(lp) == own for lp in entry["added"]):
                entry["added"] = [lp for lp in entry["added"] if set(lp) != own]
            elif any(set(lp) == own for lp in entry["removed"]):
                entry["removed"] = [lp for lp in entry["removed"] if set(lp) != own]
            elif set(loop.edges()) <= cache.analysis.cuts:
                entry["removed"].append(indices)
            else:
                entry["added"].append(indices)
        else:
            parts = {cache.part_of_face[f] for e in loop.edges() for f in cache.edge_faces.get(e, ())}
            inside = set()
            for i in parts:
                inside |= {cache.edge_index[e] for e in uv_pipe_core._inner_edges(cache.analysis.parts[i])
                           if e in cache.edge_index}
            entry["picked"] = [lp for lp in entry["picked"] if not set(lp) <= inside]
            entry["picked"].append(indices if kind == "LENGTH" else indices[:1])
        self.picks = json.dumps(picks, sort_keys=True)
        self._relayout(context)

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
        self._pending = None
        self._commit(context, obj, chosen, "LENGTH")
        return True

    # ------------------------------------------------------------------
    # Modal
    # ------------------------------------------------------------------

    def _start(self, context):
        """Snapshot and the automatic layout; False (reported, restored) when nothing can be laid out."""
        self._take_snapshot(context)
        self._cancel = {name: getattr(self, name) for name in SETTINGS}
        if not self._has_uv_source():
            self.loop_source = "GEOMETRY"
        self._pending = None
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
        self._handle = None
        if not self._start(context):
            return {"CANCELLED"}
        self._build_overlays(context.region)
        self._last_event = capture_event(event, getattr(self, "_last_event", None))
        self._handle = safe_handler_add(
            bpy.types.SpaceView3D, self._draw_callback, (context,), "WINDOW", "POST_PIXEL", tick=True)
        _ACTIVE_HANDLES.add(self._handle)
        self._show_status(context)
        context.window_manager.modal_handler_add(self)
        if context.area:
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def _seam_state(self):
        result = getattr(self, "_result", None)
        if result is not None and result.fallback:
            return "Fallback"
        picked = any(entry.get("picked") for entry in _parse_picks(getattr(self, "picks", "")).values())
        return "Picked" if picked else "Automatic"

    def _notices(self):
        result = getattr(self, "_result", None)
        if result is None:
            return "None"
        notes = list(dict.fromkeys(m.removeprefix("UV Pipe: ") for m in result.infos + result.warnings))
        return "; ".join(notes) if notes else "None"

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

        rows = [
            HUDParam("Mode (Q)", lambda: MODE_NAMES[self.mode], "enum"),
            HUDParam("Orientation (W)", lambda: ORIENTATION_NAMES[self.orientation], "enum"),
            HUDParam("Fit to Active (D)", lambda: FIT_NAMES[self.active_fit], "enum",
                     active_getter=lambda: self.mode == "ACTIVE"),
            HUDParam("Layout (E)", lambda: LAYOUT_NAMES[self.layout], "enum"),
            HUDParam("Loop Source (G)", lambda: SOURCE_NAMES[self.loop_source], "enum",
                     active_getter=self._has_uv_source),
            HUDParam("Loop Angle (Wheel)", lambda: math.degrees(self.loop_angle), "float", fmt=degrees),
            HUDParam("Sharp Angle (Shift + Wheel)", lambda: math.degrees(self.sharp_angle), "float", fmt=degrees),
            HUDParam("Split at Bends (A)", lambda: self.split_at_bends, "bool"),
            HUDParam("Bend Angle (Shift + Alt + Wheel)", lambda: math.degrees(self.bend_angle), "float",
                     fmt=degrees, active_getter=lambda: self.split_at_bends),
            HUDParam("Split at Seams (S)", lambda: self.split_at_seams, "bool"),
            HUDParam("Mark Seams (X)", lambda: self.mark_seams, "bool"),
            HUDParam("Pack (P)", lambda: self.pack, "bool", active_getter=lambda: self.mode == "FIT"),
            HUDParam("Random Offset (Z)", lambda: OFFSET_NAMES[self.offset_axis], "enum",
                     active_getter=lambda: not (self.mode == "FIT" and self.pack)),
            HUDParam("Offset Limit", lambda: self.offset_limit, "float", fmt="{:.2f}", active_getter=offset_matters),
            HUDParam("Offset Seed (R)", lambda: self.offset_seed, "int", active_getter=offset_matters),
            HUDParam("Merge Doubles (F)", lambda: self.merge_doubles, "bool"),
            HUDParam("Seam (Alt + Wheel)", self._seam_state, "str"),
            HUDParam("Notices", self._notices, "str"),
        ]
        for row in rows:
            self._hud.add_param(row)

        def item(label, key):
            return HUDItem(label, key, ItemState.ON, default_state=ItemState.OFF, always_show=True)

        self._help = HelpOverlay("uv_pipe")
        self._help.add_section(HUDSection("UV Pipe", [
            item("Pick a loop; click it again to commit", "LMB"),
            item("Step the wall seam under the cursor", "Alt + Wheel"),
            item("Loop angle", "Wheel / Ctrl + Wheel"),
            item("Sharp angle", "Shift + Wheel / Ctrl + Shift + Wheel"),
            item("Bend angle", "Shift + Alt + Wheel / Ctrl + Shift + Alt + Wheel"),
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
            item("Drop the pending loop, else cancel", "Esc / RMB"),
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
        """The answer to a wheel event: Alt steps the wall seam under the cursor, Shift + Alt the bend angle
        (with Split at Bends), Shift the sharp angle, a plain wheel the loop angle; Ctrl steps 1 degree, not 5."""
        sign = 1 if event.type == "WHEELUPMOUSE" else -1
        step = (ANGLE_FINE_STEP if event.ctrl else ANGLE_STEP) * sign
        if event.alt and not event.shift:
            target = self._part_under_cursor(context, event)
            if target is None or not self._cycle_seam(context, target[0], target[1], sign):
                return {"PASS_THROUGH"}
            return {"RUNNING_MODAL"}
        if event.alt:
            if not self.split_at_bends:
                return {"PASS_THROUGH"}
            name = "bend_angle"
        else:
            name = "sharp_angle" if event.shift else "loop_angle"
        setattr(self, name, min(max(getattr(self, name) + step, ANGLE_MIN), math.pi))
        self._pending = None
        self._relayout(context)
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
        if event.type in NAVIGATION or event.type.startswith("NDOF"):
            return {"PASS_THROUGH"}
        if event.value != "PRESS":
            return {"RUNNING_MODAL"}

        if event.type == "LEFTMOUSE":
            self._update_hover(context, event)
            if self._hover is not None:
                self._click_loop(context, *self._hover)
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
            if getattr(self, "_pending", None) is not None:
                self._pending = None
                self._show_status(context)
                return {"RUNNING_MODAL"}
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
            self._pending = None
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
        self._result = None
        self._hud = None
        self._help = None
        self._pending = None
        self._hover = None
        self._pick_cache = {}

    def _status_text(self):
        result = getattr(self, "_result", None)
        count = f"{self._summary(result)} | " if result is not None else ""
        pending = getattr(self, "_pending", None)
        if pending is not None:
            return (f"UV Pipe: {count}pending {KIND_NAMES[pending[2]]} | [LMB] on it again to commit | "
                    "[Esc/RMB] drop it | [Enter/Space] finish")
        return (
            f"UV Pipe: {count}"
            "[LMB] pick a loop, again to commit | [Alt+Wheel] step the wall seam | "
            f"loop angle = {math.degrees(self.loop_angle):.0f}° (Wheel) | "
            f"sharp angle = {math.degrees(self.sharp_angle):.0f}° (Shift+Wheel) | "
            f"layout = {LAYOUT_NAMES[self.layout].lower()} (E) | "
            f"mode = {MODE_NAMES[self.mode].lower()} (Q) | "
            f"pack = {'on' if self.pack else 'off'} (P) | "
            "[Enter/Space] finish | [Esc/RMB] cancel"
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

        def loop_points(entry):
            if entry is None or result is None:
                return []
            cache = result.objects.get(entry[0].name)
            return [] if cache is None else cache.segments(entry[1].edges())

        hover = getattr(self, "_hover", None)
        pending = getattr(self, "_pending", None)
        try:
            cuts = project(result.cut_lines) if result is not None else []
            errors = project(result.error_lines) if result is not None else []
            hovered = project(loop_points(hover))
            waiting = project(loop_points(pending))
        except Exception:   # a draw handler must never raise: it would repeat every frame
            cuts, errors, hovered, waiting = [], [], [], []
        invalid = hover is not None and hover[2] == "INVALID"
        if cuts or errors or hovered or waiting:
            with draw_scope(blend="ALPHA"):
                if cuts:
                    draw.edges_3d(cuts, role=Role.PREVIEW_LINE, context=context)
                if errors:
                    draw.edges_3d(errors, role=Role.ERROR_LINE, context=context)
                if waiting:
                    draw.edges_3d(waiting, role=Role.ACTIVE_LINE, context=context)
                if hovered:
                    draw.edges_3d(hovered, role=Role.ERROR_LINE if invalid else Role.CLOSEST_LINE, context=context)
        hud = getattr(self, "_hud", None)
        helpo = getattr(self, "_help", None)
        last_event = getattr(self, "_last_event", None)
        if helpo is not None:
            helpo.draw(context, last_event)
        if hud is not None:
            hud.set_header(self._header())
            hud.draw(context, last_event)
