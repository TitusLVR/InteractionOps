import bpy
import bmesh
import json
from mathutils import Vector
from bpy.props import (FloatProperty)

class IOPS_OT_QuickSnap(bpy.types.Operator):
    """ Quick Snap point to point """
    bl_idname = "iops.quick_snap"
    bl_label = "IOPS Quick Snap"
    bl_options = {"REGISTER", "UNDO"}

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

            #GET SCENE OBJECTS
            mesh_objects = [o for o in scene.objects if o.type == 'MESH' and o.data.polygons[:] != [] and o.visible_get()]
            bm = bmesh.new()
            for ob in mesh_objects:
                if ob == edit_obj:
                    continue
                ob_mw_i = ob.matrix_world.inverted()
                
                bm.from_mesh(me)
                bm.verts.ensure_lookup_table()
                for ind in selected_verts_index:                   
                    vert = bm.verts[ind]
                    v1 = edit_obj.matrix_world @ vert.co # global face median  
                            
                    local_pos = ob_mw_i @ v1  # face cent in sphere local space
                    (hit, loc, norm, face_index) = ob.closest_point_on_mesh(local_pos)
                    if hit:
                        bm.verts.ensure_lookup_table()
                        bm.faces.ensure_lookup_table()
                        v_dists = {}
                        for v in ob.data.polygons[face_index].vertices:                                
                            v_co = ob.matrix_world @ ob.data.vertices[v].co                 
                            v_dist = (v_co - v1).length 
                            v_dists[v] = {}
                            v_dists[v]["co"] = (*v_co,)
                            v_dists[v]["len"] = v_dist
                        
                        lens = [v_dists[idx]["len"] for idx in v_dists]
                        for k in v_dists.values():    
                            if k["len"] == min(lens):
                                min_co = k["co"]
                        
                        target_points.append([ind, Vector(min_co)])
                                                   
                bm.clear()

            bm = bmesh.from_edit_mesh(me)
            bm.verts.ensure_lookup_table()
            for p in target_points:
                bm.verts[p[0]].co = edit_obj.matrix_world.inverted() @ p[1]
            bmesh.update_edit_mesh(me)

            self.report({'INFO'}, "POINTS ARE SNAPPED!!!")
        else:
            self.report({'WARNING'}, "ENTER TO MESH EDIT MODE!!!")
        return {'FINISHED'}

        



