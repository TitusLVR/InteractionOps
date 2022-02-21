import bpy

class IOPS_OT_VertexColorAssign(bpy.types.Operator):
    """Assign Vertex color in editr mode to selected vertecies"""
    bl_idname = "iops.assign_vertex_color"
    bl_label = "Assign Vertex color in editr mode to selected vertecies"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):        
        return context.object.type == 'MESH'

    def execute(self, context):
        if context.object.type == "MESH":
            if context.mode == 'OBJECT':
                me = context.object.data
                if me.vertex_colors[:] == []:
                    me.vertex_colors.new()
                vcol_data = me.vertex_colors.active.data
                if vcol_data:
                    for p in me.polygons:
                        color = context.tool_settings.image_paint.brush.color                                
                        for loop_index in p.loop_indices:
                            vcol_data[loop_index].color = (color[0],color[1],color[2], 1.0)                
                    me.update()        
            
            if context.mode == 'EDIT_MESH':
                tool_mesh = bpy.context.scene.tool_settings.mesh_select_mode
                vertex = tool_mesh[0]
                face = tool_mesh[2]
                bpy.context.tool_settings.vertex_paint.brush.color = context.tool_settings.image_paint.brush.color
                bpy.ops.object.mode_set(mode = 'VERTEX_PAINT')
                if vertex:            
                    bpy.context.object.data.use_paint_mask_vertex = True
                    bpy.ops.paint.vertex_color_set()
                    bpy.ops.object.mode_set(mode = 'EDIT')
                if face:
                    bpy.context.object.data.use_paint_mask = True
                    bpy.ops.paint.vertex_color_set()
                    bpy.ops.object.mode_set(mode = 'EDIT')
        else:
            self.report({'WARNING'}, "Not a MESH")
        return {'FINISHED'}
        


