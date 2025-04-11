import bpy
import mathutils
from mathutils import Vector
import math # For ceil

# --- Helper Functions (get_object_bbox_data, get_target_world_pos) ---
# (Keep the helper functions from the previous script exactly as they were)
# ... (omitting them here for brevity, but they are needed) ...
def get_object_bbox_data(obj, depsgraph):
    """
    Calculates world space bounding box data for an evaluated object.
    Returns a dictionary with 'min', 'max', 'center', 'dim', 'volume', 
    'world_bbox_center_offset', 'obj_origin'.
    """
    if not obj or obj.type != 'MESH':
        # print(f"Debug: Skipping non-mesh or null object: {obj.name if obj else 'None'}")
        return None

    try:
        eval_obj = obj.evaluated_get(depsgraph)
        if not eval_obj.bound_box:
            if eval_obj.data and not eval_obj.data.vertices:
                 # print(f"Info: Object '{obj.name}' has empty mesh data. Using origin as point.")
                 loc = eval_obj.matrix_world.translation
                 zero_vec = Vector((0,0,0))
                 return {
                    'min': loc, 'max': loc, 'center': loc,
                    'dim': zero_vec, 'volume': 0.0,
                    'world_bbox_center_offset': zero_vec, # Approximation
                    'obj_origin': loc
                 }
            else:
                # print(f"Warning: Object '{obj.name}' has no bounding box data. Skipping.")
                return None
                
        bbox_corners_local = [Vector(corner) for corner in eval_obj.bound_box]
    except (RuntimeError, ReferenceError) as e:
        # print(f"Warning: Could not evaluate object '{obj.name}'. Error: {e}. Skipping.")
        return None

    bbox_corners_world = [eval_obj.matrix_world @ corner for corner in bbox_corners_local]

    if not bbox_corners_world:
        # print(f"Debug: No world bbox corners for {obj.name}")
        return None

    min_coord = Vector((min(v.x for v in bbox_corners_world),
                        min(v.y for v in bbox_corners_world),
                        min(v.z for v in bbox_corners_world)))
    max_coord = Vector((max(v.x for v in bbox_corners_world),
                        max(v.y for v in bbox_corners_world),
                        max(v.z for v in bbox_corners_world)))

    world_dim = max_coord - min_coord
    world_dim.x = max(world_dim.x, 0.0)
    world_dim.y = max(world_dim.y, 0.0)
    world_dim.z = max(world_dim.z, 0.0)
    
    world_center = (min_coord + max_coord) / 2.0
    volume = world_dim.x * world_dim.y * world_dim.z

    # Calculate local center offset (bbox center relative to object origin)
    local_bbox_center = Vector((0.0, 0.0, 0.0))
    for corner in bbox_corners_local:
        local_bbox_center += corner
    if len(bbox_corners_local) > 0: # Avoid division by zero for empty bound_box list
        local_bbox_center /= len(bbox_corners_local)
    
    # Offset of the world bbox center from the object's world origin
    world_bbox_center_offset = world_center - eval_obj.matrix_world.translation

    return {
        'min': min_coord,
        'max': max_coord,
        'center': world_center,
        'dim': world_dim,
        'volume': volume,
        'world_bbox_center_offset': world_bbox_center_offset,
        'obj_origin': eval_obj.matrix_world.translation
    }

def get_target_world_pos(current_obj_bbox, target_align_point, align_x, align_y, align_z):
    """
    Calculates the required world OBJECT ORIGIN position to place the object
    so its alignment point (min/center/max) matches the target_align_point.
    """
    if not current_obj_bbox: return None

    current_origin = current_obj_bbox['obj_origin']
    current_align_point = Vector(current_obj_bbox['center']) # Start with center

    if align_x == 'MIN': current_align_point.x = current_obj_bbox['min'].x
    elif align_x == 'MAX': current_align_point.x = current_obj_bbox['max'].x
    if align_y == 'MIN': current_align_point.y = current_obj_bbox['min'].y
    elif align_y == 'MAX': current_align_point.y = current_obj_bbox['max'].y
    if align_z == 'MIN': current_align_point.z = current_obj_bbox['min'].z
    elif align_z == 'MAX': current_align_point.z = current_obj_bbox['max'].z

    translation_needed = target_align_point - current_align_point
    new_origin_pos = current_origin + translation_needed
    
    return new_origin_pos
# --- End Helper Functions ---


