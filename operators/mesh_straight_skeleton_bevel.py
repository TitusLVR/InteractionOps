import bpy
import bmesh
import math
from mathutils import Vector
from bpy.props import FloatProperty, IntProperty

EPSILON = 1e-6


# ---------------------------------------------------------------------------
# Straight-skeleton utilities
# ---------------------------------------------------------------------------

def cross2d(a, b):
    return a[0] * b[1] - a[1] * b[0]


def intersect_lines_2d(p1, d1, p2, d2):
    denom = cross2d(d1, d2)
    if abs(denom) < EPSILON:
        return None
    dp = (p2[0] - p1[0], p2[1] - p1[1])
    t = cross2d(dp, d2) / denom
    return (p1[0] + t * d1[0], p1[1] + t * d1[1])


def signed_area_2d(verts):
    n = len(verts)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += verts[i][0] * verts[j][1]
        area -= verts[j][0] * verts[i][1]
    return area / 2.0


class FaceCoords:
    """Local 2D coordinate system on a face plane (always CCW)."""

    def __init__(self, face):
        self.normal = face.normal.copy()
        if self.normal.length < EPSILON:
            self.normal = Vector((0, 0, 1))
        else:
            self.normal.normalize()
        self.origin = face.calc_center_median()
        loops = list(face.loops)
        ev = loops[1].vert.co - loops[0].vert.co
        self.u = (ev - ev.project(self.normal)).normalized()
        self.v = self.normal.cross(self.u).normalized()
        test = [self.to2d(l.vert.co) for l in loops]
        if signed_area_2d(test) < 0:
            self.v = -self.v

    def to2d(self, p):
        d = p - self.origin
        return (d.dot(self.u), d.dot(self.v))

    def to3d(self, p):
        return self.origin + p[0] * self.u + p[1] * self.v


def weighted_skeleton_offset(verts_2d, weights, offset):
    """Weighted straight-skeleton offset for a 2D CCW polygon.

    Edges with weight=1 advance inward by *offset*; weight=0 stay fixed.
    Detects edge-collapse and split events and resolves them by clamping.
    """
    n = len(verts_2d)
    if n < 3:
        return list(verts_2d)

    dirs = []
    norms = []
    for i in range(n):
        j = (i + 1) % n
        dx = verts_2d[j][0] - verts_2d[i][0]
        dy = verts_2d[j][1] - verts_2d[i][1]
        ln = math.sqrt(dx * dx + dy * dy)
        if ln > EPSILON:
            dirs.append((dx / ln, dy / ln))
            norms.append((-dy / ln, dx / ln))
        else:
            dirs.append((1.0, 0.0))
            norms.append((0.0, 1.0))

    result = []
    for i in range(n):
        pi = (i - 1) % n
        wp, wc = weights[pi], weights[i]
        if wp == 0 and wc == 0:
            result.append(verts_2d[i])
            continue
        p_prev = (
            verts_2d[pi][0] + wp * offset * norms[pi][0],
            verts_2d[pi][1] + wp * offset * norms[pi][1],
        )
        p_curr = (
            verts_2d[i][0] + wc * offset * norms[i][0],
            verts_2d[i][1] + wc * offset * norms[i][1],
        )
        pt = intersect_lines_2d(p_prev, dirs[pi], p_curr, dirs[i])
        if pt is not None:
            result.append(pt)
        else:
            s = max(wp + wc, 1.0)
            nx = (wp * norms[pi][0] + wc * norms[i][0]) / s
            ny = (wp * norms[pi][1] + wc * norms[i][1]) / s
            result.append(
                (verts_2d[i][0] + offset * nx, verts_2d[i][1] + offset * ny)
            )

    # Edge-collapse resolution
    for _it in range(20):
        changed = False
        for i in range(n):
            j = (i + 1) % n
            if result[i] == verts_2d[i] and result[j] == verts_2d[j]:
                continue
            ox = verts_2d[j][0] - verts_2d[i][0]
            oy = verts_2d[j][1] - verts_2d[i][1]
            rx = result[j][0] - result[i][0]
            ry = result[j][1] - result[i][1]
            if ox * rx + oy * ry < -EPSILON:
                vel_i = (
                    result[i][0] - verts_2d[i][0],
                    result[i][1] - verts_2d[i][1],
                )
                vel_j = (
                    result[j][0] - verts_2d[j][0],
                    result[j][1] - verts_2d[j][1],
                )
                dv = (vel_j[0] - vel_i[0], vel_j[1] - vel_i[1])
                denom_t = dv[0] * ox + dv[1] * oy
                t = (
                    max(0.0, min(1.0, -(ox * ox + oy * oy) / denom_t))
                    if abs(denom_t) > EPSILON
                    else 0.5
                )
                cx = (
                    verts_2d[i][0]
                    + t * vel_i[0]
                    + verts_2d[j][0]
                    + t * vel_j[0]
                ) / 2
                cy = (
                    verts_2d[i][1]
                    + t * vel_i[1]
                    + verts_2d[j][1]
                    + t * vel_j[1]
                ) / 2
                result[i] = (cx, cy)
                result[j] = (cx, cy)
                changed = True
        if not changed:
            break

    # Split-event resolution
    for _it in range(10):
        changed = False
        for i in range(n):
            j = (i + 1) % n
            for k in range(n):
                l_idx = (k + 1) % n
                if k == i or k == j or l_idx == i or l_idx == j:
                    continue
                if k == (i - 1) % n or l_idx == (i - 1) % n:
                    continue
                p1, p2, p3, p4 = result[i], result[j], result[k], result[l_idx]
                d1 = (p2[0] - p1[0], p2[1] - p1[1])
                d2 = (p4[0] - p3[0], p4[1] - p3[1])
                denom = cross2d(d1, d2)
                if abs(denom) < EPSILON:
                    continue
                dp = (p3[0] - p1[0], p3[1] - p1[1])
                tv = cross2d(dp, d2) / denom
                sv = cross2d(dp, d1) / denom
                m = 0.01
                if m < tv < 1 - m and m < sv < 1 - m:
                    ix = p1[0] + tv * d1[0]
                    iy = p1[1] + tv * d1[1]
                    if result[j] != verts_2d[j]:
                        result[j] = (ix, iy)
                        changed = True
                    if result[k] != verts_2d[k]:
                        result[k] = (ix, iy)
                        changed = True
        if not changed:
            break

    return result


