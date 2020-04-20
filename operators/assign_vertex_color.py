import bpy

class IOPS_OT_VertexColorAssign(bpy.types.Operator):
    """Assign Vertex color in editr mode to selected vertecies"""
    bl_idname = "iops.assign_vertex_color"
    bl_label = "Assign Vertex color in editr mode to selected vertecies"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):        
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
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
        return {'FINISHED'}


