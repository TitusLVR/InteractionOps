import bpy

# VERTEX COLOR 
def color_to_vertices(color):
    new_color = (color[0], color[1], color[2], 1.0)
    mesh = bpy.context.active_object.data
    
    bpy.ops.object.mode_set(mode = 'VERTEX_PAINT')

    selected_verts = []
    for vert in mesh.vertices:
        if vert.select == True:
            selected_verts.append(vert)

    for polygon in mesh.polygons:
        for selected_vert in selected_verts:
            for i, index in enumerate(polygon.vertices):
                if selected_vert.index == index:
                    loop_index = polygon.loop_indices[i]
                    mesh.vertex_colors.active.data[loop_index].color = new_color

    bpy.ops.object.mode_set(mode = 'EDIT')

class IOPS_OT_VerteColorAssign(bpy.types.Operator):
    """Assign Vertex color in editr mode to selected vertecies"""
    bl_idname = "iops.assign_vertex_color"
    bl_label = "Assign Vertex color in editr mode to selected vertecies"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):        
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        # color = context.window_manager.IOPS_AddonProperties.iops_vertex_color 
        color = context.tool_settings.image_paint.brush.color
        color_to_vertices(color)       
        return {'FINISHED'}

class IOPS_OT_VerteColorAssignSplit(bpy.types.Operator):
    """Split and Assign Vertex color in editr mode to selected vertecies"""
    bl_idname = "iops.assign_split_vertex_color"
    bl_label = "Split and assign vertex color in editr mode to selected vertecies"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):        
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        # Check Automerge        
        auto_merge = context.tool_settings.use_mesh_automerge
        if auto_merge:
            context.tool_settings.use_mesh_automerge = False
            
        bpy.ops.mesh.split() 
        color = context.tool_settings.image_paint.brush.color
        color_to_vertices(color)       
        return {'FINISHED'}
