import bpy
import math


class IOPS_OT_Material_Override_Apply(bpy.types.Operator):
    """Set view layer material override for rendering"""
    bl_idname = "iops.material_override_apply"
    bl_label = "Set Material Override"
    bl_options = {'REGISTER', 'UNDO'}

    material_name: bpy.props.StringProperty(name="Material Name")

    def execute(self, context):
        if not self.material_name or self.material_name not in bpy.data.materials:
            self.report({'WARNING'}, "Invalid material")
            return {'CANCELLED'}

        material = bpy.data.materials[self.material_name]

        # Set the material override for the active view layer
        context.view_layer.material_override = material

        self.report({'INFO'}, f"View Layer material override set to '{material.name}'")

        # Refresh the viewport and panel
        for area in context.screen.areas:
            area.tag_redraw()

        return {'FINISHED'}


class IOPS_OT_Material_Override_Clear(bpy.types.Operator):
    """Clear view layer material override"""
    bl_idname = "iops.material_override_clear"
    bl_label = "Clear Material Override"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # Clear the material override
        context.view_layer.material_override = None

        self.report({'INFO'}, "View Layer material override cleared")

        # Refresh the viewport and panel
        for area in context.screen.areas:
            area.tag_redraw()

        return {'FINISHED'}


class IOPS_PT_Material_Override_Panel(bpy.types.Panel):
    """View Layer Material Override Panel"""

    bl_label = "Material Override"
    bl_idname = "IOPS_PT_Material_Override_Panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"

    def draw(self, context):
        layout = self.layout
        layout.ui_units_x = 25

        # Current override status
        view_layer = context.view_layer
        current_override = view_layer.material_override

        box = layout.box()
        col = box.column(align=True)
        row = col.row(align=True)
        row.label(text="Current Override:", icon='RENDERLAYERS')

        if current_override:
            row.operator("iops.material_override_clear", text="Clear", icon='X')

            # Show current material with preview
            row = col.row(align=True)
            row.scale_y = 1.2
            row.template_icon(icon_value=current_override.preview.icon_id, scale=2.0)
            row.label(text=current_override.name)
        else:
            row.label(text="None")
            col.label(text="Using object materials")

        layout.separator()

        # Info box
        info_row = layout.row(align=True)
        info_row.label(text=f"View Layer: {view_layer.name}", icon='RENDERLAYERS')

        layout.separator()

        # Materials section header
        row = layout.row(align=True)
        row.label(text="Available Materials:", icon='MATERIAL')

        # Get all materials
        materials = bpy.data.materials

        if not materials:
            box = layout.box()
            box.label(text="No materials in scene", icon='INFO')
        else:
            row.label(text=f"({len(materials)})")

            layout.separator(factor=0.5)
            
            # Material grid with dynamic column calculation
            materials_list = list(materials)
            num_materials = len(materials_list)
            
            # Calculate optimal grid dimensions for 5:3 aspect ratio (width:height)
            # From aspect ratio: columns/rows = 5/3
            # From fitting all materials: columns * rows >= num_materials
            # Solving: rows = sqrt(num_materials * 3/5)
            optimal_rows = math.sqrt(num_materials * 3.0 / 5.0)
            rows = max(1, int(math.ceil(optimal_rows)))
            grid_columns = max(1, int(math.ceil(num_materials / rows)))
            
            for row_start in range(0, num_materials, grid_columns):
                row = layout.row(align=True)
                
                for i in range(grid_columns):
                    mat_index = row_start + i
                    
                    if mat_index < num_materials:
                        mat = materials_list[mat_index]
                        col = row.column(align=True)
                        
                        # Create a box for each material
                        box = col.box()
                        box_col = box.column(align=True)
                        
                        # Preview icon at the top - using template_icon for actual scaling
                        icon_row = box_col.row(align=True)
                        icon_row.alignment = 'CENTER'
                        icon_row.template_icon(icon_value=mat.preview.icon_id, scale=5.0)
                        
                        # Add spacing
                        box_col.separator(factor=0.5)
                        
                        # Select button with material name
                        btn_row = box_col.row(align=True)
                        btn_row.scale_y = 1
                        
                        # Truncate long names
                        display_name = mat.name if len(mat.name) <= 12 else mat.name[:11] + "…"
                        
                        if current_override and mat.name == current_override.name:
                            btn = btn_row.operator(
                                "iops.material_override_apply",
                                text=f"✓ {display_name}",
                                depress=True
                            )
                            btn.material_name = mat.name
                        else:
                            btn = btn_row.operator(
                                "iops.material_override_apply",
                                text=display_name
                            )
                            btn.material_name = mat.name
                    else:
                        # Empty space to maintain grid alignment
                        col = row.column(align=True)
                        col.label(text="")
                
                # Add spacing between rows
                layout.separator(factor=0.5)



class IOPS_OT_Call_Material_Override_Panel(bpy.types.Operator):
    """Open View Layer Material Override Panel"""

    bl_idname = "iops.call_panel_material_override"
    bl_label = "View Layer Material Override"
    bl_description = "Set material override for the active view layer"

    @classmethod
    def poll(cls, context):
        return context.area.type == "VIEW_3D"

    def execute(self, _context):
        bpy.ops.wm.call_panel(name="IOPS_PT_Material_Override_Panel", keep_open=True)
        return {'FINISHED'}