# ---------------------------------------------------------------------------
# Operator
# ---------------------------------------------------------------------------


class IOPS_OT_StraightSkeletonBevel(bpy.types.Operator):
    """Bevel selected edges using the Straight Skeleton algorithm.
Handles overlapping geometry by merging edges at collision points"""

    bl_idname = "iops.straight_skeleton_bevel"
    bl_label = "Straight Skeleton Bevel"
    bl_description = (
        "Bevel selected edges with collision-aware straight skeleton offset. "
        "Overlapping bevel edges merge cleanly instead of creating broken geometry"
    )
    bl_options = {"REGISTER", "UNDO"}

    offset: FloatProperty(
        name="Offset",
        description="Bevel offset distance",
        default=0.05,
        min=0.0001,
        soft_max=10.0,
        step=1,
        precision=4,
        subtype="DISTANCE",
    )

    segments: IntProperty(
        name="Segments",
        description="Profile resolution (1 = flat chamfer, 2+ for arc)",
        default=4,
        min=1,
        max=32,
    )

    profile: FloatProperty(
        name="Profile",
        description="0 = flat chamfer, 0.5 = circular arc, 1.0 = convex",
        default=0.5,
        min=0.0,
        max=1.0,
        step=10,
        precision=2,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and obj.mode == "EDIT"

    def execute(self, context):
        obj = context.active_object
        bm = bmesh.from_edit_mesh(obj.data)
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        bm.verts.ensure_lookup_table()

        sel_edges = [e for e in bm.edges if e.select and len(e.link_faces) >= 1]
        if not sel_edges:
            self.report({"WARNING"}, "No edges selected")
            return {"CANCELLED"}

        sel_set = {e.index for e in sel_edges}

        affected_faces = set()
        for e in sel_edges:
            for f in e.link_faces:
                affected_faces.add(f)
        affected_face_idx = {f.index for f in affected_faces}

        # ---- Phase 1: pre-compute straight-skeleton positions ----
        skeleton_pos = {}  # (orig_vert_idx, face_idx) -> Vector
        for face in affected_faces:
            cs = FaceCoords(face)
            loops = list(face.loops)
            v2d = [cs.to2d(l.vert.co) for l in loops]
            wts = [1.0 if l.edge.index in sel_set else 0.0 for l in loops]
            off2d = weighted_skeleton_offset(v2d, wts, self.offset)
            for i, loop in enumerate(loops):
                pos = cs.to3d(off2d[i])
                if (pos - loop.vert.co).length > EPSILON:
                    skeleton_pos[(loop.vert.index, face.index)] = pos

        # ---- Phase 2: bmesh.ops.bevel for correct topology ----
        result = bmesh.ops.bevel(
            bm,
            geom=sel_edges,
            offset=self.offset,
            offset_type="OFFSET",
            segments=self.segments,
            profile=self.profile,
            affect="EDGES",
            clamp_overlap=False,
        )

        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        # ---- Phase 3: adjust boundary vertices with skeleton positions ----
        bevel_face_idx = set()
        for f in result.get("faces", []):
            if f.is_valid:
                bevel_face_idx.add(f.index)

        for nv in result.get("verts", []):
            if not nv.is_valid:
                continue

            # Only adjust vertices that sit on the inner (shrunk) face boundary,
            # not the intermediate arc vertices that live purely on bevel faces.
            on_inner = any(
                f.index not in bevel_face_idx for f in nv.link_faces if f.is_valid
            )
            if not on_inner:
                continue

            inner_faces = {
                f.index
                for f in nv.link_faces
                if f.is_valid and f.index in affected_face_idx
            }
            if not inner_faces:
                continue

            best_dist = float("inf")
            best_pos = None
            for (vi, fi), pos in skeleton_pos.items():
                if fi not in inner_faces:
                    continue
                d = (nv.co - pos).length
                if d < best_dist:
                    best_dist = d
                    best_pos = pos

            if best_pos is not None and best_dist < self.offset * 3:
                nv.co = best_pos

        # ---- cleanup ----
        bm.normal_update()
        bmesh.update_edit_mesh(obj.data)

        self.report({"INFO"}, "Straight Skeleton Bevel applied")
        return {"FINISHED"}
