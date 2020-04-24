import bpy
from bpy.types import Menu

class IOPS_MT_Pie_Split(Menu):
    # bl_idname = "iops.pie_menu"
    bl_label = "IOPS Split"

    # @classmethod
    # def poll(cls, context):
    #     return context.area.type == "VIEW_3D" 


    def draw(self, context):
        layout = self.layout
        pie = layout.menu_pie()

        # 4 - LEFT
        pie.operator("iops.split_area_outliner", text = "Outliner", icon = "OUTLINER")        
        
        # 6 - RIGHT
        pie.operator("iops.split_area_uv", text = "UV Editor", icon = "UV") 
        
        # 2 - BOTTOM
        # pie.operator("iops.split_area_timeline", text = "Timeline", icon = "TIME")
        pie.separator()
        
        # 8 - TOP
        pie.operator("iops.split_area_console", text = "Console", icon = "CONSOLE")        
        # pie.separator()

        # 7 - TOP - LEFT
        # pie.operator("iops.", text = "", icon = "")
        pie.separator()        
        
        # 9 - TOP - RIGHT
        pie.operator("iops.split_area_text", text = "Text Editor", icon = "TEXT")
        # pie.separator()

        # 1 - BOTTOM - LEFT 
        # pie.operator("iops.", text = "", icon = "")
        pie.separator()                
        
        # 3 - BOTTOM - RIGHT
        pie.operator("iops.split_area_properties", text = "Properties", icon = "PROPERTIES")  
        # pie.separator()
             
       

class IOPS_OT_Call_Pie_Split(bpy.types.Operator):
    """IOPS Pie Split"""
    bl_idname = "iops.call_pie_split"
    bl_label = "IOPS Pie Split"    

    # @classmethod
    # def poll(cls, context):
    #     return context.area.type == "VIEW_3D"

    def execute(self, context):        
        bpy.ops.wm.call_menu_pie(name="IOPS_MT_Pie_Split")         
        return {'FINISHED'}