import bpy
import bmesh

from bpy.props import (FloatProperty)

class IOPS_OT_QuickSnap(bpy.types.Operator):
    """ Quick Snap point to point """
    bl_idname = "iops.quick_snap"
    bl_label = "IOPS Quick Snap"
    bl_options = {"REGISTER", "UNDO"}

    quick_snap_diff: FloatProperty(
        name="", 
        description="Guess Value", 
        default=0.5, 
        min=0.0001,
        max=1000,
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
            # print("____________________________________________")
            for v in bm.verts:
                if v.select:
                    selected_verts_index.append(v.index)        
                    # print ("VERTS INDEX:", v.index)
            bpy.ops.object.editmode_toggle()
            bm.free()
            bpy.ops.object.editmode_toggle()

            #GET SCENE OBJECTS
            mesh_objects = [o for o in scene.objects if o.type == 'MESH' and o.data.polygons[:] != []]
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
                        v2 = ob.matrix_world @ loc
                        c_dist = (v2 - v1).length
            #            print(ob.name, (v2 - v1).length)
                        # print("Closest dist:",c_dist)
                        bm.verts.ensure_lookup_table()
                        bm.faces.ensure_lookup_table()
                        for v in ob.data.polygons[face_index].vertices:                                
                            v_co = ob.matrix_world @ ob.data.vertices[v].co 
            #                target_points.append(v_co)                          
                            v_dist = (v_co - v1).length - self.quick_snap_diff
                            # print("Vertex dist:",v_dist) 
                            if v_dist <= c_dist:
                                target_points.append([ind,v_co])                           
                bm.clear()
                

            # print (target_points[0][0])

            bm = bmesh.from_edit_mesh(me)
            bm.verts.ensure_lookup_table()
            for p in target_points:
                bm.verts[p[0]].co = edit_obj.matrix_world.inverted() @ p[1]
            bmesh.update_edit_mesh(me)
            #bpy.ops.object.editmode_toggle()
            #for p in target_points: 
            #    print ("------", p)   
            #    bpy.ops.object.empty_add(location=p)

            self.report({'INFO'}, "POINTS ARE SNAPPED!!!")
        else:
            self.report({'WARNING'}, "ENTER TO MESH EDIT MODE!!!")
        return {'FINISHED'}

        



