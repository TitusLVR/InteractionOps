"""UV Pipe: unwrap tubes as a straight wall, straight cap rings and cap disks.

The faces are split into parts by ``utils/uv_pipe_core.analyse``: ring seams where
the tube ends or breaks (closed loops sharper than Sharp Angle), cap rings peeled off
flat caps, the disk left in a cap's middle, walls between, and free parts that are
none of these. Each wall gets one lengthwise seam. ``uv_pipe_bridge`` lays every part
out (a wall inside a straight rectangle, a ring as a straight strip, a disk at real
size, a free part by Blender's unwrap), places them with one texel density per
object, packs them into 0-1 and marks the seams.

Scope: the selected faces; with no face selected, every visible face of the meshes
in Edit Mode. The loops the user committed in the interactive mode are kept in
``picks`` for redo.
"""

import json
import math
from dataclasses import dataclass, field

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty

from ..utils import uv_pipe_core, uv_stripe_select_core
from . import uv_pipe_bridge, uv_stripe_bridge
from .mesh_uv_stripe import _world_context

PICK_KINDS = ("added", "removed", "picked")


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
    # per object name: the analysis, the layouts and the world matrix of the last pass (the modal's preview)
    analyses: dict = field(default_factory=dict)


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
            uv = uv_pipe_bridge.single_uvs(bm, faces=scoped) if self.loop_source == "UV" else None
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
            result.analyses[obj.name] = (analysis, layouts, matrix.copy())
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
