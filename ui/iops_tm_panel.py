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
        row = layout.row(align=True)
        row.prop(tool_settings, "use_snap", text="")
        row.prop(tool_settings, "use_mesh_automerge", text="")

        
