import math
import bpy
import bmesh
from mathutils import Vector
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

    def execute(self, context):
        if context.mode == "EDIT_MESH":
            scene = context.scene

            edit_obj = context.active_object
            me = edit_obj.data
            target_points = []
            # GET INDEXES
            bm = bmesh.from_edit_mesh(me)
            selected_verts_index = []
            for v in bm.verts:
                if v.select:
                    selected_verts_index.append(v.index)
            bpy.ops.object.editmode_toggle()
            bm.free()
            bpy.ops.object.editmode_toggle()

            # GET SCENE OBJECTS
            mesh_objects = [
                o
                for o in scene.objects
                if o.type == "MESH"
                and o.data.polygons[:] != []
                and o.visible_get()
                and o.modifiers[:] == []
            ]
            if self.quick_snap_self and edit_obj not in mesh_objects:
                mesh_objects.append(edit_obj)

            # Build a BVH of edit_obj geometry excluding selected verts/faces,
            # so self-snap (both surface and vertex modes) ignores the moving
            # selection itself.
            self_bvh = None
            self_face_verts = None
            if self.quick_snap_self:
                self_bm = bmesh.new()
                self_bm.from_mesh(me)
                self_bm.verts.ensure_lookup_table()
                drop = [self_bm.verts[i] for i in selected_verts_index]
                bmesh.ops.delete(self_bm, geom=drop, context="VERTS")
                self_bm.verts.ensure_lookup_table()
                self_bm.faces.ensure_lookup_table()
                if len(self_bm.faces) > 0:
                    self_bvh = BVHTree.FromBMesh(self_bm)
                    self_face_verts = [
                        [v.co.copy() for v in f.verts] for f in self_bm.faces
                    ]
                self_bm.free()

            bm = bmesh.new()
            for ob in mesh_objects:
                is_self = ob == edit_obj
                if is_self and not self.quick_snap_self:
                    continue
                if is_self and self_bvh is None:
                    continue
                ob_mw_i = ob.matrix_world.inverted()

                bm.from_mesh(me)
                bm.verts.ensure_lookup_table()
                for ind in selected_verts_index:
                    vert = bm.verts[ind]
                    vert_co = edit_obj.matrix_world @ vert.co
                    local_pos = ob_mw_i @ vert_co

                    if is_self:
                        loc, norm, face_index, _ = self_bvh.find_nearest(local_pos)
                        hit = loc is not None
                        face_verts_co = (
                            self_face_verts[face_index] if hit else None
                        )
                    else:
                        (hit, loc, norm, face_index) = ob.closest_point_on_mesh(
                            local_pos
                        )
                        face_verts_co = None

                    if hit and self.quick_snap_normal_check:
                        # World-space face normal at hit and vector hit -> vertex.
                        world_norm = (
                            ob.matrix_world.to_3x3() @ norm
                        ).normalized()
                        world_hit = ob.matrix_world @ loc
                        to_vert = vert_co - world_hit
                        if to_vert.length_squared > 0.0:
                            angle = world_norm.angle(to_vert, math.pi)
                            if math.degrees(angle) > self.quick_snap_normal_angle:
                                hit = False

                    if hit:
                        bm.verts.ensure_lookup_table()
                        bm.faces.ensure_lookup_table()
                        v_dists = {}
                        if self.quick_snap_surface:
                            target_co = ob.matrix_world @ loc
                            v_dist = (target_co - vert_co).length
                            min_co = target_co
                            min_len = v_dist
                        else:
                            if is_self:
                                iter_co = enumerate(face_verts_co)
                            else:
                                iter_co = (
                                    (v, ob.data.vertices[v].co)
                                    for v in ob.data.polygons[face_index].vertices
                                )
                            for key, co in iter_co:
                                target_co = ob.matrix_world @ co
                                v_dist = (target_co - vert_co).length
                                v_dists[key] = {}
                                v_dists[key]["co"] = (*target_co,)
                                v_dists[key]["len"] = v_dist

                            if not v_dists:
                                continue
                            lens = [v_dists[idx]["len"] for idx in v_dists]
                            for k in v_dists.values():
                                if k["len"] == min(lens):
                                    min_co = Vector((k["co"]))
                                    min_len = k["len"]

                        if target_points:
                            if len(target_points) != len(selected_verts_index):
                                target_points.append([ind, min_co, min_len])
                            else:
                                for p in target_points:
                                    if p[0] == ind and p[2] >= min_len:
                                        p[1] = min_co
                                        p[2] = min_len
                        else:
                            target_points.append([ind, min_co, min_len])
                bm.clear()

            bm = bmesh.from_edit_mesh(me)
            bm.verts.ensure_lookup_table()
            for p in target_points:
                bm.verts[p[0]].co = edit_obj.matrix_world.inverted() @ p[1]
            bmesh.update_edit_mesh(me)

            self.report({"INFO"}, "POINTS ARE SNAPPED!!!")
        else:
            self.report({"WARNING"}, "ENTER TO MESH EDIT MODE!!!")
        return {"FINISHED"}
