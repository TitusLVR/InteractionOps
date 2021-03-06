import bpy
from bpy.types import Menu

class IOPS_MT_Pie_Edit(Menu):
    # bl_idname = "iops.pie_menu"
    bl_label = "IOPS_MT_Pie_Edit"

    @classmethod
    def poll(self, context):
        return (context.area.type in {"VIEW_3D", "IMAGE_EDITOR"} and context.active_object)


    def draw(self, context):
        layout = self.layout
        pie = layout.menu_pie()

        if context.area.type == "VIEW_3D":
            # 4 - LEFT
            pie.operator("iops.f1", text = "Vertex", icon = "VERTEXSEL")        
            # 6 - RIGHT
            pie.operator("iops.f3", text = "Face", icon = "FACESEL") 
            # 2 - BOTTOM
            pie.operator("iops.esc", text = "Esc", icon = "EVENT_ESC")
            # 8 - TOP
            pie.operator("iops.f2", text = "Edge", icon = "EDGESEL")         
            # 7 - TOP - LEFT
            
            # 9 - TOP - RIGHT
            # 1 - BOTTOM - LEFT        
            # 3 - BOTTOM - RIGHT 
        if context.area.type == "IMAGE_EDITOR":
            if context.tool_settings.use_uv_select_sync == True:
                # 4 - LEFT
                pie.operator("iops.f1", text = "Vertex", icon = "VERTEXSEL")        
                # 6 - RIGHT
                pie.operator("iops.f3", text = "Face", icon = "FACESEL") 
                # 2 - BOTTOM
                pie.operator("iops.esc", text = "Esc", icon = "EVENT_ESC")
                # 8 - TOP
                pie.operator("iops.f2", text = "Edge", icon = "EDGESEL")         
                # 7 - TOP - LEFT
            elif context.tool_settings.use_uv_select_sync == False:
                # 4 - LEFT
                pie.operator("iops.f1", text = "Vertex", icon = "VERTEXSEL")        
                # 6 - RIGHT
                pie.operator("iops.f3", text = "Face", icon = "FACESEL") 
                # 2 - BOTTOM
                pie.operator("iops.esc", text = "Esc", icon = "EVENT_ESC")
                # 8 - TOP
                pie.operator("iops.f2", text = "Edge", icon = "EDGESEL")         
                # 7 - TOP - LEFT
                pie.separator()
                # 9 - TOP - RIGHT
                pie.operator("iops.f4", text = "Island", icon = "UV_ISLANDSEL")
            

       

class IOPS_OT_Call_Pie_Edit(bpy.types.Operator):
    """IOPS Pie"""
    bl_idname = "iops.call_pie_edit"
    bl_label = "IOPS Pie Edit"    

    @classmethod
    def poll(self, context):
        return (context.area.type in {"VIEW_3D", "IMAGE_EDITOR"} and context.active_object)


    def execute(self, context):        
        bpy.ops.wm.call_menu_pie(name="IOPS_MT_Pie_Edit")         
        return {'FINISHED'}
