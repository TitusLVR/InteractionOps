import bpy
import mathutils
import bmesh
from mathutils import Vector, Matrix
import gpu
from gpu_extras.batch import batch_for_shader
import bpy_extras


class IOPS_OT_Mesh_Cursor_Bisect(bpy.types.Operator):
    bl_idname = "iops.mesh_cursor_bisect"
    bl_label = "Cursor Bisect"
    bl_description = "Bisect mesh. S-snap, D-hold points, Z-deselect all, Ctrl+Z-undo"
    bl_options = {'REGISTER', 'UNDO'}

    merge_doubles: bpy.props.BoolProperty(name="Merge Doubles", default=True)
    merge_distance: bpy.props.FloatProperty(name="Merge Distance", default=0.005, min=0.0, max=10.0)

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
    
    # Snapping system
    snapping_enabled = True  # Active by default
    snap_points = []
    closest_snap_point = None
    edge_subdivisions = 0  # 0 subdivisions by default (only vertices and center)
    hold_snap_points = False  # Hold snap points without recalculating
    last_face_index = -1  # Track last face to avoid unnecessary recalculations

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
    
    def find_closest_snap_point(self, mouse_pos_world):
        """Find the closest snap point to the mouse position"""
        if not self.snap_points:
            return None
            
        closest_point = None
        closest_distance = float('inf')
        
        for snap_type, point_local in self.snap_points:
            # Transform to world space
            point_world = self.hit_obj.matrix_world @ point_local
            distance = (point_world - mouse_pos_world).length
            
            if distance < closest_distance:
                closest_distance = distance
                closest_point = (snap_type, point_local, point_world)
        
        # Only snap if within reasonable distance (viewport dependent)
        if closest_distance < 0.5:  # Adjust this threshold as needed
            return closest_point
        
        return None
    
    def update_snapping(self, context, mouse_pos_world):
        """Update snap points and find closest snap point"""
        if not self.snapping_enabled:
            self.snap_points = []
            self.closest_snap_point = None
            return
            
        # If holding snap points, only update closest point calculation, not the snap points themselves
        if self.hold_snap_points and self.snap_points:
            self.closest_snap_point = self.find_closest_snap_point(mouse_pos_world)
            return
            
        # Regular snap point calculation
        if not self.hit_obj or self.hit_face_index == -1:
            self.snap_points = []
            self.closest_snap_point = None
            return
            
        try:
            mesh = self.hit_obj.data
            bm = bmesh.from_edit_mesh(mesh)
            bm.faces.ensure_lookup_table()
            
            if self.hit_face_index >= len(bm.faces):
                return
                
            face = bm.faces[self.hit_face_index]
            self.snap_points = self.calculate_snap_points(face)
            self.closest_snap_point = self.find_closest_snap_point(mouse_pos_world)
            
        except (IndexError, AttributeError):
            self.snap_points = []
            self.closest_snap_point = None

    def draw_callback(self, context):
        """Draw the bisect plane preview and snap points - ALL colors from preferences"""
        # Get preferences for all colors and sizes
        prefs = context.preferences.addons["InteractionOps"].preferences
        
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
        
        # Draw the plane fill - FROM PREFERENCES
        batch = batch_for_shader(shader, 'TRI_FAN', {"pos": corners})
        plane_color = prefs.cursor_bisect_plane_color
        shader.uniform_float("color", (plane_color[0], plane_color[1], plane_color[2], plane_color[3]))
        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('LESS')
        batch.draw(shader)

        # Draw plane outline - FROM PREFERENCES
        outline_coords = corners + [corners[0]]
        batch_outline = batch_for_shader(shader, 'LINE_STRIP', {"pos": outline_coords})
        outline_color = prefs.cursor_bisect_plane_outline_color
        shader.uniform_float("color", (outline_color[0], outline_color[1], outline_color[2], outline_color[3]))
        gpu.state.line_width_set(prefs.cursor_bisect_plane_outline_thickness)
        batch_outline.draw(shader)

        # Draw snap points if snapping is enabled - FROM PREFERENCES
        if self.snapping_enabled and self.snap_points and self.hit_obj:
            try:
                snap_coords = []
                for snap_type, point_local in self.snap_points:
                    point_world = self.hit_obj.matrix_world @ point_local
                    snap_coords.append(point_world)
                
                if snap_coords:
                    # Choose snap points color based on hold state - FROM PREFERENCES
                    if self.hold_snap_points:
                        snap_color = prefs.cursor_bisect_snap_hold_color
                    else:
                        snap_color = prefs.cursor_bisect_snap_color
                    
                    # Draw snap points - FROM PREFERENCES
                    batch_points = batch_for_shader(shader, 'POINTS', {"pos": snap_coords})
                    shader.uniform_float("color", (snap_color[0], snap_color[1], snap_color[2], snap_color[3]))
                    gpu.state.point_size_set(prefs.cursor_bisect_snap_size)
                    gpu.state.depth_test_set('ALWAYS')
                    batch_points.draw(shader)
                    
                    # Draw closest snap point - FROM PREFERENCES
                    if self.closest_snap_point:
                        _, _, closest_world = self.closest_snap_point
                        batch_closest = batch_for_shader(shader, 'POINTS', {"pos": [closest_world]})
                        if self.hold_snap_points:
                            closest_color = prefs.cursor_bisect_snap_closest_hold_color
                        else:
                            closest_color = prefs.cursor_bisect_snap_closest_color
                        shader.uniform_float("color", (closest_color[0], closest_color[1], closest_color[2], closest_color[3]))
                        gpu.state.point_size_set(prefs.cursor_bisect_snap_closest_size)
                        batch_closest.draw(shader)
                        
            except (IndexError, AttributeError):
                pass

        # Reset GPU state
        gpu.state.point_size_set(1.0)
        gpu.state.line_width_set(1.0)
        gpu.state.depth_test_set('LESS')
        gpu.state.blend_set('NONE')
        
        # Draw highlighted edge - FROM PREFERENCES
        if self.hit_obj and self.face_edges and 0 <= self.edge_index < len(self.face_edges):
            try:
                mesh = self.hit_obj.data
                bm = bmesh.from_edit_mesh(mesh)
                bm.edges.ensure_lookup_table()
                
                edge_idx = self.face_edges[self.edge_index]
                if edge_idx < len(bm.edges):
                    edge = bm.edges[edge_idx]
                    v1, v2 = edge.verts
                    
                    # Transform to world space
                    world_coords = [
                        self.hit_obj.matrix_world @ v1.co.copy(), 
                        self.hit_obj.matrix_world @ v2.co.copy()
                    ]
                    
                    # Reset GPU state
                    gpu.state.blend_set('NONE')
                    gpu.state.depth_test_set('ALWAYS')
                    gpu.state.line_width_set(1.0)
                    
                    # Create fresh shader
                    fresh_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
                    fresh_shader.bind()
                    
                    # Set edge properties based on lock state - FROM PREFERENCES
                    if self.lock_orientation:
                        edge_color = prefs.cursor_bisect_edge_locked_color
                        fresh_shader.uniform_float("color", (edge_color[0], edge_color[1], edge_color[2], edge_color[3]))
                        gpu.state.line_width_set(prefs.cursor_bisect_edge_locked_thickness)
                    else:
                        edge_color = prefs.cursor_bisect_edge_color
                        fresh_shader.uniform_float("color", (edge_color[0], edge_color[1], edge_color[2], edge_color[3]))
                        gpu.state.line_width_set(prefs.cursor_bisect_edge_thickness)
                    
                    gpu.state.depth_test_set('ALWAYS')
                    
                    # Draw edge
                    fresh_batch = batch_for_shader(fresh_shader, 'LINES', {"pos": world_coords})
                    fresh_batch.draw(fresh_shader)
                    
                    # Reset state
                    gpu.state.line_width_set(1.0)
                    
            except (IndexError, AttributeError):
                pass

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
            print(f"Error in align_cursor_orientation: {e}")

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
        self.edge_subdivisions = 0  # 0 subdivisions by default
        self.hold_snap_points = False
        self.last_face_index = -1

        # Add draw handler
        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_callback, (context,), 'WINDOW', 'POST_VIEW'
        )
        
        # Add timer for smoother updates
        self._timer = context.window_manager.event_timer_add(0.1, window=context.window)
        
        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        # Handle timer events
        if event.type == 'TIMER':
            return {'PASS_THROUGH'}
        
        # Handle Ctrl+Wheel for edge subdivision control FIRST (before other wheel events)
        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and event.ctrl and not event.shift:
            if self.snapping_enabled:
                if event.type == 'WHEELUPMOUSE':
                    self.edge_subdivisions = min(self.edge_subdivisions + 1, 10)
                else:
                    self.edge_subdivisions = max(self.edge_subdivisions - 1, 0)
                
                # Update snap points with new subdivision
                if self.hit_obj and self.hit_face_index != -1 and not self.hold_snap_points:
                    self.update_snapping(context, context.scene.cursor.location)
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}  # Consume the event
            return {'PASS_THROUGH'}
            
        # Handle Shift+Wheel for edge cycling
        elif event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and event.shift and not event.ctrl:
            if self.face_edges:
                if event.type == 'WHEELUPMOUSE':
                    self.edge_index = (self.edge_index + 1) % len(self.face_edges)
                else:
                    self.edge_index = (self.edge_index - 1) % len(self.face_edges)
                
                # Always update orientation when manually cycling edges, even if locked
                if not self.hold_snap_points:
                    self.align_cursor_orientation()
                context.area.tag_redraw()
            return {'RUNNING_MODAL'}  # Consume the event
            
        # Allow navigation - don't intercept middle mouse or plain navigation wheel
        elif event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            # Only handle if we haven't already handled it above
            return {'PASS_THROUGH'}

        # Mouse movement - update cursor position and orientation
        if event.type == 'MOUSEMOVE':
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
                
                # Update snapping
                self.update_snapping(context, loc)
                
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
                                self.edge_index = 0
                    except (IndexError, AttributeError):
                        pass
                self.align_cursor_orientation()
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Toggle normal axis
        elif event.type == 'X' and event.value == 'PRESS' and not event.shift and not event.ctrl:
            self.normal_axis = 'Y' if self.normal_axis == 'X' else 'X'
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Toggle face selection
        elif event.type == 'C' and event.value == 'PRESS' and not event.shift and not event.ctrl:
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
                except (IndexError, AttributeError):
                    pass
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

        # Confirm and exit
        elif event.type == 'SPACE' and event.value == 'PRESS':
            self.cancel(context)
            return {'FINISHED'}

        # Cancel
        elif event.type in {'ESC', 'RIGHTMOUSE'}:
            self.cancel(context)
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def execute(self, context):
        """Execute the bisect operation on all selected mesh objects in edit mode"""
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

                # Get geometry to bisect
                selected_faces = [f for f in bm.faces if f.select]
                if selected_faces:
                    # Use only selected faces and their components
                    geom = list({v for f in selected_faces for v in f.verts} |
                               {e for f in selected_faces for e in f.edges} |
                               set(selected_faces))
                else:
                    # Use all geometry
                    geom = bm.verts[:] + bm.edges[:] + bm.faces[:]

                # Transform plane to object space
                obj_matrix = obj.matrix_world
                plane_no = obj_matrix.to_3x3().inverted_safe() @ axis_world
                plane_no.normalize()
                plane_co = obj_matrix.inverted() @ cursor.location

                # Perform bisect
                bmesh.ops.bisect_plane(
                    bm,
                    geom=geom,
                    plane_co=plane_co,
                    plane_no=plane_no,
                )

                # Merge doubles if requested
                if self.merge_doubles:
                    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=self.merge_distance)

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

    def cancel(self, context):
        """Clean up and cancel the operation"""
        if self._handle:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
            self._handle = None
            
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
            
        context.area.tag_redraw()