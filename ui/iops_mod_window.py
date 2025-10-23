import bpy


class IOPS_OT_Modifier_Window(bpy.types.Operator):
    """Creates a new window for Modifiers at 300x600 size"""

    bl_idname = "iops.window_modifiers"
    bl_label = "IOPS Modifiers Window"
    bl_description = "Create a new window and switch to Properties > Modifiers panel (300x600)"
    bl_options = {'REGISTER', 'UNDO'}

    def open_new_window_with_size(self, width, height):
        """Open a new window using render view show method with resolution sizing."""
        scene = bpy.context.scene
        original_x = scene.render.resolution_x
        original_y = scene.render.resolution_y

        # Set new resolution
        scene.render.resolution_x = width
        scene.render.resolution_y = height

        # Open a new window using render view
        bpy.ops.render.view_show("INVOKE_DEFAULT")

        # Restore original resolution
        scene.render.resolution_x = original_x
        scene.render.resolution_y = original_y

    def execute(self, context):
        # Check if we have a valid context for window operations
        if not context.window_manager or not context.window_manager.windows:
            self.report({'ERROR'}, "No valid window context available")
            return {'CANCELLED'}

        # Check if modifier window exists - if yes, close it; if no, create it
        if self.modifier_window_exists():
            self.close_existing_modifier_window()
            self.report({'INFO'}, "Modifier window closed")
            return {'FINISHED'}

        # Use the render view show method to open a new window at the desired size
        self.open_new_window_with_size(350, 550)

        # Get the new window (should be the last one created)
        new_window = context.window_manager.windows[-1]
        area = new_window.screen.areas[0]

        # Change the area type to Properties
        area.type = 'PROPERTIES'

        # Clean up render result image if it exists
        if 'Render Result' in bpy.data.images:
            render_result = bpy.data.images['Render Result']
            bpy.data.images.remove(render_result)

        # Configure the Properties panel to show only Modifiers
        if area.spaces and len(area.spaces) > 0:
            space = area.spaces.active
            if space and space.type == 'PROPERTIES':
                # Hide all other property tabs, show only modifiers
                space.show_properties_tool = False
                space.show_properties_scene = False
                space.show_properties_render = False
                space.show_properties_output = False
                space.show_properties_view_layer = False
                space.show_properties_world = False
                space.show_properties_collection = False
                space.show_properties_object = False
                space.show_properties_constraints = False
                space.show_properties_modifiers = True  # Only show modifiers
                space.show_properties_data = False
                space.show_properties_bone = False
                space.show_properties_bone_constraints = False
                space.show_properties_material = False
                space.show_properties_texture = False
                space.show_properties_particles = False
                space.show_properties_physics = False
                space.show_properties_effects = False

        # Configure navigation bar alignment and visibility
        # Override context to target the new window
        with context.temp_override(window=new_window, area=area):
            # First, ensure navigation bar is visible
            bpy.ops.screen.region_toggle(region_type='NAVIGATION_BAR')
            # Toggle alignment to move navigation bar to the right
            for region in area.regions:
                if region.type == 'NAVIGATION_BAR':
                    # Found the navigation bar region, now flip its alignment
                    with context.temp_override(region=region):
                        try:
                            bpy.ops.screen.region_flip()
                        except Exception as e:
                            print(f"Could not flip navigation bar alignment: {e}")
                    break

        # Force a redraw to ensure window is fully initialized
        bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)

        self.report({'INFO'}, "Modifier window created and sized using render resolution trick (300x600)")
        return {'FINISHED'}

    def modifier_window_exists(self):
        """Check if a modifier window already exists"""
        if len(bpy.context.window_manager.windows) <= 1:
            return False  # Only main window exists
            
        # Find floating windows that could be modifier windows
        for window in bpy.context.window_manager.windows[1:]:  # Skip main window
            if window.screen and window.screen.areas:
                # Check if this is a single-area Properties window
                if len(window.screen.areas) == 1:
                    area = window.screen.areas[0]
                    if area.type == 'PROPERTIES':
                        return True
        return False

    def close_existing_modifier_window(self):
        """Close any existing modifier windows"""
        if len(bpy.context.window_manager.windows) <= 1:
            return  # Only main window exists, nothing to close

        windows_to_close = []

        # Find floating windows that could be modifier windows
        for window in bpy.context.window_manager.windows[1:]:  # Skip main window
            if window.screen and window.screen.areas:
                # Check if this is a single-area Properties window
                if len(window.screen.areas) == 1:
                    area = window.screen.areas[0]
                    if area.type == 'PROPERTIES':
                        windows_to_close.append(window)
                        print("Found Properties window to close")

        # Close the found windows
        for window in windows_to_close:
            try:
                # Override context to close the specific window (without screen override)
                with bpy.context.temp_override(window=window):
                    bpy.ops.wm.window_close()
                print("Closed existing Properties window")
            except Exception as e:
                print(f"Could not close window: {e}")


