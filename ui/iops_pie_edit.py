import bpy
from bpy.types import Menu

class IOPS_MT_Pie_Edit(Menu):
    # bl_idname = "iops.pie_menu"
    bl_label = "IOPS_MT_Pie_Edit"

    def draw(self, context):
        layout = self.layout
        pie = layout.menu_pie()

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
             
       

class IOPS_OT_Call_Pie_Edit(bpy.types.Operator):
    """IOPS Pie"""
    bl_idname = "iops.call_pie_edit"
    bl_label = "IOPS Pie Edit"    

    def execute(self, context):        
        bpy.ops.wm.call_menu_pie(name="IOPS_MT_Pie_Edit")         
        return {'FINISHED'}
