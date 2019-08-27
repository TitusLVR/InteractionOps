import bpy


class IOPS_PT_iops_tm_panel(bpy.types.Panel):
    """Creates a Panel from Tranformation,PivotPoint,Snapping panels"""
    bl_label = "IOPS TPS"
    bl_idname = "IOPS_PT_iops_tm_panel" 
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Item'   

    def draw(self, context):
        tool_settings = context.tool_settings

        layout = self.layout
        layout.ui_units_x = 8.0        
        row = layout.row(align=True)
        row.prop(tool_settings, "use_snap", text="")
        row.prop(tool_settings, "use_mesh_automerge", text="")

class IOPS_PT_iops_transform_panel(bpy.types.Panel):
    """Creates a Panel from Tranformation,PivotPoint,Snapping panels"""
    bl_label = "IOPS TM"
    bl_idname = "IOPS_PT_iops_transform_panel" 
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Item'    
    bl_options = {'DEFAULT_CLOSED'}    

    @classmethod
    def poll(self, context):
        return (context.area.type == "VIEW_3D" and                
                len(context.view_layer.objects.selected) != 0 and
                context.view_layer.objects.active.type == "MESH")   

    def draw(self, context):        
        obj = context.view_layer.objects.active
        layout = self.layout
        layout.ui_units_x = 8.0      
        col = layout.column(align=True)
        col.prop(obj, "location")
        col.prop(obj, "rotation_euler")
        col.prop(obj, "scale")
        col.prop(obj, "dimensions")
        


        


        



        
