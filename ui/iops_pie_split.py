import bpy
from bpy.types import Menu

def get_text_and_icon(ui_type, dict):
    for k,v in dict.items():
        if v["ui"] == ui_type:
            return (k, v["icon"])

class IOPS_MT_Pie_Split(Menu):
    # bl_idname = "iops.pie_menu"
    bl_label = "IOPS Split"

    # @classmethod
    # def poll(cls, context):
    #     return context.area.type == "VIEW_3D" 


    def draw(self, context):
        prefs = context.preferences.addons['InteractionOps'].preferences
        split_areas_dict = prefs.split_areas_dict

        pie_1_text, pie_1_icon = get_text_and_icon(prefs.split_area_pie_1_ui, split_areas_dict)
        pie_2_text, pie_2_icon = get_text_and_icon(prefs.split_area_pie_2_ui, split_areas_dict)
        pie_3_text, pie_3_icon = get_text_and_icon(prefs.split_area_pie_3_ui, split_areas_dict)
        pie_4_text, pie_4_icon = get_text_and_icon(prefs.split_area_pie_4_ui, split_areas_dict)
        pie_6_text, pie_6_icon = get_text_and_icon(prefs.split_area_pie_6_ui, split_areas_dict)
        pie_7_text, pie_7_icon = get_text_and_icon(prefs.split_area_pie_7_ui, split_areas_dict)
        pie_8_text, pie_8_icon = get_text_and_icon(prefs.split_area_pie_8_ui, split_areas_dict)
        pie_9_text, pie_9_icon = get_text_and_icon(prefs.split_area_pie_9_ui, split_areas_dict)

        layout = self.layout
        pie = layout.menu_pie()
        props = context
        # # 4 - LEFT
        # pie.operator("iops.split_area_pie_w", text=pie_4_text, icon=pie_4_icon)        
        
        # # 6 - RIGHT
        # pie.operator("iops.split_area_pie_e", text=pie_6_text, icon=pie_6_icon) 
        
        # # 2 - BOTTOM
        # pie.operator("iops.split_area_pie_s", text=pie_2_text, icon=pie_2_icon )
        
        # # 8 - TOP
        # pie.operator("iops.split_area_pie_n", text=pie_8_text, icon=pie_8_icon )

        # # 7 - TOP - LEFT
        # pie.operator("iops.split_area_nw", text=pie_7_text, icon=pie_7_icon)
        
        # # 9 - TOP - RIGHT
        # pie.operator("iops.split_area_ne", text=pie_9_text, icon=pie_9_icon)

        # # 1 - BOTTOM - LEFT 
        # pie.operator("iops.split_area_se", text=pie_1_text, icon=pie_1_icon)
        
        # # 3 - BOTTOM - RIGHT
        # pie.operator("iops.split_area_sw", text=pie_3_text, icon=pie_3_icon) 
        # 
        # 4 - LEFT
        if pie_4_text != "Empty":
            pie.operator("iops.split_area_uv", text=pie_4_text, icon=pie_4_icon) 
        else:
            pie.separator()       
        
        # 6 - RIGHT
        if pie_6_text != "Empty":
            pie.operator("iops.split_area_uv", text=pie_6_text, icon=pie_6_icon) 
        else:
            pie.separator()  
        
        # 2 - BOTTOM
        if pie_2_text != "Empty":
            pie.operator("iops.split_area_uv", text=pie_2_text, icon=pie_2_icon) 
        else:
            pie.separator()  
        
        # 8 - TOP
        if pie_8_text != "Empty":
            pie.operator("iops.split_area_uv", text=pie_8_text, icon=pie_8_icon) 
        else:
            pie.separator()  

        # 7 - TOP - LEFT
        if pie_7_text != "Empty":
            pie.operator("iops.split_area_uv", text=pie_7_text, icon=pie_7_icon) 
        else:
            pie.separator()  
        
        # 9 - TOP - RIGHT
        if pie_9_text != "Empty":
            pie.operator("iops.split_area_uv", text=pie_9_text, icon=pie_9_icon) 
        else:
            pie.separator()  

        # 1 - BOTTOM - LEFT 
        if pie_1_text != "Empty":
            pie.operator("iops.split_area_uv", text=pie_1_text, icon=pie_1_icon) 
        else:
            pie.separator()  
        # 3 - BOTTOM - RIGHT
        if pie_3_text != "Empty":
            pie.operator("iops.split_area_uv", text=pie_3_text, icon=pie_3_icon) 
        else:
            pie.separator()  
             
       

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