# --- Main Operator ---
class IOPS_OT_KitBash_Grid(bpy.types.Operator):
    """Sort selected objects based on bounding box, starting from active"""
    bl_idname = "iops.object_kitbash_grid"
    bl_label = "Sort Selected by BBox"
    bl_options = {'REGISTER', 'UNDO'} # Enable Undo

    # --- Properties (Keep all properties from the previous script) ---
    # arrange_mode, grid_columns, arrange_axis, gap_x, gap_y, 
    # sort_by, align_x, align_y, align_z
    # ... (omitting them here for brevity, but they are needed) ...
    # --- Arrangement Properties ---
    arrange_mode: bpy.props.EnumProperty(
        name="Mode",
        items=[('LINEAR', "Linear", "Arrange objects in a single line"),
               ('GRID', "Grid", "Arrange objects in a grid")],
        default='LINEAR',
        description="How to arrange the objects"
    )

    grid_columns: bpy.props.IntProperty(
        name="Columns",
        default=5,
        min=1,
        description="Number of columns for grid arrangement"
    )

    arrange_axis: bpy.props.EnumProperty(
        name="Primary Axis",
        items=[('X', "X Axis", "Primary arrangement axis (for Linear mode, or columns in Grid)"),
               ('Y', "Y Axis", "Primary arrangement axis (for Linear mode, or columns in Grid)")],
        default='X',
        description="Main axis for arrangement"
    )

    # --- Gap Properties ---
    gap_x: bpy.props.FloatProperty(
        name="Gap X",
        description="Gap between object bounding boxes along X",
        default=0.1,
        min=0.0,
        subtype='DISTANCE', unit='LENGTH'
    )
    gap_y: bpy.props.FloatProperty(
        name="Gap Y",
        description="Gap between object bounding boxes along Y",
        default=0.1,
        min=0.0,
        subtype='DISTANCE', unit='LENGTH'
    )

    # --- Sorting Properties ---
    sort_by: bpy.props.EnumProperty(
        name="Sort By",
        items=[
            ('VOLUME', "Volume", "Sort by bounding box volume (Smallest first)"),
            ('X_DIM', "X Dimension", "Sort by bounding box X dimension (Smallest first)"),
            ('Y_DIM', "Y Dimension", "Sort by bounding box Y dimension (Smallest first)"),
            ('Z_DIM', "Z Dimension", "Sort by bounding box Z dimension (Smallest first)"),
            ('VOLUME_INV', "Volume (Inv)", "Sort by bounding box volume (Largest first)"),
            ('X_DIM_INV', "X Dimension (Inv)", "Sort by bounding box X dimension (Largest first)"),
            ('Y_DIM_INV', "Y Dimension (Inv)", "Sort by bounding box Y dimension (Largest first)"),
            ('Z_DIM_INV', "Z Dimension (Inv)", "Sort by bounding box Z dimension (Largest first)"),
            ('NAME', "Name", "Sort alphabetically by object name"),
            ('NAME_INV', "Name (Inv)", "Sort reverse alphabetically by object name"),
        ],
        default='VOLUME',
        description="Criterion for sorting objects"
    )

    # --- Alignment Properties ---
    align_x: bpy.props.EnumProperty(
        name="Align X",
        items=[('MIN', "Min X (Left)", "Align objects by their minimum X extent"),
               ('CENTER', "Center X", "Align objects by their X center"),
               ('MAX', "Max X (Right)", "Align objects by their maximum X extent")],
        default='CENTER',
        description="Alignment along the X axis"
    )
    align_y: bpy.props.EnumProperty(
        name="Align Y",
        items=[('MIN', "Min Y (Back)", "Align objects by their minimum Y extent"),
               ('CENTER', "Center Y", "Align objects by their Y center"),
               ('MAX', "Max Y (Front)", "Align objects by their maximum Y extent")],
        default='CENTER',
        description="Alignment along the Y axis"
    )
    align_z: bpy.props.EnumProperty(
        name="Align Z",
        items=[('MIN', "Min Z (Bottom)", "Align objects by their minimum Z extent"),
               ('CENTER', "Center Z", "Align objects by their Z center"),
               ('MAX', "Max Z (Top)", "Align objects by their maximum Z extent")],
        default='CENTER',
        description="Alignment along the Z axis"
    )
    # --- End Properties ---
    
    # --- Draw method (Keep as before) ---
    def draw(self, context):
        layout = self.layout
        
        box = layout.box()
        box.label(text="Arrangement")
        box.prop(self, "arrange_mode")
        if self.arrange_mode == 'GRID':
            box.prop(self, "grid_columns")
            box.prop(self, "arrange_axis", text="Grid Direction Axis") # X means columns go along X
        else:
             box.prop(self, "arrange_axis", text="Linear Axis")
        row = box.row(align=True)
        row.prop(self, "gap_x")
        row.prop(self, "gap_y")

        box = layout.box()
        box.label(text="Sorting")
        box.prop(self, "sort_by")
        
        box = layout.box()
        box.label(text="Alignment")
        row = box.row(align=True)
        row.prop(self, "align_x", text="")
        row.prop(self, "align_y", text="")
        row.prop(self, "align_z", text="")
        row.label(text="Align (X, Y, Z)")
    # --- End Draw ---

    # --- Execution Logic ---
    def execute(self, context):
        active_obj = context.active_object
        # *** CHANGE: Include active object in the list to be processed ***
        selected_objs_all = list(context.selected_objects) # Use all selected

        if not active_obj:
            # Still need an active object to define the STARTING reference point, even if it moves later
            self.report({'WARNING'}, "Active object required to define starting reference point.")
            return {'CANCELLED'}
        if len(selected_objs_all) < 1: # Need at least one object (which would be the active one)
            self.report({'INFO'}, "Select at least one object (the active object).")
            return {'CANCELLED'}

        depsgraph = context.evaluated_depsgraph_get()

        # --- 1. Get STARTING Reference Data from Active Object (BEFORE it potentially moves) ---
        initial_active_bbox_data = get_object_bbox_data(active_obj, depsgraph)
        if initial_active_bbox_data is None:
            self.report({'WARNING'}, "Could not get bounding box for the initial active object. Ensure it's a Mesh.")
            return {'CANCELLED'}
            
        # Determine the absolute starting reference point based on initial active obj & alignment
        initial_active_ref_point = Vector(initial_active_bbox_data['center'])
        if self.align_x == 'MIN': initial_active_ref_point.x = initial_active_bbox_data['min'].x
        elif self.align_x == 'MAX': initial_active_ref_point.x = initial_active_bbox_data['max'].x
        if self.align_y == 'MIN': initial_active_ref_point.y = initial_active_bbox_data['min'].y
        elif self.align_y == 'MAX': initial_active_ref_point.y = initial_active_bbox_data['max'].y
        if self.align_z == 'MIN': initial_active_ref_point.z = initial_active_bbox_data['min'].z
        elif self.align_z == 'MAX': initial_active_ref_point.z = initial_active_bbox_data['max'].z
        
        # Store the initial max edges needed to start the placement cursors
        initial_active_max_x = initial_active_bbox_data['max'].x
        initial_active_max_y = initial_active_bbox_data['max'].y


        # --- 2. Get Data & Filter for Valid Objects (Now includes active obj) ---
        object_data = []
        valid_selection_count = 0
        for obj in selected_objs_all: # Iterate through ALL selected objects
            if not obj or obj.name not in context.scene.objects: continue # Check existence
            
            bbox_data = get_object_bbox_data(obj, depsgraph)
            if bbox_data is None: continue

            # --- Sorting Key Calculation (same as before) ---
            sort_key_base = 0
            sort_key_name = self.sort_by.replace('_INV', '')
            reverse_sort = '_INV' in self.sort_by
            if sort_key_name == 'VOLUME': sort_key_base = bbox_data['volume']
            elif sort_key_name == 'X_DIM': sort_key_base = bbox_data['dim'].x
            elif sort_key_name == 'Y_DIM': sort_key_base = bbox_data['dim'].y
            elif sort_key_name == 'Z_DIM': sort_key_base = bbox_data['dim'].z
            elif sort_key_name == 'NAME': sort_key_base = obj.name
            if isinstance(sort_key_base, (int, float)):
                sort_key = -sort_key_base if reverse_sort else sort_key_base
            else: sort_key = sort_key_base
            # --- End Sorting Key ---

            object_data.append({
                'obj': obj,
                'sort_key': sort_key,
                'initial_bbox': bbox_data,
            })
            valid_selection_count += 1

        if not object_data:
            self.report({'WARNING'}, "No valid mesh objects found in selection.")
            return {'CANCELLED'}

        # --- 3. Sort the Objects (incl. active) ---
        sort_reverse_flag = False
        if isinstance(object_data[0]['sort_key'], str) and '_INV' in self.sort_by:
             sort_reverse_flag = True
        object_data.sort(key=lambda d: d['sort_key'], reverse=sort_reverse_flag)

        # --- 4. Placement ---
        
        # --- Linear Arrangement ---
        if self.arrange_mode == 'LINEAR':
            primary_axis_idx = 0 if self.arrange_axis == 'X' else 1
            secondary_axis_idx = 1 if self.arrange_axis == 'X' else 0
            gap_primary = self.gap_x if self.arrange_axis == 'X' else self.gap_y

            # *** CHANGE: Cursor starts relative to the STORED initial active object's position ***
            current_cursor_primary = initial_active_bbox_data['max'][primary_axis_idx] if primary_axis_idx==0 else initial_active_bbox_data['max'][primary_axis_idx]

            # Place the VERY FIRST object relative to the initial active object pos
            is_first_object = True
            
            for i, data in enumerate(object_data):
                obj = data['obj']
                current_obj_bbox = get_object_bbox_data(obj, depsgraph)
                if not current_obj_bbox: continue

                obj_dim_primary = current_obj_bbox['dim'][primary_axis_idx]

                # Calculate Target Alignment Point
                target_min_primary = 0
                if is_first_object:
                     # Place first object relative to initial active max edge + gap
                     target_min_primary = (initial_active_max_x if primary_axis_idx == 0 else initial_active_max_y) + gap_primary
                else:
                     # Subsequent objects relative to the previous object's max edge + gap
                     target_min_primary = current_cursor_primary + gap_primary # current_cursor updated at end of loop

                # Calculate target point coord based on alignment (same logic as before)
                target_primary_coord = 0
                if self.align_x == 'MIN' and primary_axis_idx == 0: target_primary_coord = target_min_primary
                elif self.align_x == 'CENTER' and primary_axis_idx == 0: target_primary_coord = target_min_primary + obj_dim_primary / 2.0
                elif self.align_x == 'MAX' and primary_axis_idx == 0: target_primary_coord = target_min_primary + obj_dim_primary
                elif self.align_y == 'MIN' and primary_axis_idx == 1: target_primary_coord = target_min_primary
                elif self.align_y == 'CENTER' and primary_axis_idx == 1: target_primary_coord = target_min_primary + obj_dim_primary / 2.0
                elif self.align_y == 'MAX' and primary_axis_idx == 1: target_primary_coord = target_min_primary + obj_dim_primary
                else: target_primary_coord = target_min_primary + obj_dim_primary / 2.0

                # Assemble full target alignment vector (use STORED initial active ref for other axes)
                target_align_point = Vector((0, 0, 0))
                target_align_point[primary_axis_idx] = target_primary_coord
                target_align_point[secondary_axis_idx] = initial_active_ref_point[secondary_axis_idx] # Align secondary based on initial active ref
                target_align_point[2] = initial_active_ref_point[2] # Align Z based on initial active ref

                # Calculate and Apply Translation
                target_origin_pos = get_target_world_pos(current_obj_bbox, target_align_point, self.align_x, self.align_y, self.align_z)
                
                if target_origin_pos:
                     obj.location = target_origin_pos
                     depsgraph.update() # Update after move

                     # Update Cursor using the object JUST PLACED
                     placed_bbox = get_object_bbox_data(obj, depsgraph)
                     if placed_bbox:
                          current_cursor_primary = placed_bbox['max'][primary_axis_idx]
                     else: 
                          current_cursor_primary = target_min_primary + obj_dim_primary # Estimate
                     
                     is_first_object = False # No longer the first object
                else:
                    print(f"Warning: Could not calculate target position for {obj.name}")

        # --- Grid Arrangement ---
        elif self.arrange_mode == 'GRID':
            cols = max(1, self.grid_columns)
            primary_axis_idx = 0 if self.arrange_axis == 'X' else 1
            secondary_axis_idx = 1 if self.arrange_axis == 'X' else 0
            gap_primary = self.gap_x if self.arrange_axis == 'X' else self.gap_y
            gap_secondary = self.gap_y if self.arrange_axis == 'X' else self.gap_x

            # *** CHANGE: Initialization relative to STORED initial active object pos ***
            row_start_cursor_secondary = initial_active_bbox_data['max'][secondary_axis_idx]
            col_start_cursor_primary = initial_active_bbox_data['max'][primary_axis_idx]

            current_cursor_primary = col_start_cursor_primary
            current_cursor_secondary = row_start_cursor_secondary
            max_dim_secondary_in_row = 0.0
            is_first_row = True # Flag to handle first row positioning

            for i, data in enumerate(object_data):
                obj = data['obj']
                col_idx = i % cols
                row_idx = i // cols

                # New Row
                if col_idx == 0 and i > 0:
                    current_cursor_secondary += max_dim_secondary_in_row + gap_secondary
                    current_cursor_primary = col_start_cursor_primary # Reset X/Y cursor for row start
                    max_dim_secondary_in_row = 0.0
                    is_first_row = False

                # Process Object
                current_obj_bbox = get_object_bbox_data(obj, depsgraph)
                if not current_obj_bbox: continue

                obj_dim_primary = current_obj_bbox['dim'][primary_axis_idx]
                obj_dim_secondary = current_obj_bbox['dim'][secondary_axis_idx]

                # Calculate Target Alignment Point
                target_min_primary = 0
                if col_idx == 0: # First object in ANY row
                     target_min_primary = col_start_cursor_primary + gap_primary
                else: # Subsequent objects in row
                     target_min_primary = current_cursor_primary + gap_primary # Use updated cursor

                target_min_secondary = 0
                if is_first_row: # First row starts relative to initial active object
                     target_min_secondary = row_start_cursor_secondary + gap_secondary
                else: # Subsequent rows use the updated secondary cursor
                     target_min_secondary = current_cursor_secondary + gap_secondary


                # Calculate target coords based on alignment (same logic as before)
                target_primary_coord = 0
                # ... (copy alignment logic for target_primary_coord from Linear section) ...
                if self.align_x == 'MIN' and primary_axis_idx == 0: target_primary_coord = target_min_primary
                elif self.align_x == 'CENTER' and primary_axis_idx == 0: target_primary_coord = target_min_primary + obj_dim_primary / 2.0
                elif self.align_x == 'MAX' and primary_axis_idx == 0: target_primary_coord = target_min_primary + obj_dim_primary
                elif self.align_y == 'MIN' and primary_axis_idx == 1: target_primary_coord = target_min_primary
                elif self.align_y == 'CENTER' and primary_axis_idx == 1: target_primary_coord = target_min_primary + obj_dim_primary / 2.0
                elif self.align_y == 'MAX' and primary_axis_idx == 1: target_primary_coord = target_min_primary + obj_dim_primary
                else: target_primary_coord = target_min_primary + obj_dim_primary / 2.0 # Fallback Center
                
                target_secondary_coord = 0
                # ... (copy alignment logic for target_secondary_coord from Linear section) ...
                if self.align_y == 'MIN' and secondary_axis_idx == 1: target_secondary_coord = target_min_secondary
                elif self.align_y == 'CENTER' and secondary_axis_idx == 1: target_secondary_coord = target_min_secondary + obj_dim_secondary / 2.0
                elif self.align_y == 'MAX' and secondary_axis_idx == 1: target_secondary_coord = target_min_secondary + obj_dim_secondary
                elif self.align_x == 'MIN' and secondary_axis_idx == 0: target_secondary_coord = target_min_secondary
                elif self.align_x == 'CENTER' and secondary_axis_idx == 0: target_secondary_coord = target_min_secondary + obj_dim_secondary / 2.0
                elif self.align_x == 'MAX' and secondary_axis_idx == 0: target_secondary_coord = target_min_secondary + obj_dim_secondary
                else: target_secondary_coord = target_min_secondary + obj_dim_secondary / 2.0 # Fallback Center


                # Assemble full target alignment vector (use STORED initial active ref for Z)
                target_align_point = Vector((0, 0, 0))
                target_align_point[primary_axis_idx] = target_primary_coord
                target_align_point[secondary_axis_idx] = target_secondary_coord
                target_align_point[2] = initial_active_ref_point[2] # Align Z based on initial active ref

                # Calculate and Apply Translation
                target_origin_pos = get_target_world_pos(current_obj_bbox, target_align_point, self.align_x, self.align_y, self.align_z)

                if target_origin_pos:
                     obj.location = target_origin_pos
                     depsgraph.update()

                     # Update Cursors and Max Dim
                     placed_bbox = get_object_bbox_data(obj, depsgraph)
                     if placed_bbox:
                          current_cursor_primary = placed_bbox['max'][primary_axis_idx]
                          max_dim_secondary_in_row = max(max_dim_secondary_in_row, placed_bbox['dim'][secondary_axis_idx])
                     else:
                          current_cursor_primary = target_min_primary + obj_dim_primary
                          max_dim_secondary_in_row = max(max_dim_secondary_in_row, obj_dim_secondary)
                else:
                     print(f"Warning: Could not calculate target position for {obj.name}")


        self.report({'INFO'}, f"Sorted and placed {valid_selection_count} objects (including initial active).")
        return {'FINISHED'}










