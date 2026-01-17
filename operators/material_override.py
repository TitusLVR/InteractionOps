import bpy
import math


# Panel display mode preference
class IOPS_MaterialOverrideSettings(bpy.types.PropertyGroup):
    fancy_mode: bpy.props.BoolProperty(
        name="Fancy Mode",
        description="Show material thumbnail previews (slower, requires rendering)",
        default=False
    )
    is_rendering: bpy.props.BoolProperty(
        name="Is Rendering Previews",
        description="True when previews are currently being rendered",
        default=False
    )


class IOPS_OT_Material_Override_Clear_Rendering_Flag(bpy.types.Operator):
    """Clear the rendering warning (when previews are done)"""
    bl_idname = "iops.material_override_clear_rendering_flag"
    bl_label = "Clear Warning"
    bl_options = {'REGISTER', 'INTERNAL'}
    
    def execute(self, context):
        settings = context.scene.iops_material_override_settings
        settings.is_rendering = False
        
        # Redraw
        for area in context.screen.areas:
            area.tag_redraw()
        
        return {'FINISHED'}


class IOPS_OT_Material_Override_Refresh_Previews(bpy.types.Operator):
    """Force refresh all material previews and save them with the file"""
    bl_idname = "iops.material_override_refresh_previews"
    bl_label = "Refresh Previews"
    bl_options = {'REGISTER'}
    
    def execute(self, context):
        count = 0
        for mat in bpy.data.materials:
            # Clear the cached preview (non-blocking)
            mat.preview.reload()
            count += 1
        
        # Mark as rendering
        settings = context.scene.iops_material_override_settings
        settings.is_rendering = True
        
        self.report({'INFO'}, f"Cleared {count} material preview caches. They will re-render when displayed.")
        
        # Force redraw to trigger lazy re-render
        for area in context.screen.areas:
            area.tag_redraw()
        
        return {'FINISHED'}


class IOPS_OT_Material_Override_Generate_Previews(bpy.types.Operator):
    """Pre-generate all material previews for faster display (saves with file)"""
    bl_idname = "iops.material_override_generate_previews"
    bl_label = "Generate All Previews"
    bl_options = {'REGISTER'}
    
    def execute(self, context):
        # Mark as rendering
        settings = context.scene.iops_material_override_settings
        settings.is_rendering = True
        
        # Pre-generate all previews
        count = 0
        for mat in bpy.data.materials:
            # Ensure preview exists and is rendered
            mat.preview_ensure()
            count += 1
        
        self.report({'INFO'}, f"Generating {count} previews... Watch for the warning to disappear.")
        
        # Refresh UI
        for area in context.screen.areas:
            area.tag_redraw()
        
        return {'FINISHED'}


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
        
        # Header with Clear button
        header_row = col.row(align=True)
        header_row.alignment = 'CENTER'
        header_row.label(text="Current Override:", icon='RENDERLAYERS')

        if current_override:
            # Show current material with preview
            row = col.row(align=True)
            row.alignment = 'CENTER'
            try:
                row.template_icon(icon_value=current_override.preview.icon_id, scale=5.0)
                if current_override:
                    header_row = col.row(align=True)
                    header_row.alignment = 'CENTER'
                    header_row.operator("iops.material_override_clear", text="Clear", icon='X')
            except (AttributeError, ReferenceError, RuntimeError):
                # Fallback if preview is not available or invalid
                row.label(text="", icon='MATERIAL')
            row.label(text=current_override.name)
        else:
            col.label(text="None - Using object materials")

        layout.separator()

        # Info box
        info_row = layout.row(align=True)
        info_row.label(text=f"View Layer: {view_layer.name}", icon='RENDERLAYERS')

        layout.separator()

        # Get settings
        settings = context.scene.iops_material_override_settings
        
        # Materials section header with mode toggle
        row = layout.row(align=True)
        row.label(text="Available Materials:", icon='MATERIAL')
        
        # Fancy mode toggle
        fancy_icon = 'SHADING_RENDERED' if settings.fancy_mode else 'SHADING_SOLID'
        row.prop(settings, "fancy_mode", text="Fancy Mode", icon=fancy_icon, toggle=True)
        
        # Show preview controls only in fancy mode
        if settings.fancy_mode:
            row.operator("iops.material_override_generate_previews", text="", icon='RENDER_STILL')
            row.operator("iops.material_override_refresh_previews", text="", icon='FILE_REFRESH')
            
            # Show warning when in rendering mode (user controlled)
            if settings.is_rendering:
                warning_box = layout.box()
                warning_row = warning_box.row(align=True)
                warning_row.alert = True
                warning_row.label(text="⚠ Previews may be rendering, please wait...", icon='TIME')
                warning_row.operator("iops.material_override_clear_rendering_flag", text="", icon='X')
        
        # Get all materials
        materials = bpy.data.materials

        if not materials:
            box = layout.box()
            box.label(text="No materials in scene", icon='INFO')
        else:
            row = layout.row(align=True)
            row.label(text=f"({len(materials)})")

            layout.separator(factor=0.5)
            
            materials_list = list(materials)
            num_materials = len(materials_list)
            
            # FANCY MODE - Grid with thumbnails
            if settings.fancy_mode:
                # Material grid with dynamic column calculation
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
                            try:
                                icon_row.template_icon(icon_value=mat.preview.icon_id, scale=5.0)
                            except (AttributeError, ReferenceError, RuntimeError):
                                # Fallback if preview is not available or invalid
                                icon_row.label(text="", icon='MATERIAL')
                            
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
            
            # SIMPLE MODE - Just a list
            else:
                box = layout.box()
                col = box.column(align=True)
                
                for mat in materials_list:
                    row = col.row(align=True)
                    
                    # Material icon
                    icon = 'SHADING_RENDERED' if mat.use_nodes else 'MATERIAL_DATA'
                    row.label(text="", icon=icon)
                    
                    # Material name and apply button
                    if current_override and mat.name == current_override.name:
                        btn = row.operator(
                            "iops.material_override_apply",
                            text=f"✓ {mat.name}",
                            depress=True
                        )
                        btn.material_name = mat.name
                    else:
                        btn = row.operator(
                            "iops.material_override_apply",
                            text=mat.name
                        )
                        btn.material_name = mat.name


class IOPS_OT_Call_Material_Override_Panel(bpy.types.Operator):
    """Open View Layer Material Override Panel"""

    bl_idname = "iops.call_panel_material_override"
    bl_label = "View Layer Material Override"
    bl_description = "Set material override for the active view layer"

    @classmethod
    def poll(cls, context):
        return context.area and context.area.type == "VIEW_3D"

    def invoke(self, context, event):
        # Simple approach - just try to open, catch error if busy
        try:
            bpy.ops.wm.call_panel('INVOKE_DEFAULT', name="IOPS_PT_Material_Override_Panel", keep_open=True)
            return {'FINISHED'}
        except RuntimeError as e:
            if "drawing/rendering" in str(e):
                self.report({'INFO'}, "Blender is busy, try again in a moment")
            else:
                self.report({'WARNING'}, f"Could not open panel: {str(e)}")
            return {'CANCELLED'}
    
    def execute(self, context):
        # Fallback for non-interactive calls
        return self.invoke(context, None)