# Part 1: Imports and Class Definition
from multiprocessing import context
import bpy
import mathutils
import bmesh
import math
from mathutils import Vector, Matrix
import gpu
from gpu_extras.batch import batch_for_shader
import bpy_extras
import blf


class IOPS_OT_Mesh_Cursor_Bisect(bpy.types.Operator):
    bl_idname = "iops.mesh_cursor_bisect"
    bl_label = "Cursor Bisect"
    bl_description = "Bisect mesh. S-snap, D-hold points, Z-deselect all, Ctrl+Z-undo, A-lock orientation, P-toggle preview mode, I-toggle distance info"
    bl_options = {'REGISTER', 'UNDO'}

    merge_doubles: bpy.props.BoolProperty(name="Merge Doubles", default=True)

    _handle = None
    hit_location = None
    hit_normal = None
    hit_obj = None
    hit_face_index = -1
    edge_index = 0
    face_edges = []
    normal_axis = 'X'
    lock_orientation = False
    locked_rotation = None

    # Add timer for better modal handling
    _timer = None

    # Mouse coordinate tracking for screen-space snapping
    _current_mouse_coord = (0, 0)

    # Snapping system
    snapping_enabled = True  # Active by default
    snap_points = []
    closest_snap_point = None
    edge_subdivisions = 0  # 0 subdivisions by default (only vertices and center)
    hold_snap_points = False  # Hold snap points without recalculating
    last_face_index = -1  # Track last face to avoid unnecessary recalculations

    # Cut preview system
    cut_preview_mode = 'LINES'  # 'LINES' or 'PLANE' - default to lines
    cut_preview_lines = []  # Store cut preview line segments

    # Distance text system
    show_distance_info = False  # Toggle for showing distance info (I key)
    distance_text_offset_x = 20  # Offset from mouse cursor in pixels
    distance_text_offset_y = -30  # Offset from mouse cursor in pixels
    distance_text_size = 16  # Text size

    # Part 2: Status Bar and Distance Calculation Methods

    def update_status_bar(self, context):
        """Update workspace status text with current shortcuts and mode info"""
        snap_status = "ON" if self.snapping_enabled else "OFF"
        hold_status = " (HOLD)" if self.hold_snap_points else ""
        lock_status = " (LOCKED)" if self.lock_orientation else ""
        preview_mode = self.cut_preview_mode
        distance_status = "ON" if self.show_distance_info else "OFF"

        # Create status text with simple letter prefixes in brackets for visual clarity
        status_text = (f"Cursor Bisect: [LMB] Execute | [A] Lock{lock_status} | [S] Snap({snap_status}{hold_status}) | "
                      f"[D] Hold Points | [P] Preview({preview_mode}) | [I] Distance Info({distance_status}) | [X] Axis | [RMB] Select Face | "
                      f"[Shift+RMB] Select Coplanar | [Ctrl+Wheel] Subdivisions({self.edge_subdivisions}) | "
                      f"[Alt+Wheel] Rotate Z | [Z] Deselect | [Ctrl+Z] Undo | [Space] Finish | [Esc] Cancel")

        # Set workspace status text
        context.workspace.status_text_set(status_text)

    def get_edge_split_distances(self, context):
        """Calculate the split distances for the current edge"""
        if not (self.hit_obj and self.face_edges and 0 <= self.edge_index < len(self.face_edges)):
            return None

        try:
            # Check if object is still in edit mode
            if self.hit_obj.mode != 'EDIT':
                return None

            mesh = self.hit_obj.data
            bm = bmesh.from_edit_mesh(mesh)
            bm.edges.ensure_lookup_table()

            edge_idx = self.face_edges[self.edge_index]
            if edge_idx >= len(bm.edges):
                return None

            edge = bm.edges[edge_idx]
            v1, v2 = edge.verts

            # Transform edge vertices to world space
            v1_world = self.hit_obj.matrix_world @ v1.co
            v2_world = self.hit_obj.matrix_world @ v2.co
            total_edge_length = (v2_world - v1_world).length

            # Get cursor position in world space
            cursor_pos = context.scene.cursor.location

            # Project cursor position onto the edge line
            edge_vec = v2_world - v1_world
            cursor_vec = cursor_pos - v1_world

            if edge_vec.length > 0:
                # Calculate projection parameter (0 to 1 along edge)
                t = max(0, min(1, cursor_vec.dot(edge_vec) / edge_vec.length_squared))

                # Calculate distances
                dist1 = total_edge_length * t
                dist2 = total_edge_length * (1.0 - t)

                # Convert to display units
                unit_settings = context.scene.unit_settings
                if unit_settings.system == 'METRIC':
                    if unit_settings.length_unit == 'METERS':
                        unit_scale = 100.0  # Convert to cm
                        unit_suffix = "cm"
                    elif unit_settings.length_unit == 'CENTIMETERS':
                        unit_scale = 1.0
                        unit_suffix = "cm"
                    elif unit_settings.length_unit == 'MILLIMETERS':
                        unit_scale = 0.1  # Convert to cm
                        unit_suffix = "cm"
                    else:
                        unit_scale = 100.0  # Default to cm
                        unit_suffix = "cm"
                elif unit_settings.system == 'IMPERIAL':
                    unit_scale = 39.3701  # Convert to inches
                    unit_suffix = "in"
                else:
                    unit_scale = 100.0  # Default to cm
                    unit_suffix = "cm"

                # Apply unit scaling
                total_display = total_edge_length * unit_scale
                dist1_display = dist1 * unit_scale
                dist2_display = dist2 * unit_scale

                return {
                    'total': total_display,
                    'dist1': dist1_display,
                    'dist2': dist2_display,
                    'unit': unit_suffix
                }

        except (IndexError, AttributeError, ValueError):
            pass

        return None

    # Part 3: Coplanar Face Selection Method

    def select_coplanar_faces(self, context, event):
        """Select faces that are coplanar with the clicked face within angle threshold"""
        result, loc, normal, face_index, obj, _ = self.mouse_raycast(context, event)
        if not result or not obj or obj.type != 'MESH' or obj.mode != 'EDIT':
            return

        try:
            # Get angle threshold from preferences and convert to threshold for select_similar
            try:
                prefs = context.preferences.addons["InteractionOps"].preferences
                angle_threshold = prefs.cursor_bisect_coplanar_angle if hasattr(prefs, 'cursor_bisect_coplanar_angle') else 5.0
            except:
                angle_threshold = 5.0  # Default 5 degrees

            # Convert angle threshold to the threshold format used by select_similar
            similarity_threshold = angle_threshold / 180.0  # Convert degrees to 0-1 range
            similarity_threshold = max(0.001, min(1.0, similarity_threshold))  # Clamp to valid range

            bm = bmesh.from_edit_mesh(obj.data)
            bm.faces.ensure_lookup_table()

            if face_index >= len(bm.faces):
                return

            clicked_face = bm.faces[face_index]
            if not self.is_face_visible_and_valid(clicked_face):
                return

            # Store current selection state
            original_selection = {f.index: f.select for f in bm.faces}

            # Check if the clicked face is already selected to determine add/remove mode
            clicked_face_was_selected = clicked_face.select

            # Temporarily clear selection and select only the clicked face for similarity detection
            for face in bm.faces:
                face.select = False
            clicked_face.select = True
            bmesh.update_edit_mesh(obj.data)

            # Use Blender's built-in select similar with coplanar type
            bpy.ops.mesh.select_similar(type='FACE_COPLANAR', threshold=similarity_threshold)

            # Refresh bmesh to get the similarity results
            bm = bmesh.from_edit_mesh(obj.data)
            bm.faces.ensure_lookup_table()

            # Get the faces that were detected as coplanar
            coplanar_faces = [f.index for f in bm.faces if f.select and self.is_face_visible_and_valid(f)]

            # Restore original selection
            for face in bm.faces:
                face.select = original_selection.get(face.index, False)

            # Now apply add/remove logic based on whether clicked face was originally selected
            if clicked_face_was_selected:
                # Clicked face was selected - REMOVE coplanar faces from selection
                removed_count = 0
                for face_idx in coplanar_faces:
                    if face_idx < len(bm.faces):
                        face = bm.faces[face_idx]
                        if face.select:
                            face.select = False
                            removed_count += 1

                action_text = f"Removed {removed_count} coplanar faces from selection"

            else:
                # Clicked face was not selected - ADD coplanar faces to selection
                added_count = 0
                for face_idx in coplanar_faces:
                    if face_idx < len(bm.faces):
                        face = bm.faces[face_idx]
                        if not face.select:
                            face.select = True
                            added_count += 1

                action_text = f"Added {added_count} coplanar faces to selection"

            # Flush selection to edges and vertices
            bm.select_flush(True)
            bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=True)

            # Update cut preview after selection change
            self.calculate_cut_preview(context)

            # Show feedback message
            self.report({'INFO'}, f"{action_text} (angle ≤ {angle_threshold}°)")

        except Exception as e:
            self.report({'WARNING'}, f"Failed to select coplanar faces: {e}")
            # Restore original selection on error
            try:
                bm = bmesh.from_edit_mesh(obj.data)
                bm.faces.ensure_lookup_table()
                for face in bm.faces:
                    face.select = original_selection.get(face.index, False)
                bmesh.update_edit_mesh(obj.data)
            except:
                pass

    # Part 4: Modal Method (First Half)

    def modal(self, context, event):
        # Handle timer events
        if event.type == 'TIMER':
            return {'PASS_THROUGH'}

        # Handle Ctrl+Wheel for edge subdivision control
        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and event.ctrl and not event.shift:
            if self.snapping_enabled:
                if event.type == 'WHEELUPMOUSE':
                    self.edge_subdivisions = min(self.edge_subdivisions + 1, 100)
                else:
                    self.edge_subdivisions = max(self.edge_subdivisions - 1, 0)

                # Update snap points with new subdivision
                if self.hit_obj and self.hit_face_index != -1 and not self.hold_snap_points:
                    self.update_snapping(context, context.scene.cursor.location)

                self.update_status_bar(context)
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}  # Consume the event
            return {'PASS_THROUGH'}

        # Handle Alt+Wheel for Z-axis rotation
        elif event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and event.alt and not event.shift and not event.ctrl:
            # Get rotation step from preferences
            try:
                prefs = context.preferences.addons["InteractionOps"].preferences
                rotation_step = prefs.cursor_bisect_rotation_step if hasattr(prefs, 'cursor_bisect_rotation_step') else 45.0
            except:
                rotation_step = 45.0

            # Convert to radians
            rotation_radians = math.radians(rotation_step)

            # Determine rotation direction
            if event.type == 'WHEELUPMOUSE':
                rotation_radians = -rotation_radians  # Counter-clockwise
            # else: clockwise (positive rotation)

            # Get current cursor rotation
            cursor = context.scene.cursor
            if self.lock_orientation and self.locked_rotation:
                current_rotation = self.locked_rotation
            else:
                current_rotation = cursor.matrix.to_quaternion()

            # Get the cursor's local Z-axis
            cursor_matrix = current_rotation.to_matrix()
            local_z_axis = cursor_matrix @ Vector((0, 0, 1))

            # Create rotation around cursor's local Z-axis
            z_rotation = mathutils.Quaternion(local_z_axis, rotation_radians)

            # Apply rotation
            new_rotation = z_rotation @ current_rotation

            # Update cursor and locked rotation
            cursor.rotation_mode = 'QUATERNION'
            cursor.rotation_quaternion = new_rotation

            if self.lock_orientation:
                self.locked_rotation = new_rotation

            # Update cut preview if in lines mode
            if self.cut_preview_mode == 'LINES':
                self.calculate_cut_preview(context)

            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Allow navigation - don't intercept middle mouse or plain navigation wheel
        elif event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            return {'PASS_THROUGH'}

        # Mouse movement - update cursor position and orientation
        if event.type == 'MOUSEMOVE':
            # Store current mouse coordinates for screen-space snapping
            self._current_mouse_coord = (event.mouse_region_x, event.mouse_region_y)

            result, loc, normal, face_index, obj, _ = self.mouse_raycast(context, event)
            if result and obj and obj.type == 'MESH' and obj.mode == 'EDIT':
                self.hit_location = loc
                self.hit_normal = normal
                self.hit_obj = obj

                # Check if face changed
                face_changed = (face_index != self.last_face_index)
                self.hit_face_index = face_index
                self.last_face_index = face_index

                # Only reset edge cache if face changed AND not holding snap points AND not locked
                if face_changed and not self.hold_snap_points and not self.lock_orientation:
                    self.face_edges.clear()  # Reset edge cache
                    self.edge_index = 0  # Reset edge index

                # Update edge selection based on mouse position (if not locked)
                if not self.lock_orientation:
                    try:
                        mesh = obj.data
                        bm = bmesh.from_edit_mesh(mesh)
                        bm.faces.ensure_lookup_table()

                        if face_index < len(bm.faces):
                            face = bm.faces[face_index]
                            if face.edges:
                                # Update face edges if needed
                                if not self.face_edges or face_changed:
                                    self.face_edges = [e.index for e in face.edges]

                                # Find closest edge to mouse cursor
                                closest_edge = self.find_closest_edge_to_mouse(context, event, face)
                                if closest_edge != self.edge_index:
                                    self.edge_index = closest_edge

                    except (IndexError, AttributeError):
                        pass

                # Update snapping (now with screen-space support)
                self.update_snapping(context, loc)

                # Update cut preview
                self.calculate_cut_preview(context)

                # Set cursor position (snap to closest point if snapping enabled)
                if self.snapping_enabled and self.closest_snap_point:
                    _, _, snap_world = self.closest_snap_point
                    context.scene.cursor.location = snap_world
                else:
                    context.scene.cursor.location = loc

                # Only update orientation if face changed or if not locked/holding
                if (face_changed or not self.lock_orientation) and not self.hold_snap_points:
                    if not self.lock_orientation:
                        self.align_cursor_orientation()

                context.area.tag_redraw()

        # Toggle distance info display
        elif event.type == 'I' and event.value == 'PRESS' and not event.shift and not event.ctrl:
            self.show_distance_info = not self.show_distance_info
            self.update_status_bar(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}
    # Part 5: Modal Method (Second Half)

        # Toggle orientation lock
        elif event.type == 'A' and event.value == 'PRESS' and not event.shift and not event.ctrl:
            self.lock_orientation = not self.lock_orientation

            if self.lock_orientation and self.hit_obj:
                # When locking, ensure we have face edges calculated for the current face
                if not self.face_edges and self.hit_face_index != -1:
                    try:
                        mesh = self.hit_obj.data
                        bm = bmesh.from_edit_mesh(mesh)
                        bm.faces.ensure_lookup_table()
                        if self.hit_face_index < len(bm.faces):
                            face = bm.faces[self.hit_face_index]
                            if face.edges:
                                self.face_edges = [e.index for e in face.edges]
                                # Keep current edge index when locking
                    except (IndexError, AttributeError):
                        pass
                self.align_cursor_orientation()

            self.update_status_bar(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Toggle normal axis
        elif event.type == 'X' and event.value == 'PRESS' and not event.shift and not event.ctrl:
            self.normal_axis = 'Y' if self.normal_axis == 'X' else 'X'

            # Update cut preview immediately when changing axis (needed for LINES mode)
            if self.cut_preview_mode == 'LINES':
                self.calculate_cut_preview(context)

            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Face selection and coplanar selection
        elif event.type == 'RIGHTMOUSE' and event.value == 'PRESS' and not event.ctrl:
            if event.shift:
                # Shift+RMB: Select coplanar faces
                self.select_coplanar_faces(context, event)
            else:
                # Regular RMB: Toggle face selection
                result, loc, normal, face_index, obj, _ = self.mouse_raycast(context, event)
                if result and obj and obj.type == 'MESH' and obj.mode == 'EDIT':
                    try:
                        bm = bmesh.from_edit_mesh(obj.data)
                        bm.faces.ensure_lookup_table()
                        if face_index < len(bm.faces):
                            face = bm.faces[face_index]
                            face.select_set(not face.select)
                            bm.select_flush(True)
                            bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=True)
                            # Update cut preview after selection change
                            self.calculate_cut_preview(context)
                    except (IndexError, AttributeError):
                        pass
            return {'RUNNING_MODAL'}

        # Toggle cut preview mode
        elif event.type == 'P' and event.value == 'PRESS' and not event.shift and not event.ctrl:
            if self.cut_preview_mode == 'LINES':
                self.cut_preview_mode = 'PLANE'
                self.cut_preview_lines = []  # Clear lines when switching to plane
            else:
                self.cut_preview_mode = 'LINES'
                # Update cut preview immediately when switching to lines
                self.calculate_cut_preview(context)

            self.update_status_bar(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Execute bisect
        elif event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            self.execute(context)
            return {'RUNNING_MODAL'}

        # Toggle snapping
        elif event.type == 'S' and event.value == 'PRESS' and not event.shift and not event.ctrl:
            self.snapping_enabled = not self.snapping_enabled
            if not self.snapping_enabled:
                self.snap_points = []
                self.closest_snap_point = None
                self.hold_snap_points = False  # Reset hold when disabling snapping
            else:
                # Update snapping immediately
                if self.hit_obj and self.hit_face_index != -1:
                    self.update_snapping(context, context.scene.cursor.location)

            self.update_status_bar(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Toggle hold snap points
        elif event.type == 'D' and event.value == 'PRESS' and not event.shift and not event.ctrl:
            if self.snapping_enabled:
                self.hold_snap_points = not self.hold_snap_points
                if not self.hold_snap_points:
                    # When releasing hold, immediately update snap points for current face
                    if self.hit_obj and self.hit_face_index != -1:
                        self.update_snapping(context, context.scene.cursor.location)

                self.update_status_bar(context)
                context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Undo with Ctrl+Z
        elif event.type == 'Z' and event.value == 'PRESS' and event.ctrl and not event.shift:
            bpy.ops.ed.undo()
            # Refresh the bmesh data after undo
            if self.hit_obj and self.hit_obj.mode == 'EDIT':
                bmesh.update_edit_mesh(self.hit_obj.data)
                # Clear caches since geometry might have changed
                self.face_edges.clear()
                self.edge_index = 0
                if not self.hold_snap_points:
                    self.snap_points = []
                    self.closest_snap_point = None
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Deselect all with Z
        elif event.type == 'Z' and event.value == 'PRESS' and not event.ctrl and not event.shift:
            # Deselect all in all selected mesh objects in edit mode
            edit_objects = [obj for obj in context.selected_objects
                           if obj.type == 'MESH' and obj.mode == 'EDIT']

            for obj in edit_objects:
                try:
                    bm = bmesh.from_edit_mesh(obj.data)
                    # Deselect all vertices, edges, and faces
                    for vert in bm.verts:
                        vert.select = False
                    for edge in bm.edges:
                        edge.select = False
                    for face in bm.faces:
                        face.select = False
                    bmesh.update_edit_mesh(obj.data)
                except (IndexError, AttributeError):
                    pass

            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Finish operator
        elif event.type == 'SPACE' and event.value == 'PRESS':
            self.cancel(context)
            return {'FINISHED'}

        # Cancel operator
        elif event.type == 'ESC':
            self.cancel(context)
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}
    # Part 6: Execute Method

    def execute(self, context):
        """Execute the bisect operation on all selected mesh objects in edit mode"""
         # Push undo state before operation
        bpy.ops.ed.undo_push(message="Cursor Bisect")

        # Get all selected mesh objects in edit mode
        edit_objects = [obj for obj in context.selected_objects
                       if obj.type == 'MESH' and obj.mode == 'EDIT']

        if not edit_objects:
            self.report({'ERROR'}, "No mesh objects in Edit Mode selected.")
            return {'CANCELLED'}

        # Get cursor transform
        cursor = context.scene.cursor
        rotation = self.locked_rotation if self.lock_orientation else cursor.matrix.to_quaternion()

        # Calculate bisect axis
        axis = Vector((1, 0, 0)) if self.normal_axis == 'X' else Vector((0, 1, 0))
        axis_world = rotation @ axis

        success_count = 0

        # Execute bisect on each object
        for obj in edit_objects:
            try:
                bm = bmesh.from_edit_mesh(obj.data)
                bm.faces.ensure_lookup_table()
                bm.edges.ensure_lookup_table()
                bm.verts.ensure_lookup_table()

                # Step 1: Store selected faces using face set range (1-999) for robust multi-bisect handling
                # Remove any existing temp layer to ensure clean state
                if "temp_selection" in bm.faces.layers.int:
                    old_layer = bm.faces.layers.int["temp_selection"]
                    bm.faces.layers.int.remove(old_layer)

                # Create fresh temporary integer layer for face sets
                temp_layer = bm.faces.layers.int.new("temp_selection")

                # Get selected visible faces
                selected_faces = [f for f in bm.faces if f.select and self.is_face_visible_and_valid(f)]

                # Initialize all faces to 0 (no face set)
                for face in bm.faces:
                    face[temp_layer] = 0

                # Assign face sets 1-999 to selected faces (cycling through if more than 999 faces)
                if selected_faces:
                    for i, face in enumerate(selected_faces):
                        face_set_id = ((i % 999) + 1)  # Range 1-999, cycling
                        face[temp_layer] = face_set_id

                # Step 2: Get geometry to bisect - respect face selection and visibility
                if selected_faces:
                    # Use only selected visible faces and their components
                    geom = list({v for f in selected_faces for v in f.verts} |
                               {e for f in selected_faces for e in f.edges} |
                               set(selected_faces))
                else:
                    # Use only visible geometry
                    visible_faces = [f for f in bm.faces if self.is_face_visible_and_valid(f)]
                    if visible_faces:
                        geom = list({v for f in visible_faces for v in f.verts} |
                                   {e for f in visible_faces for e in f.edges} |
                                   set(visible_faces))
                    else:
                        # No visible faces to process
                        continue

                # Transform plane to object space
                obj_matrix = obj.matrix_world
                plane_no = obj_matrix.to_3x3().inverted_safe() @ axis_world
                plane_no.normalize()
                plane_co = obj_matrix.inverted() @ cursor.location

                # Step 3: Perform bisect
                result = bmesh.ops.bisect_plane(
                    bm,
                    geom=geom,
                    plane_co=plane_co,
                    plane_no=plane_no,
                )

                # Update indices after bisect operation
                bm.faces.ensure_lookup_table()
                bm.edges.ensure_lookup_table()
                bm.verts.ensure_lookup_table()

                # Step 4: Restore selection using face set range (1-999)
                # Clear current selection
                for face in bm.faces:
                    face.select = False
                for edge in bm.edges:
                    edge.select = False
                for vert in bm.verts:
                    vert.select = False

                # Select all faces that have face set IDs in range 1-999
                restored_count = 0
                for face in bm.faces:
                    if self.is_face_visible_and_valid(face) and 1 <= face[temp_layer] <= 999:
                        face.select = True
                        restored_count += 1

                # Step 5: Also select new faces created by bisect
                cut_faces_count = 0
                if 'geom_cut' in result:
                    for elem in result['geom_cut']:
                        if isinstance(elem, bmesh.types.BMFace) and self.is_face_visible_and_valid(elem):
                            elem.select = True
                            cut_faces_count += 1

                # Step 6: Clean up - remove temporary layer (ensure it's always removed)
                try:
                    if temp_layer and temp_layer.is_valid:
                        bm.faces.layers.int.remove(temp_layer)
                except:
                    # If layer removal fails, try to find and remove by name
                    if "temp_selection" in bm.faces.layers.int:
                        bm.faces.layers.int.remove(bm.faces.layers.int["temp_selection"])

                # Step 7: Merge doubles if requested
                if self.merge_doubles:
                    # Get merge distance from preferences
                    try:
                        prefs = context.preferences.addons["InteractionOps"].preferences
                        merge_distance = prefs.cursor_bisect_merge_distance if hasattr(prefs, 'cursor_bisect_merge_distance') else 0.005
                    except:
                        merge_distance = 0.005
                    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=merge_distance)

                # Ensure selection is properly flushed
                bm.select_flush_mode()

                bmesh.update_edit_mesh(obj.data)
                success_count += 1

            except Exception as e:
                self.report({'WARNING'}, f"Bisect failed on {obj.name}: {e}")
                continue

        if success_count > 0:
            self.report({'INFO'}, f"Bisect completed on {success_count} object(s)")
        else:
            self.report({'ERROR'}, "Bisect failed on all objects")
            return {'CANCELLED'}

        return {'FINISHED'}
    # Part 7: Cancel and Draw Methods

    def cancel(self, context):
        """Clean up and cancel the operation"""
        if self._handle:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
            self._handle = None

        if self._handle_pixel:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_pixel, 'WINDOW')
            self._handle_pixel = None

        if self._handle_iops_text:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_iops_text, 'WINDOW')
            self._handle_iops_text = None

        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None


        # Clear workspace status text
        context.workspace.status_text_set(None)
        context.area.tag_redraw()

    def draw(self, context):
        layout = self.layout

        # Main operator property
        layout.prop(self, "merge_doubles")

        # Show current merge distance from preferences (read-only info)
        if self.merge_doubles:
            try:
                prefs = context.preferences.addons["InteractionOps"].preferences
                row = layout.row()
                row.prop(prefs, "cursor_bisect_merge_distance", text="Merge Distance")
            except:
                pass

    def calculate_snap_points(self, face):
        """Calculate snap points for a face: vertices, center, and edge midpoints with subdivisions"""
        if not face:
            return []

        snap_points = []

        # Face vertices
        for vert in face.verts:
            snap_points.append(('vertex', vert.co.copy()))

        # Face center
        face_center = face.calc_center_median()
        snap_points.append(('center', face_center))

        # Edge points with subdivisions (only if subdivisions > 0)
        if self.edge_subdivisions > 0:
            for edge in face.edges:
                v1, v2 = edge.verts
                # Add subdivided points along edge
                for i in range(1, self.edge_subdivisions + 1):
                    t = i / (self.edge_subdivisions + 1)
                    point = v1.co.lerp(v2.co, t)
                    snap_points.append(('edge', point))

        return snap_points
    # Part 8: Snap Point Methods

    def find_closest_snap_point(self, context, mouse_coord, mouse_pos_world):
        """Find closest snap point using weighted screen + world distance"""
        if not self.snap_points or not context:
            return None

        try:
            region = context.region
            rv3d = context.space_data.region_3d

            # Get thresholds
            try:
                prefs = context.preferences.addons["InteractionOps"].preferences
                screen_threshold = prefs.cursor_bisect_snap_threshold if hasattr(prefs, 'cursor_bisect_snap_threshold') else 30.0
            except:
                screen_threshold = 30.0

            closest_point = None
            best_weighted_score = float('inf')

            # Calculate adaptive world threshold
            obj_scale = self.hit_obj.matrix_world.to_scale()
            max_scale = max(obj_scale.x, obj_scale.y, obj_scale.z)
            world_threshold = max(0.1, min(max_scale * 0.02, 10.0))

            for snap_type, point_local in self.snap_points:
                point_world = self.hit_obj.matrix_world @ point_local

                # Calculate world distance (always available)
                world_distance = (point_world - mouse_pos_world).length
                world_score = world_distance / world_threshold  # Normalize to 0-1+ range

                # Try screen distance
                point_screen = bpy_extras.view3d_utils.location_3d_to_region_2d(region, rv3d, point_world)

                if point_screen and 0 <= point_screen[0] <= region.width and 0 <= point_screen[1] <= region.height:
                    # Screen projection successful
                    screen_distance = (Vector(mouse_coord) - Vector(point_screen)).length
                    screen_score = screen_distance / screen_threshold  # Normalize to 0-1+ range

                    # Weighted combination: prefer screen distance but include world as backup
                    weighted_score = (screen_score * 0.7) + (world_score * 0.3)
                else:
                    # No screen projection - use world distance only
                    weighted_score = world_score

                # Only consider points within reasonable range
                if weighted_score < 1.5 and weighted_score < best_weighted_score:
                    best_weighted_score = weighted_score
                    closest_point = (snap_type, point_local, point_world)

            return closest_point if best_weighted_score < 1.0 else None

        except Exception:
            return self.find_closest_snap_point_fallback(mouse_pos_world)

    def find_closest_snap_point_fallback(self, mouse_pos_world):
        """Fallback method using world-space distance with adaptive threshold"""
        if not self.snap_points:
            return None

        closest_point = None
        closest_distance = float('inf')

        for snap_type, point_local in self.snap_points:
            point_world = self.hit_obj.matrix_world @ point_local
            distance = (point_world - mouse_pos_world).length

            if distance < closest_distance:
                closest_distance = distance
                closest_point = (snap_type, point_local, point_world)

        # Use adaptive threshold based on object scale
        if self.hit_obj and closest_point:
            obj_scale = self.hit_obj.matrix_world.to_scale()
            max_scale = max(obj_scale.x, obj_scale.y, obj_scale.z)
            adaptive_threshold = 0.5 * max_scale
            adaptive_threshold = max(0.1, min(adaptive_threshold, 50.0))

            if closest_distance < adaptive_threshold:
                return closest_point

        return None

    def find_closest_edge_to_mouse(self, context, event, face):
        """Find the closest edge in the face to the mouse cursor"""
        if not face or not face.edges:
            return 0

        region = context.region
        rv3d = context.space_data.region_3d
        mouse_coord = (event.mouse_region_x, event.mouse_region_y)

        closest_edge_index = 0
        closest_distance = float('inf')

        for i, edge in enumerate(face.edges):
            v1, v2 = edge.verts

            # Transform vertices to world space
            v1_world = self.hit_obj.matrix_world @ v1.co
            v2_world = self.hit_obj.matrix_world @ v2.co

            # Project to screen space
            v1_screen = bpy_extras.view3d_utils.location_3d_to_region_2d(region, rv3d, v1_world)
            v2_screen = bpy_extras.view3d_utils.location_3d_to_region_2d(region, rv3d, v2_world)

            if v1_screen and v2_screen:
                # Calculate distance from mouse to edge in screen space
                edge_vec = Vector((v2_screen[0] - v1_screen[0], v2_screen[1] - v1_screen[1]))
                mouse_vec = Vector((mouse_coord[0] - v1_screen[0], mouse_coord[1] - v1_screen[1]))

                if edge_vec.length > 0:
                    # Project mouse vector onto edge vector
                    t = max(0, min(1, mouse_vec.dot(edge_vec) / edge_vec.length_squared))
                    projection = Vector(v1_screen) + t * edge_vec
                    distance = (Vector(mouse_coord) - projection).length

                    if distance < closest_distance:
                        closest_distance = distance
                        closest_edge_index = i

        return closest_edge_index

    def update_snapping(self, context, mouse_pos_world):
        """Update snap points and find closest snap point"""
        if not self.snapping_enabled:
            self.snap_points = []
            self.closest_snap_point = None
            return

        # Get mouse coordinates for screen-space calculation
        mouse_coord = getattr(self, '_current_mouse_coord', (0, 0))

        # If holding snap points, only update closest point calculation, not the snap points themselves
        if self.hold_snap_points and self.snap_points:
            self.closest_snap_point = self.find_closest_snap_point(context, mouse_coord, mouse_pos_world)
            return

        # Regular snap point calculation
        if not self.hit_obj or self.hit_face_index == -1:
            self.snap_points = []
            self.closest_snap_point = None
            return

        try:
            # Check if object is still in edit mode
            if self.hit_obj.mode != 'EDIT':
                self.snap_points = []
                self.closest_snap_point = None
                return

            mesh = self.hit_obj.data
            bm = bmesh.from_edit_mesh(mesh)
            bm.faces.ensure_lookup_table()

            if self.hit_face_index >= len(bm.faces):
                return

            face = bm.faces[self.hit_face_index]
            self.snap_points = self.calculate_snap_points(face)
            self.closest_snap_point = self.find_closest_snap_point(context, mouse_coord, mouse_pos_world)

        except (IndexError, AttributeError, ValueError):
            self.snap_points = []
            self.closest_snap_point = None
    # Part 9: Face Processing Methods

    def get_connected_faces_by_depth(self, bm, start_face_index, max_depth=5):
        """Get faces connected to start face within specified depth"""
        if start_face_index >= len(bm.faces) or start_face_index < 0:
            return set()

        visited = set()
        current_depth_faces = {start_face_index}
        visited.add(start_face_index)

        for depth in range(max_depth):
            if not current_depth_faces:
                break

            next_depth_faces = set()

            for face_idx in current_depth_faces:
                if face_idx >= len(bm.faces):
                    continue

                face = bm.faces[face_idx]

                # Get connected faces through shared edges
                for edge in face.edges:
                    for linked_face in edge.link_faces:
                        if linked_face.index not in visited:
                            visited.add(linked_face.index)
                            next_depth_faces.add(linked_face.index)

            current_depth_faces = next_depth_faces

        return visited

    def is_face_visible_and_valid(self, face):
        """Check if face is visible (not hidden) and valid for processing"""
        if not face or not face.is_valid:
            return False

        # Check if face is hidden
        if face.hide:
            return False

        return True

    def get_faces_to_process(self, bm, obj, face_depth):
        """Get faces to process based on selection and visibility"""
        faces_to_process = set()

        # Get selected faces that are visible
        selected_faces = [f for f in bm.faces if f.select and self.is_face_visible_and_valid(f)]

        if selected_faces:
            # ONLY use selected faces - no connectivity expansion for preview
            for face in selected_faces:
                faces_to_process.add(face.index)
        else:
            # If we have a hit face from raycast, use connectivity-based selection
            if self.hit_obj == obj and self.hit_face_index != -1:
                if self.hit_face_index < len(bm.faces):
                    hit_face = bm.faces[self.hit_face_index]
                    if self.is_face_visible_and_valid(hit_face):
                        connected_faces = self.get_connected_faces_by_depth(bm, self.hit_face_index, face_depth)
                        # Filter connected faces to only include visible ones
                        for face_idx in connected_faces:
                            if face_idx < len(bm.faces):
                                connected_face = bm.faces[face_idx]
                                if self.is_face_visible_and_valid(connected_face):
                                    faces_to_process.add(face_idx)

            # If still no faces to process, use all visible faces
            if not faces_to_process:
                # Get preferences for max faces limit
                try:
                    prefs = bpy.context.preferences.addons["InteractionOps"].preferences
                    max_faces = prefs.cursor_bisect_max_faces if hasattr(prefs, 'cursor_bisect_max_faces') else 1000
                except:
                    max_faces = 1000

                visible_faces = [f.index for f in bm.faces if self.is_face_visible_and_valid(f)]
                faces_to_process = set(visible_faces[:max_faces])

        return faces_to_process
    # Part 10: Cut Preview Calculation

    def calculate_cut_preview(self, context):
        """Calculate cut preview lines for selected mesh objects using face connectivity with improved visibility"""
        self.cut_preview_lines = []

        if self.cut_preview_mode == 'PLANE':
            return  # No line calculation needed for plane mode

        # Get all selected mesh objects in edit mode
        edit_objects = [obj for obj in context.selected_objects
                       if obj.type == 'MESH' and obj.mode == 'EDIT']

        if not edit_objects:
            return

        # Get cursor transform
        cursor = context.scene.cursor
        rotation = self.locked_rotation if self.lock_orientation else cursor.matrix.to_quaternion()

        # Calculate bisect axis
        axis = Vector((1, 0, 0)) if self.normal_axis == 'X' else Vector((0, 1, 0))
        axis_world = rotation @ axis

        # Get preferences for depth setting and line elevation
        try:
            prefs = context.preferences.addons["InteractionOps"].preferences
            face_depth = prefs.cursor_bisect_face_depth if hasattr(prefs, 'cursor_bisect_face_depth') else 5
            line_elevation = prefs.cursor_bisect_line_elevation if hasattr(prefs, 'cursor_bisect_line_elevation') else 0.001
        except:
            face_depth = 5
            line_elevation = 0.001

        # Calculate cut preview for each object
        for obj in edit_objects:
            try:
                # Check if object is still in edit mode
                if obj.mode != 'EDIT':
                    continue

                bm = bmesh.from_edit_mesh(obj.data)
                bm.faces.ensure_lookup_table()
                bm.edges.ensure_lookup_table()
                bm.verts.ensure_lookup_table()

                # Transform plane to object space
                obj_matrix = obj.matrix_world
                plane_no = obj_matrix.to_3x3().inverted_safe() @ axis_world
                plane_no.normalize()
                plane_co = obj_matrix.inverted() @ cursor.location

                # Get faces to process with improved selection and visibility checking
                faces_to_process = self.get_faces_to_process(bm, obj, face_depth)

                if not faces_to_process:
                    continue

                # Collect intersection points per face to create connected lines
                face_intersections = {}

                # Process only edges that belong to our target faces
                processed_edges = set()
                for face_idx in faces_to_process:
                    if face_idx >= len(bm.faces):
                        continue
                    face = bm.faces[face_idx]
                    if not self.is_face_visible_and_valid(face):
                        continue

                    # Process each edge of this face
                    for edge in face.edges:
                        if edge.index in processed_edges:
                            continue
                        processed_edges.add(edge.index)

                        # Only process if edge belongs to our target faces
                        edge_faces = [f.index for f in edge.link_faces if f.index in faces_to_process and self.is_face_visible_and_valid(f)]
                        if not edge_faces:
                            continue

                        v1, v2 = edge.verts

                        # Calculate distances from plane
                        d1 = (v1.co - plane_co).dot(plane_no)
                        d2 = (v2.co - plane_co).dot(plane_no)

                        # Check if edge crosses the plane (different signs or one is zero)
                        if (d1 * d2 < 0) or (abs(d1) < 1e-6) or (abs(d2) < 1e-6):
                            # Calculate intersection point
                            if abs(d1 - d2) > 1e-6:  # Avoid division by zero
                                t = d1 / (d1 - d2)
                                intersection = v1.co.lerp(v2.co, t)

                                # Calculate face normal for elevation (use the first valid face)
                                face_normal = None
                                for face_idx in edge_faces:
                                    if face_idx < len(bm.faces):
                                        face = bm.faces[face_idx]
                                        if self.is_face_visible_and_valid(face):
                                            face_normal = face.normal.normalized()
                                            break

                                # If we couldn't get a face normal, use the plane normal
                                if face_normal is None:
                                    face_normal = plane_no

                                # Elevate intersection point slightly above surface for better visibility
                                elevated_intersection = intersection + face_normal * line_elevation

                                # Transform to world space
                                world_intersection = obj_matrix @ elevated_intersection

                                # Group intersections by faces that share this edge
                                for face_idx in edge_faces:
                                    if face_idx not in face_intersections:
                                        face_intersections[face_idx] = []
                                    face_intersections[face_idx].append(world_intersection)

                # Create connected lines within each face
                for face_idx, intersections in face_intersections.items():
                    if len(intersections) >= 2:
                        # Sort intersections to create proper connections
                        intersections.sort(key=lambda p: (p.x, p.y, p.z))

                        # Connect consecutive intersection points
                        for i in range(len(intersections) - 1):
                            self.cut_preview_lines.append((intersections[i], intersections[i + 1]))

                        # If more than 2 points, this might be a complex intersection
                        # Connect the last point to the first to close if it's a polygon cut
                        if len(intersections) > 2:
                            # Only close if the points form a reasonable polygon
                            dist_to_close = (intersections[-1] - intersections[0]).length
                            avg_edge_length = sum((intersections[i] - intersections[i-1]).length
                                                for i in range(1, len(intersections))) / (len(intersections) - 1)

                            # Close the loop if the closing distance is reasonable
                            if dist_to_close <= avg_edge_length * 2:
                                self.cut_preview_lines.append((intersections[-1], intersections[0]))

            except (IndexError, AttributeError, ValueError):
                continue

    # Draw Help text
    def draw_iops_text(self, context):
        preferences = context.preferences
        uifactor = preferences.system.ui_scale
        prefs = bpy.context.preferences.addons["InteractionOps"].preferences
        
        # Text appearance settings
        tColor = prefs.text_color
        tKColor = prefs.text_color_key
        tCSize = prefs.text_size
        tCPosX = prefs.text_pos_x
        tCPosY = prefs.text_pos_y
        
        # Shadow settings
        tShadow = prefs.text_shadow_toggle
        tSColor = prefs.text_shadow_color
        tSBlur = prefs.text_shadow_blur
        tSPosX = prefs.text_shadow_pos_x
        tSPosY = prefs.text_shadow_pos_y
        
        # Instructions text (action, key)
        iops_text = (
            ("Snapping", "S"),
            ("Snap Points Subdivide", "Ctrl+Mouse Wheel"),
            ("Hold Points", "D"),
            ("Select Face", "Right Mouse Button"),
            ("Select Coplanar Faces", "Shift+Right Mouse Button"),
            ("Rotate Z-axis", "Alt+Mouse Wheel"),
            ("Lock Edge (Orientation)", "A"),
            ("Preview Line/Plane", "P"),
            ("Toggle Distance Info", "I"),
            ("Execute bisect", "Left Mouse Button"),
            ("Finish operation", "Space"),
            ("Cancel operation", "Esc"),
        )
        
        # Font setup
        font_id = 0
        blf.color(font_id, tColor[0], tColor[1], tColor[2], tColor[3])
        blf.size(font_id, tCSize)
        
        # Configure shadow
        if tShadow:
            blf.enable(font_id, blf.SHADOW)
            blf.shadow(font_id, int(tSBlur), tSColor[0], tSColor[1], tSColor[2], tSColor[3])
            blf.shadow_offset(font_id, tSPosX, tSPosY)
        else:
            blf.disable(font_id, blf.SHADOW)
        
        # Calculate layout - find the widest action text to avoid overlap
        max_action_width = 0
        for line in iops_text:
            action_width = blf.dimensions(font_id, line[0])[0]
            max_action_width = max(max_action_width, action_width)
        
        # Calculate the right edge position for key alignment
        action_start_x = tCPosX * uifactor
        padding = (tCSize * 2) * uifactor
        keys_right_edge = action_start_x + max_action_width + padding + (tCSize * 15) * uifactor
        
        offset = tCPosY
        
        # Draw text lines (reversed order for bottom-up display)
        for line in reversed(iops_text):
            # Draw action description
            blf.color(font_id, tColor[0], tColor[1], tColor[2], tColor[3])
            blf.position(font_id, action_start_x, offset, 0)
            blf.draw(font_id, line[0])
            
            # Draw key binding (right-aligned to the keys_right_edge)
            blf.color(font_id, tKColor[0], tKColor[1], tKColor[2], tKColor[3])
            key_width = blf.dimensions(font_id, line[1])[0]
            key_x_pos = keys_right_edge - key_width
            blf.position(font_id, key_x_pos, offset, 0)
            blf.draw(font_id, line[1])
            
            # Move to next line
            offset += (tCSize + 5) * uifactor

    # Part 11: Distance Text Drawing

    def draw_mouse_distance_text(self, context):
        """Draw distance information as text near the mouse cursor"""
        try:
            import blf
            prefs = context.preferences.addons["InteractionOps"].preferences

            # Get distance information
            distance_info = self.get_edge_split_distances(context)
            if not distance_info:
                return

            # Format the distance text
            total = distance_info['total']
            dist1 = distance_info['dist1']
            dist2 = distance_info['dist2']
            unit = distance_info['unit']
            distance_text = f"Edge: {total:.2f}{unit} | Split: {dist1:.2f}{unit} | {dist2:.2f}{unit}"

            # Get current mouse position and offsets
            mouse_x, mouse_y = self._current_mouse_coord
            text_x = mouse_x + self.distance_text_offset_x
            text_y = mouse_y + self.distance_text_offset_y

            # Ensure text stays within screen bounds
            region = context.region
            font_id = 0
            blf.size(font_id, self.distance_text_size)
            text_width, text_height = blf.dimensions(font_id, distance_text)

            text_x = min(max(text_x, 10), region.width - text_width - 10)
            text_y = min(max(text_y, 10), region.height - text_height - 10)

            # Enable shadow for readability
            blf.enable(font_id, blf.SHADOW)
            blf.shadow(font_id, 5, 0, 0, 0, 1)
            blf.shadow_offset(font_id, 1, -1)

            # Set text color
            text_color = prefs.cursor_bisect_distance_text_color  # Yellow
            blf.color(font_id, *text_color)
            # Draw the text
            blf.position(font_id, text_x, text_y, 0)
            blf.draw(font_id, distance_text)

        except Exception as e:
            print(f"Error in draw_mouse_distance_text: {e}")


    def draw_callback(self, context):
        """Draw the bisect plane preview, snap points, and distance text - with debug info"""
        # Safety check: ensure the operator is still valid
        try:
            test_access = self.lock_orientation
        except ReferenceError:
            return

        if not context or not context.scene:
            return

        try:
            # Get preferences for all colors and sizes
            try:
                prefs = context.preferences.addons["InteractionOps"].preferences
            except:
                prefs = None

            origin = context.scene.cursor.location
            rotation = self.locked_rotation if self.lock_orientation else context.scene.cursor.matrix.to_quaternion()
            mat = rotation.to_matrix()

            # Calculate plane vectors based on normal axis
            if self.normal_axis == 'X':
                u = mat @ Vector((0, 1, 0))
                v = mat @ Vector((0, 0, 1))
            else:
                u = mat @ Vector((1, 0, 0))
                v = mat @ Vector((0, 0, 1))

            size = 2.0
            corners = [
                origin + (u + v) * size,
                origin + (u - v) * size,
                origin + (-u - v) * size,
                origin + (-u + v) * size,
            ]

            shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            shader.bind()

            # Draw the plane fill - FROM PREFERENCES (when in PLANE mode)
            if self.cut_preview_mode == 'PLANE':
                batch = batch_for_shader(shader, 'TRI_FAN', {"pos": corners})
                if prefs and hasattr(prefs, 'cursor_bisect_plane_color'):
                    plane_color = prefs.cursor_bisect_plane_color
                else:
                    plane_color = (0.5, 0.5, 1.0, 0.3)
                shader.uniform_float("color", (plane_color[0], plane_color[1], plane_color[2], plane_color[3]))
                gpu.state.blend_set('ALPHA')
                gpu.state.depth_test_set('LESS')
                batch.draw(shader)

            # Draw plane outline - FROM PREFERENCES (when in PLANE mode)
            if self.cut_preview_mode == 'PLANE':
                outline_coords = corners + [corners[0]]
                batch_outline = batch_for_shader(shader, 'LINE_STRIP', {"pos": outline_coords})
                if prefs and hasattr(prefs, 'cursor_bisect_plane_outline_color'):
                    outline_color = prefs.cursor_bisect_plane_outline_color
                    outline_thickness = getattr(prefs, 'cursor_bisect_plane_outline_thickness', 2.0)
                else:
                    outline_color = (0.5, 0.5, 1.0, 1.0)
                    outline_thickness = 2.0
                shader.uniform_float("color", (outline_color[0], outline_color[1], outline_color[2], outline_color[3]))
                gpu.state.line_width_set(outline_thickness)
                batch_outline.draw(shader)

            # Draw snap points if snapping is enabled - FROM PREFERENCES
            if self.snapping_enabled and self.snap_points and self.hit_obj:
                try:
                    snap_coords = []
                    for snap_type, point_local in self.snap_points:
                        point_world = self.hit_obj.matrix_world @ point_local
                        snap_coords.append(point_world)

                    if snap_coords:
                        # Choose snap points color based on hold state
                        if self.hold_snap_points:
                            if prefs and hasattr(prefs, 'cursor_bisect_snap_hold_color'):
                                snap_color = prefs.cursor_bisect_snap_hold_color
                            else:
                                snap_color = (1.0, 0.5, 0.0, 1.0)
                        else:
                            if prefs and hasattr(prefs, 'cursor_bisect_snap_color'):
                                snap_color = prefs.cursor_bisect_snap_color
                            else:
                                snap_color = (1.0, 1.0, 0.0, 1.0)

                        batch_points = batch_for_shader(shader, 'POINTS', {"pos": snap_coords})
                        shader.uniform_float("color", (snap_color[0], snap_color[1], snap_color[2], snap_color[3]))
                        snap_size = getattr(prefs, 'cursor_bisect_snap_size', 8.0) if prefs else 8.0
                        gpu.state.point_size_set(snap_size)
                        gpu.state.depth_test_set('ALWAYS')
                        batch_points.draw(shader)

                        # Draw closest snap point
                        if self.closest_snap_point:
                            _, _, closest_world = self.closest_snap_point
                            batch_closest = batch_for_shader(shader, 'POINTS', {"pos": [closest_world]})
                            if self.hold_snap_points:
                                if prefs and hasattr(prefs, 'cursor_bisect_snap_closest_hold_color'):
                                    closest_color = prefs.cursor_bisect_snap_closest_hold_color
                                else:
                                    closest_color = (1.0, 0.0, 0.0, 1.0)
                            else:
                                if prefs and hasattr(prefs, 'cursor_bisect_snap_closest_color'):
                                    closest_color = prefs.cursor_bisect_snap_closest_color
                                else:
                                    closest_color = (0.0, 1.0, 0.0, 1.0)
                            shader.uniform_float("color", (closest_color[0], closest_color[1], closest_color[2], closest_color[3]))
                            closest_size = getattr(prefs, 'cursor_bisect_snap_closest_size', 12.0) if prefs else 12.0
                            gpu.state.point_size_set(closest_size)
                            batch_closest.draw(shader)

                except (IndexError, AttributeError, ReferenceError):
                    pass

            # Reset GPU state
            gpu.state.point_size_set(1.0)
            gpu.state.line_width_set(1.0)
            gpu.state.depth_test_set('LESS')
            gpu.state.blend_set('NONE')

            # Draw cut preview lines (when in LINES mode)
            if self.cut_preview_mode == 'LINES' and self.cut_preview_lines:
                try:
                    preview_coords = []
                    for line_start, line_end in self.cut_preview_lines:
                        preview_coords.extend([line_start, line_end])

                    if preview_coords:
                        preview_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
                        preview_shader.bind()

                        if prefs and hasattr(prefs, 'cursor_bisect_cut_preview_color'):
                            preview_color = prefs.cursor_bisect_cut_preview_color
                        else:
                            preview_color = (1.0, 0.5, 0.0, 1.0)

                        preview_thickness = getattr(prefs, 'cursor_bisect_cut_preview_thickness', 3.0) if prefs else 3.0

                        preview_shader.uniform_float("color", preview_color)
                        gpu.state.line_width_set(preview_thickness)
                        gpu.state.depth_test_set('LESS_EQUAL')

                        preview_batch = batch_for_shader(preview_shader, 'LINES', {"pos": preview_coords})
                        preview_batch.draw(preview_shader)

                        gpu.state.line_width_set(1.0)
                        gpu.state.depth_test_set('LESS')

                except (IndexError, AttributeError, ReferenceError):
                    pass

            # Draw highlighted edge
            if self.hit_obj and self.face_edges and 0 <= self.edge_index < len(self.face_edges):
                try:
                    if self.hit_obj.mode != 'EDIT':
                        return

                    mesh = self.hit_obj.data
                    bm = bmesh.from_edit_mesh(mesh)
                    bm.edges.ensure_lookup_table()

                    edge_idx = self.face_edges[self.edge_index]
                    if edge_idx < len(bm.edges):
                        edge = bm.edges[edge_idx]
                        v1, v2 = edge.verts

                        world_coords = [
                            self.hit_obj.matrix_world @ v1.co.copy(),
                            self.hit_obj.matrix_world @ v2.co.copy()
                        ]

                        gpu.state.blend_set('NONE')
                        gpu.state.depth_test_set('ALWAYS')
                        gpu.state.line_width_set(1.0)

                        fresh_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
                        fresh_shader.bind()

                        if self.lock_orientation:
                            if prefs and hasattr(prefs, 'cursor_bisect_edge_locked_color'):
                                edge_color = prefs.cursor_bisect_edge_locked_color
                                edge_thickness = getattr(prefs, 'cursor_bisect_edge_locked_thickness', 4.0)
                            else:
                                edge_color = (1.0, 0.0, 1.0, 1.0)
                                edge_thickness = 4.0
                        else:
                            if prefs and hasattr(prefs, 'cursor_bisect_edge_color'):
                                edge_color = prefs.cursor_bisect_edge_color
                                edge_thickness = getattr(prefs, 'cursor_bisect_edge_thickness', 3.0)
                            else:
                                edge_color = (0.0, 1.0, 1.0, 1.0)
                                edge_thickness = 3.0

                        fresh_shader.uniform_float("color", (edge_color[0], edge_color[1], edge_color[2], edge_color[3]))
                        gpu.state.line_width_set(edge_thickness)
                        gpu.state.depth_test_set('ALWAYS')

                        fresh_batch = batch_for_shader(fresh_shader, 'LINES', {"pos": world_coords})
                        fresh_batch.draw(fresh_shader)

                        gpu.state.line_width_set(1.0)

                except (IndexError, AttributeError, ValueError, ReferenceError):
                    pass

        except (ReferenceError, AttributeError) as e:
            print(f"DEBUG: Exception in draw_callback: {e}")
            return

    # Part 14: Final Methods and Registration
    def draw_distance_text_callback(self, context):
        if self.show_distance_info:
            self.draw_mouse_distance_text(context)

    def mouse_raycast(self, context, event):
        """Perform raycast from mouse position"""
        region = context.region
        rv3d = context.space_data.region_3d
        coord = (event.mouse_region_x, event.mouse_region_y)
        view_vector = bpy_extras.view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        ray_origin = bpy_extras.view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        depsgraph = context.evaluated_depsgraph_get()
        return context.scene.ray_cast(depsgraph, ray_origin, view_vector)

    def align_cursor_orientation(self):
        """Align cursor to selected edge and face normal"""
        if not self.hit_obj or self.hit_face_index == -1:
            return

        try:
            # Check if object is still in edit mode
            if self.hit_obj.mode != 'EDIT':
                return

            mesh = self.hit_obj.data
            bm = bmesh.from_edit_mesh(mesh)
            bm.faces.ensure_lookup_table()
            bm.edges.ensure_lookup_table()

            if self.hit_face_index >= len(bm.faces):
                return

            face = bm.faces[self.hit_face_index]
            if not face.edges:
                return

            # Cache face edges if not already done
            if not self.face_edges:
                self.face_edges = [e.index for e in face.edges]

            # Ensure edge index is valid
            self.edge_index = self.edge_index % len(self.face_edges)
            edge_index = self.face_edges[self.edge_index]

            if edge_index >= len(bm.edges):
                return

            edge = bm.edges[edge_index]
            v1, v2 = edge.verts

            # Get vectors in object space first
            edge_vec_local = (v2.co - v1.co).normalized()
            normal_local = face.normal.normalized()

            # Transform to world space using object matrix
            obj_matrix = self.hit_obj.matrix_world
            edge_vec_world = (obj_matrix.to_3x3() @ edge_vec_local).normalized()
            normal_world = (obj_matrix.to_3x3() @ normal_local).normalized()

            # Build coordinate system
            x_axis = edge_vec_world
            z_axis = normal_world
            y_axis = z_axis.cross(x_axis).normalized()
            x_axis = y_axis.cross(z_axis).normalized()  # Recompute for orthogonality

            # Create rotation matrix and convert to quaternion
            rot_matrix = Matrix((x_axis, y_axis, z_axis)).transposed()
            self.locked_rotation = rot_matrix.to_quaternion()

            # Apply to cursor
            cursor = bpy.context.scene.cursor
            cursor.rotation_mode = 'QUATERNION'
            cursor.rotation_quaternion = self.locked_rotation

        except (IndexError, AttributeError, ValueError) as e:
            pass

    def invoke(self, context, event):
        if context.area.type != 'VIEW_3D':
            self.report({'WARNING'}, "View3D not found")
            return {'CANCELLED'}

        # Initialize all state variables
        self.hit_location = None
        self.hit_normal = None
        self.hit_obj = None
        self.hit_face_index = -1
        self.edge_index = 0
        self.face_edges = []
        self.normal_axis = 'X'
        self.lock_orientation = False
        self.locked_rotation = None
        self.snapping_enabled = True  # Active by default
        self.snap_points = []
        self.closest_snap_point = None
        # Get initial subdivisions from preferences
        try:
            prefs = context.preferences.addons["InteractionOps"].preferences
            self.edge_subdivisions = prefs.cursor_bisect_edge_subdivisions if hasattr(prefs, 'cursor_bisect_edge_subdivisions') else 1
        except:
            self.edge_subdivisions = 1  # Fallback default
        self.hold_snap_points = False  # Active by default
        self.last_face_index = -1
        self.cut_preview_mode = 'LINES'  # Default to line preview
        self.cut_preview_lines = []

        # Initialize distance text system (OFF by default, toggle with I key)
        self.show_distance_info = False
        # Get text settings from preferences
        try:
            prefs = context.preferences.addons["InteractionOps"].preferences
            self.distance_text_size = getattr(prefs, 'cursor_bisect_distance_text_size', 16)
            self.distance_text_offset_x = getattr(prefs, 'cursor_bisect_distance_offset_x', 20)
            self.distance_text_offset_y = getattr(prefs, 'cursor_bisect_distance_offset_y', -30)
        except:
            self.distance_text_size = 16
            self.distance_text_offset_x = 20
            self.distance_text_offset_y = -30

        # Initialize mouse coordinate tracking for screen-space snapping
        self._current_mouse_coord = (0, 0)

        # Add draw handler
        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_callback, (context,), 'WINDOW', 'POST_VIEW'
        )
        self._handle_pixel = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_distance_text_callback, (context,), 'WINDOW', 'POST_PIXEL'
        )
        self._handle_iops_text = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_iops_text,(context,), "WINDOW", "POST_PIXEL"
            )
        # Add timer for smoother updates
        self._timer = context.window_manager.event_timer_add(0.1, window=context.window)

        # Set workspace status text
        self.update_status_bar(context)

        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}


