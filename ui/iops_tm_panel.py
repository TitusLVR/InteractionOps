import bpy
from bpy.types import VIEW3D_PT_transform_orientations, VIEW3D_PT_pivot_point, VIEW3D_PT_snapping


class IOPS_PT_iops_tm_panel(bpy.types.Panel):
    """Creates a Panel from Tranformation,PivotPoint,Snapping panels"""
    bl_label = "IOPS TPS"
    bl_idname = "IOPS_PT_iops_tm_panel" 
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Item' 

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=250)

    def execute(self, context):
        return {'FINISHED'}  

    def draw(self, context):
        tool_settings = context.tool_settings
        layout = self.layout         
        row = layout.row(align=True)
        row.prop(tool_settings, "use_snap", text="")
        row.prop(tool_settings, "use_mesh_automerge", text="")
        
        VIEW3D_PT_transform_orientations.draw(self, context)
        VIEW3D_PT_pivot_point.draw(self, context)
        VIEW3D_PT_snapping.draw(self,context)
        # row.popover('VIEW3D_PT_transform_orientations', text="Transform", text_ctxt="", translate=True, icon='ORIENTATION_GLOBAL', icon_value=0)
        # row.popover('VIEW3D_PT_pivot_point', text="PivotPoint", text_ctxt="", translate=True, icon='PIVOT_INDIVIDUAL', icon_value=0)
        # row.popover('VIEW3D_PT_snapping', text="Snapping", text_ctxt="", translate=True, icon='SNAP_ON', icon_value=0) 
    
    # def draw(self, context):
    #     tool_settings = context.tool_settings

    #     layout = self.layout
    #     layout.use_property_decorate = True
    #     layout.use_property_split = False
    #     layout.grid_flow(row_major=True, columns=3, even_columns=False, even_rows=False, align=False)
    #     layout.ui_units_x = 8.0        
    #     row = layout.row(align=True)        
    #     row.prop(tool_settings, "use_snap", text="")
    #     row.prop(tool_settings, "use_mesh_automerge", text="")
        

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
        


        


        



        
