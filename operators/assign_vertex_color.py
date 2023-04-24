import bpy
from bpy.props import (FloatProperty)

class IOPS_OT_VertexColorAssign(bpy.types.Operator):
    """Assign Vertex color in editr mode to selected vertecies"""
    bl_idname = "iops.assign_vertex_color"
    bl_label = "Assign Vertex color in editr mode to selected vertecies"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):        
        return context.object.type == 'MESH'

    def execute(self, context):
        sel = [obj for obj in context.selected_objects]


        if len(sel) == 1 and context.mode == 'EDIT_MESH':
            tool_mesh = context.scene.tool_settings.mesh_select_mode
            vertex = tool_mesh[0]
            face = tool_mesh[2]
            context.tool_settings.vertex_paint.brush.color = context.tool_settings.image_paint.brush.color
            bpy.ops.object.mode_set(mode = 'VERTEX_PAINT')
            if vertex:            
                context.object.data.use_paint_mask_vertex = True
                bpy.ops.paint.vertex_color_set()
                bpy.ops.object.mode_set(mode = 'EDIT')
                return {'FINISHED'}
            if face:
                context.object.data.use_paint_mask = True
                bpy.ops.paint.vertex_color_set()
                bpy.ops.object.mode_set(mode = 'EDIT')
                return {'FINISHED'}
        if context.mode == 'OBJECT':
            bpy.ops.object.select_all(action='DESELECT')
            for obj in sel:
                obj.select_set(True)
                context.view_layer.objects.active = obj
                if obj.type == "MESH":
                    me = obj.data
                    if me.vertex_colors[:] == []:
                        me.vertex_colors.new()
                    vcol_data = me.vertex_colors.active.data
                    if vcol_data:
                        for p in me.polygons:
                            color = context.tool_settings.image_paint.brush.color                                
                            for loop_index in p.loop_indices:
                                vcol_data[loop_index].color = (color[0],color[1],color[2], 1.0)                
                        me.update()        
            else:
                self.report({'WARNING'}, obj.name + " is not a MESH.")
            obj.select_set(False)

        return {'FINISHED'}
    
    def draw(self, context):
        tools = context.tool_settings.image_paint.brush
        layout = self.layout
        col = layout.column(align=True)        
        col.prop(tools, "color")


class IOPS_OT_VertexColorAlphaAssign(bpy.types.Operator):
    """Assign Vertex Color Alpha to selected vertecies"""
    bl_idname = 'iops.assign_vertex_color_alpha'
    bl_label = 'Assign Vertex Color Alpha to selected vertecies'
    bl_options = {'REGISTER', 'UNDO'}

    vertex_color_alpha: FloatProperty(
        name="Alpha",
        description="Alpha channel value. 0 - Transparent, 1 - Solid",
        default=1.0,
        min=0.0,
        max=1.0
    )

    @classmethod
    def poll(cls, context):
        return context.object.type == 'MESH' and context.object.mode == "EDIT"

    def execute(self, context):
        if context.object.mode == "EDIT":
            bpy.ops.object.editmode_toggle()
            
            mesh = bpy.context.active_object.data
            if mesh.vertex_colors[:] == []:
                mesh.vertex_colors.new()
            vertices = mesh.vertices
            vcol = mesh.vertex_colors.active
            
            for loop_index, loop in enumerate(mesh.loops):
                # If vertex selected
                if vertices[loop.vertex_index].select:
                    vertex_color = vcol.data[loop_index].color
                    vertex_color[3] = self.vertex_color_alpha
            mesh.update()
            bpy.ops.object.editmode_toggle()
        return {'FINISHED'}
    
    def draw(self, context):
        layout = self.layout
        row = layout.row()
        row.prop(self, 'vertex_color_alpha', slider=True, text="Alpha value")
        
        
        


