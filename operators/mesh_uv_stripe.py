"""UV Stripe: unwrap each selected strip of faces as one straight, even UV rectangle.

Every edge-connected island of selected faces becomes a ``uv_stripe_core.Strip``
(``uv_stripe_select_core.strip_from_faces``), built from world positions so the
object's scale shows in the aspect. The strips are written into the active UV
map with ``uv_stripe_bridge.apply_stripes``; no ``bpy.ops.uv`` call, seams, pins
and selection are left alone.
"""

import bmesh
import bpy
from bpy.props import EnumProperty

from ..utils import uv_stripe_core, uv_stripe_select_core
from . import uv_stripe_bridge

EPS = 1e-6


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


def _strip_for(island, bm_faces, matrix):
    """The validated strip of one island of face ids, laid out in world units; raises ValueError."""
    faces = {fid: tuple(v.index for v in bm_faces[fid].verts) for fid in island}
    verts = {v.index: tuple(matrix @ v.co) for fid in island for v in bm_faces[fid].verts}
    strip = uv_stripe_select_core.strip_from_faces(verts, faces)
    if uv_stripe_core.strip_length(strip) <= EPS:
        raise ValueError("the strip has no length")
    if strip.height <= EPS:
        raise ValueError("the strip has no width")
    uv_stripe_core.stripe_uvs(strip)
    return strip


class IOPS_OT_Mesh_UV_Stripe(bpy.types.Operator):
    """Unwrap each selected strip of faces as one straight, even UV rectangle"""

    bl_idname = "iops.mesh_uv_stripe"
    bl_label = "UV Stripe"
    bl_options = {"REGISTER", "UNDO"}
    is_bindable = True

    mode: EnumProperty(
        name="Mode",
        items=[
            ("FIT", "Fit 0–1", "Stretch the strip across U 0–1, V in proportion"),
            ("IN_PLACE", "In Place", "Keep the old UV location and the neighbours' texel density"),
        ],
        default="FIT",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and obj.mode == "EDIT"

    def execute(self, context):
        done, skipped, first_reason, selected = 0, 0, None, 0
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
            selected += 1
            ids = {fid: tuple(v.index for v in f.verts) for fid, f in picked.items()}
            matrix = obj.matrix_world
            strips, contexts = [], []
            for island in uv_stripe_select_core.face_islands(ids):
                try:
                    strip = _strip_for(island, picked, matrix)
                except ValueError as exc:
                    skipped += 1
                    first_reason = first_reason or str(exc)
                    continue
                island_faces = [picked[fid] for fid in island]
                strips.append(strip)
                contexts.append(_world_context(uv_stripe_bridge.uv_context(bm, island_faces), island_faces, matrix))
            if not strips:
                continue
            uv_stripe_bridge.apply_stripes(bm, strips, picked, self.mode, contexts)
            bmesh.update_edit_mesh(me)
            done += len(strips)

        if not selected:
            self.report({"WARNING"}, "UV Stripe: no faces selected")
            return {"CANCELLED"}
        if not done:
            self.report({"WARNING"}, f"UV Stripe: nothing laid out ({first_reason})")
            return {"CANCELLED"}
        if skipped:
            self.report({"WARNING"}, f"UV Stripe: {done} strip(s), {skipped} skipped ({first_reason})")
        else:
            self.report({"INFO"}, f"UV Stripe: {done} strip(s)")
        return {"FINISHED"}
