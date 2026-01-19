import bpy
import ctypes
from ctypes import wintypes

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

    def open_new_window_standard(self, context, width=350, height=550):
        """Open a new window using bpy.ops.wm.window_new()."""
        # Use context override to ensure proper context for window_new operator
        # Include both window and screen for proper context
        with context.temp_override(window=context.window, screen=context.screen):
            bpy.ops.wm.window_new()

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

        # Get the window creation method from preferences
        prefs = context.preferences.addons["InteractionOps"].preferences
        window_method = prefs.modifier_window_method

        # Use the selected method to open a new window
        if window_method == "RENDER":
            # Use the render view show method to open a new window at the desired size
            self.open_new_window_with_size(350, 550)
        else:  # NEW_WINDOW
            # Use the standard window_new method with resize
            self.open_new_window_standard(context, 350, 550)

        # Get the new window (should be the last one created)
        new_window = context.window_manager.windows[-1]
        area = new_window.screen.areas[0]

        # Change the area type to Properties
        area.type = 'PROPERTIES'
        
        # For NEW_WINDOW method, resize now that window is renamed to Properties
        if window_method == "NEW_WINDOW":
            # Resize the Properties window immediately
            try:
                user32 = ctypes.windll.user32
                properties_hwnd = None
                
                def enum_handler(hwnd, lParam):
                    window_text = ctypes.create_unicode_buffer(512)
                    user32.GetWindowTextW(hwnd, window_text, 512)
                    if "Properties" in window_text.value:
                        nonlocal properties_hwnd
                        if properties_hwnd is None:
                            properties_hwnd = hwnd
                            return False  # Stop enumeration once found
                    return True
                
                EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
                user32.EnumWindows(EnumWindowsProc(enum_handler), 0)
                
                if properties_hwnd:
                    rect = wintypes.RECT()
                    user32.GetWindowRect(properties_hwnd, ctypes.byref(rect))
                    SWP_NOZORDER = 0x0004
                    user32.SetWindowPos(
                        properties_hwnd, None, rect.left, rect.top, 350, 550,
                        SWP_NOZORDER
                    )
            except Exception as e:
                print(f"Window resize failed: {e}")

        # Clean up render result image if it exists (only needed for render method)
        if window_method == "RENDER":
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
            if window_method == "RENDER":
                # For render method: show and flip navigation bar
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
            else:  # NEW_WINDOW method
                # For new window method: hide navigation bar and header
                # Hide navigation bar
                for region in area.regions:
                    if region.type == 'NAVIGATION_BAR':
                        # If region has size, it's visible - toggle to hide it
                        if region.width > 0 or region.height > 0:
                            try:
                                bpy.ops.screen.region_toggle(region_type='NAVIGATION_BAR')
                            except Exception as e:
                                print(f"Could not hide navigation bar: {e}")
                        break
                
                # Hide header
                for region in area.regions:
                    if region.type == 'HEADER':
                        # If region has size, it's visible - toggle to hide it
                        if region.width > 0 or region.height > 0:
                            try:
                                bpy.ops.screen.region_toggle(region_type='HEADER')
                            except Exception as e:
                                print(f"Could not hide header: {e}")
                        break

        # Report success with method used
        if window_method == "RENDER":
            self.report({'INFO'}, "Modifier window created using render method (350x550)")
        else:
            self.report({'INFO'}, "Modifier window created using new window method")
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


