import math
import bpy
import bmesh
from mathutils.bvhtree import BVHTree
from bpy.props import BoolProperty, FloatProperty


class IOPS_OT_Mesh_QuickSnap(bpy.types.Operator):
    """Quick Snap point to point"""

    bl_idname = "iops.mesh_quick_snap"
    bl_label = "IOPS Quick Snap"
    bl_options = {"REGISTER", "UNDO"}

    quick_snap_surface: BoolProperty(
        name="Surface snap", description="ON/Off", default=False
    )
    quick_snap_self: BoolProperty(
        name="Snap to self",
        description="Also snap selected verts to non-selected geometry of the active object",
        default=False,
    )
    quick_snap_normal_check: BoolProperty(
        name="Face normal check",
        description="Reject snap targets whose face normal points away from the vertex",
        default=False,
    )
    quick_snap_normal_angle: FloatProperty(
        name="Max angle",
        description="Maximum angle between face normal and vector from hit to vertex (degrees)",
        default=90.0,
        min=0.0,
        max=180.0,
    )
    # @classmethod
    # def poll(cls, context):
    #     return (and context.area.type == "VIEW_3D")

    def _build_edit_data(self, edit_objects):
        """For each edit-mode object: live bmesh, selected coords, and a BVH
        of geometry excluding selected verts (used as snap target when another
        edit object snaps onto this one, or for self-snap)."""
        edit_data = {}
        for eo in edit_objects:
            ebm = bmesh.from_edit_mesh(eo.data)
            ebm.verts.ensure_lookup_table()
            sel_co = {v.index: v.co.copy() for v in ebm.verts if v.select}

            cbm = ebm.copy()
            cbm.verts.ensure_lookup_table()
            drop = [v for v in cbm.verts if v.select]
            if drop:
                bmesh.ops.delete(cbm, geom=drop, context="VERTS")
            cbm.verts.ensure_lookup_table()
            cbm.faces.ensure_lookup_table()
            if len(cbm.faces) > 0:
                bvh = BVHTree.FromBMesh(cbm)
                face_verts = [[v.co.copy() for v in f.verts] for f in cbm.faces]
            else:
                bvh = None
                face_verts = None
            cbm.free()

            edit_data[eo] = {
                "ebm": ebm,
                "sel_co": sel_co,
                "bvh": bvh,
                "face_verts": face_verts,
            }
        return edit_data

    def _find_target(self, vert_co, ob, edit_data):
        """Return (hit, loc, norm, face_index, face_verts_co) for snap query."""
        ob_mw_i = ob.matrix_world.inverted()
        local_pos = ob_mw_i @ vert_co
        if ob in edit_data:
            bvh = edit_data[ob]["bvh"]
            if bvh is None:
                return False, None, None, None, None
            loc, norm, face_index, _ = bvh.find_nearest(local_pos)
            if loc is None:
                return False, None, None, None, None
            return True, loc, norm, face_index, edit_data[ob]["face_verts"][face_index]
        hit, loc, norm, face_index = ob.closest_point_on_mesh(local_pos)
        return hit, loc, norm, face_index, None

    def execute(self, context):
        if context.mode != "EDIT_MESH":
            self.report({"WARNING"}, "ENTER TO MESH EDIT MODE!!!")
            return {"FINISHED"}

        scene = context.scene
        edit_objects = [o for o in context.objects_in_mode if o.type == "MESH"]
        edit_data = self._build_edit_data(edit_objects)

        external_objects = [
            o
            for o in scene.objects
            if o.type == "MESH"
            and o not in edit_objects
            and o.data.polygons[:] != []
            and o.visible_get()
            and o.modifiers[:] == []
        ]

        for eo in edit_objects:
            d = edit_data[eo]
            if not d["sel_co"]:
                continue

            # Snap targets: all external meshes + other edit objects.
            # Same-object only included when self-snap is on.
            target_objects = list(external_objects)
            for other in edit_objects:
                if other is eo:
                    if self.quick_snap_self and edit_data[other]["bvh"] is not None:
                        target_objects.append(other)
                else:
                    target_objects.append(other)

            target_points = []
            eo_mw = eo.matrix_world

            for ob in target_objects:
                for ind, co in d["sel_co"].items():
                    vert_co = eo_mw @ co
                    hit, loc, norm, face_index, face_verts_co = self._find_target(
                        vert_co, ob, edit_data
                    )

                    if hit and self.quick_snap_normal_check:
                        world_norm = (
                            ob.matrix_world.to_3x3() @ norm
                        ).normalized()
                        world_hit = ob.matrix_world @ loc
                        to_vert = vert_co - world_hit
                        if to_vert.length_squared > 0.0:
                            angle = world_norm.angle(to_vert, math.pi)
                            if math.degrees(angle) > self.quick_snap_normal_angle:
                                hit = False

                    if not hit:
                        continue

                    if self.quick_snap_surface:
                        min_co = ob.matrix_world @ loc
                        min_len = (min_co - vert_co).length
                    else:
                        if face_verts_co is not None:
                            iter_co = enumerate(face_verts_co)
                        else:
                            iter_co = (
                                (v, ob.data.vertices[v].co)
                                for v in ob.data.polygons[face_index].vertices
                            )
                        best = None
                        for _key, fco in iter_co:
                            target_co = ob.matrix_world @ fco
                            v_dist = (target_co - vert_co).length
                            if best is None or v_dist < best[1]:
                                best = (target_co, v_dist)
                        if best is None:
                            continue
                        min_co, min_len = best

                    existing = next(
                        (p for p in target_points if p[0] == ind), None
                    )
                    if existing is None:
                        target_points.append([ind, min_co, min_len])
                    elif min_len < existing[2]:
                        existing[1] = min_co
                        existing[2] = min_len

            ebm = d["ebm"]
            ebm.verts.ensure_lookup_table()
            mw_i = eo_mw.inverted()
            for p in target_points:
                ebm.verts[p[0]].co = mw_i @ p[1]
            bmesh.update_edit_mesh(eo.data)

        self.report({"INFO"}, "POINTS ARE SNAPPED!!!")
        return {"FINISHED"}
