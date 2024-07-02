import bpy
import bmesh
from mathutils import Vector
from bpy.props import BoolProperty


class IOPS_OT_Mesh_QuickSnap(bpy.types.Operator):
    """Quick Snap point to point"""

    bl_idname = "iops.mesh_quick_snap"
    bl_label = "IOPS Quick Snap"
    bl_options = {"REGISTER", "UNDO"}

    quick_snap_surface: BoolProperty(
        name="Surface snap", description="ON/Off", default=False
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
            bm = bmesh.new()
            for ob in mesh_objects:
                if ob == edit_obj:
                    continue
                ob_mw_i = ob.matrix_world.inverted()

                bm.from_mesh(me)
                bm.verts.ensure_lookup_table()
                for ind in selected_verts_index:
                    vert = bm.verts[ind]
                    vert_co = edit_obj.matrix_world @ vert.co
                    local_pos = ob_mw_i @ vert_co
                    (hit, loc, norm, face_index) = ob.closest_point_on_mesh(local_pos)
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
                            for v in ob.data.polygons[face_index].vertices:
                                target_co = ob.matrix_world @ ob.data.vertices[v].co
                                v_dist = (target_co - vert_co).length
                                v_dists[v] = {}
                                v_dists[v]["co"] = (*target_co,)
                                v_dists[v]["len"] = v_dist

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
