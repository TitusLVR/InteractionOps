import bpy
import bmesh
import gpu
from gpu_extras.batch import batch_for_shader
from bpy_extras import view3d_utils
import mathutils
from mathutils import Vector
import blf

class IOPS_OT_Mesh_Quick_Connect(bpy.types.Operator):
    bl_idname = "iops.mesh_quick_connect"
    bl_label = "Quick Connect"
    bl_description = "Connect two vertices by dragging"
    bl_options = {'REGISTER'}

    start_point_2d = None
    end_point_2d = None
    
    _handle = None
    _handle_text = None
    start_vert_index = -1
    end_vert_index = -1
    mouse_pos = (0, 0)
    
    # Hover data
    hover_vert_index = -1
    hover_point_2d = None
    
    # Undo tracking
    undo_steps = 0
    
    # Drawing data
    shader = None
    batch = None


    is_a_held = False
    use_midpoint_snap = False
    use_screen_space = False
    preview_edge_index = -1
    preview_edge_point_3d = None

    def invoke(self, context, event):
        if context.active_object.mode != 'EDIT':
            return {'CANCELLED'}

        self.mouse_pos = (event.mouse_region_x, event.mouse_region_y)
        
        # Initialize drawing
        self.undo_steps = 0
        bpy.ops.ed.undo_push(message="Start Quick Connect")
        
        self.shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        args = (context,)
        self._handle = bpy.types.SpaceView3D.draw_handler_add(self.draw_callback_px, args, 'WINDOW', 'POST_PIXEL')
        self._handle_text = bpy.types.SpaceView3D.draw_handler_add(self.draw_shortcuts_callback, args, 'WINDOW', 'POST_PIXEL')
        
        context.window_manager.modal_handler_add(self)
        
        # If invoked by a click, start immediately
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            self.start_vert_index = self.find_closest_vertex(context, event)
            self.update_points(context)
        else:
            self.start_vert_index = -1
            
        self.update_status_bar(context)
        return {'RUNNING_MODAL'}

    def update_status_bar(self, context):
        snap_status = "ON" if self.use_midpoint_snap else "OFF"
        screen_status = "ON" if self.use_screen_space else "OFF"
        status_text = f"Quick Connect: [LMB] Drag to Connect | [A] Hold to Split Edge | [S] Snap Midpoint({snap_status}) | [W] Screen Space({screen_status}) | [MMB] Navigation | [Space] Finish | [Esc/RMB] Cancel"
        context.workspace.status_text_set(status_text)

    def draw_shortcuts_callback(self, context):
        try:
            font_id = 0
            blf.size(font_id, 16)
            blf.disable(font_id, blf.SHADOW)
            
            # Use hardcoded defaults first to ensure visibility
            tColor = (1.0, 1.0, 1.0, 1.0)
            tKColor = (1.0, 0.8, 0.2, 1.0)
            tCSize = 16
            tCPosX = 20
            tCPosY = 60
            
            try:
                prefs = context.preferences.addons["InteractionOps"].preferences
                # Ensure we actually get values, otherwise stick to defaults
                if hasattr(prefs, "text_color"): tColor = prefs.text_color
                if hasattr(prefs, "text_color_key"): tKColor = prefs.text_color_key
                if hasattr(prefs, "text_size"): tCSize = prefs.text_size
                if hasattr(prefs, "text_pos_x"): tCPosX = prefs.text_pos_x
                if hasattr(prefs, "text_pos_y"): tCPosY = prefs.text_pos_y
            except (KeyError, AttributeError):
                pass
                
            uifactor = context.preferences.system.ui_scale
            
            shortcuts = [
                ("Connect", "LMB Drag"),
                ("Split Edge (Hold)", "A"),
                ("Snap Midpoint", "S" + (" [ON]" if self.use_midpoint_snap else " [OFF]")),
                ("Screen Space", "W" + (" [ON]" if self.use_screen_space else " [OFF]")),
                ("Navigation", "MMB"),
                ("Finish", "SPACE"),
                ("Cancel", "ESC / RMB"),
            ]
            
            blf.size(font_id, int(tCSize * uifactor))
            
            # Calculate layout
            max_action_width = 0
            for line in shortcuts:
                action_width = blf.dimensions(font_id, line[0])[0]
                max_action_width = max(max_action_width, action_width)
            
            action_start_x = tCPosX * uifactor
            padding = (tCSize * 2) * uifactor
            keys_right_edge = action_start_x + max_action_width + padding + (tCSize * 8) * uifactor
            
            offset = tCPosY * uifactor
            
            # Draw text lines (reversed order for bottom-up display)
            for line in reversed(shortcuts):
                # Draw action description
                blf.color(font_id, tColor[0], tColor[1], tColor[2], tColor[3])
                blf.position(font_id, action_start_x, offset, 0)
                blf.draw(font_id, line[0])
                
                # Draw key binding
                blf.color(font_id, tKColor[0], tKColor[1], tKColor[2], tKColor[3])
                key_width = blf.dimensions(font_id, line[1])[0]
                key_x_pos = keys_right_edge - key_width
                blf.position(font_id, key_x_pos, offset, 0)
                blf.draw(font_id, line[1])
                
                offset += (tCSize + 5) * uifactor
                
        except ReferenceError:
            pass
        except Exception as e:
            print(f"Error in draw_shortcuts_callback: {e}")
            pass

    def modal(self, context, event):
        context.area.tag_redraw()

        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} or event.type.startswith('NDOF'):
            return {'PASS_THROUGH'}

        if event.type == 'MOUSEMOVE':
            self.mouse_pos = (event.mouse_region_x, event.mouse_region_y)
            
            if self.is_a_held:
                self.update_edge_preview(context, event)
                # If previewing edge, snap end point to it
                if self.preview_edge_point_3d:
                     region = context.region
                     rv3d = context.region_data
                     self.end_point_2d = view3d_utils.location_3d_to_region_2d(region, rv3d, self.preview_edge_point_3d)
            elif self.start_vert_index != -1:
                self.end_vert_index = self.find_closest_vertex(context, event)
                self.update_points(context)
            else:
                self.update_hover(context, event)
                
            return {'RUNNING_MODAL'}
            
        elif event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            if not self.is_a_held:
                # Start new drag
                self.start_vert_index = self.find_closest_vertex(context, event)
                self.update_points(context)
            return {'RUNNING_MODAL'}

        elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            if not self.is_a_held:
                # Execute connection if dragging
                if self.start_vert_index != -1:
                    if self.end_vert_index != -1 and self.start_vert_index != self.end_vert_index:
                        self.connect_verts(context)
                    
                    # Reset for next operation
                    self.start_vert_index = -1
                    self.end_vert_index = -1
                    self.start_point_2d = None
                    self.end_point_2d = None
                
            return {'RUNNING_MODAL'}
            
        elif event.type == 'A':
            if event.value == 'PRESS':
                self.is_a_held = True
                self.update_edge_preview(context, event)
            elif event.value == 'RELEASE':
                self.is_a_held = False
                if self.preview_edge_index != -1:
                    self.execute_edge_split(context)
                    self.preview_edge_index = -1
                    self.preview_edge_point_3d = None
                    # Resume normal operation, end_point_2d will be updated on next mouse move
            
            return {'RUNNING_MODAL'}
            
        elif event.type == 'S' and event.value == 'PRESS':
            self.use_midpoint_snap = not self.use_midpoint_snap
            self.update_status_bar(context)
            # Update preview if A is held
            if self.is_a_held:
                self.update_edge_preview(context, event)
            return {'RUNNING_MODAL'}
            
        elif event.type == 'W' and event.value == 'PRESS':
            self.use_screen_space = not self.use_screen_space
            self.update_status_bar(context)
            return {'RUNNING_MODAL'}

        elif event.type == 'SPACE' and event.value == 'PRESS':
            self.remove_handler(context)
            context.workspace.status_text_set(None)
            return {'FINISHED'}

        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            self.remove_handler(context)
            context.workspace.status_text_set(None) # Clear status bar
            
            # Undo changes made during the session
            for _ in range(self.undo_steps):
                bpy.ops.ed.undo()
                
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def remove_handler(self, context):
        if self._handle:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
            self._handle = None
        if self._handle_text:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_text, 'WINDOW')
            self._handle_text = None
        context.area.tag_redraw()

    def draw_callback_px(self, context):
        try:
            # Draw hover highlight if not dragging
            if self.start_vert_index == -1 and self.hover_point_2d:
                gpu.state.point_size_set(10.0)
                self.shader.bind()
                self.shader.uniform_float("color", (0.0, 1.0, 0.0, 1.0)) # Green for hover
                batch_hover = batch_for_shader(self.shader, 'POINTS', {"pos": [self.hover_point_2d]})
                batch_hover.draw(self.shader)
                gpu.state.point_size_set(1.0)

            if not self.start_point_2d:
                return

            coords_line = [self.start_point_2d]
            coords_points = [self.start_point_2d]
            
            if self.end_point_2d:
                coords_line.append(self.end_point_2d)
                coords_points.append(self.end_point_2d)
            else:
                coords_line.append(Vector(self.mouse_pos))

            # Draw line
            gpu.state.line_width_set(2.0)
            self.shader.bind()
            self.shader.uniform_float("color", (1.0, 1.0, 0.0, 1.0)) # Yellow
            
            batch_line = batch_for_shader(self.shader, 'LINES', {"pos": coords_line})
            batch_line.draw(self.shader)
            
            # Draw points
            gpu.state.point_size_set(8.0)
            self.shader.uniform_float("color", (1.0, 0.0, 0.0, 1.0)) # Red for points
            batch_points = batch_for_shader(self.shader, 'POINTS', {"pos": coords_points})
            batch_points.draw(self.shader)
            
            # Draw edge preview point if A is held
            if self.is_a_held and self.preview_edge_point_3d:
                region = context.region
                rv3d = context.region_data
                preview_2d = view3d_utils.location_3d_to_region_2d(region, rv3d, self.preview_edge_point_3d)
                
                if preview_2d:
                    self.shader.uniform_float("color", (0.0, 1.0, 1.0, 1.0)) # Cyan for preview
                    batch_preview = batch_for_shader(self.shader, 'POINTS', {"pos": [preview_2d]})
                    batch_preview.draw(self.shader)
            
            # Restore state
            gpu.state.line_width_set(1.0)
            gpu.state.point_size_set(1.0)
            
        except ReferenceError:
            # Operator might be finished/dead
            pass
        except Exception:
            pass

    def find_closest_vertex(self, context, event):
        if self.use_screen_space:
            return self.find_closest_vertex_screen_space(context, event)

        # First, find the object under the mouse
        region = context.region
        rv3d = context.region_data
        coord = (event.mouse_region_x, event.mouse_region_y)
        view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        depsgraph = context.evaluated_depsgraph_get()

        # Raycast to find the object
        result, location, normal, index, obj, matrix = context.scene.ray_cast(
            depsgraph, ray_origin, view_vector
        )

        if not result or obj != context.active_object:
            # Fallback: if raycast fails (e.g. on wireframe or close to vert but off face), 
            # use the screen space projection method but only for the active object.
            return self.find_closest_vertex_screen_space(context, event)
        
        # If we hit the object, we have a 3D location. Find the closest vertex to this location.
        # We need to transform the hit location to object space
        mw = obj.matrix_world
        mwi = mw.inverted()
        hit_pos_local = mwi @ location
        
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        
        # Find closest vertex to hit_pos_local
        closest_index = -1
        min_dist_sq = float('inf')
        
        for v in bm.verts:
            dist_sq = (v.co - hit_pos_local).length_squared
            if dist_sq < min_dist_sq:
                min_dist_sq = dist_sq
                closest_index = v.index
                
        return closest_index

    def find_closest_vertex_screen_space(self, context, event):
        obj = context.active_object
        if not obj: return -1
        
        region = context.region
        rv3d = context.region_data
        
        me = obj.data
        bm = bmesh.from_edit_mesh(me)
        bm.verts.ensure_lookup_table()
        
        closest_index = -1
        min_dist = 30.0 # Threshold in pixels
        
        mouse_co = Vector((event.mouse_region_x, event.mouse_region_y))
        mw = obj.matrix_world
        
        # Prepare for occlusion check
        ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, (event.mouse_region_x, event.mouse_region_y))
        depsgraph = context.evaluated_depsgraph_get()
        
        candidates = []

        for v in bm.verts:
            co_world = mw @ v.co
            co_screen = view3d_utils.location_3d_to_region_2d(region, rv3d, co_world)
            
            if co_screen:
                dist = (co_screen - mouse_co).length
                if dist < min_dist:
                    candidates.append((dist, v.index, co_world))
        
        # Sort by 2D distance
        candidates.sort(key=lambda x: x[0])
        
        for dist, index, co_world in candidates:
            # Check occlusion
            # Raycast from camera to vertex
            direction = (co_world - ray_origin).normalized()
            dist_to_vert = (co_world - ray_origin).length
            
            result, location, normal, hit_index, hit_obj, matrix = context.scene.ray_cast(
                depsgraph, ray_origin, direction, distance=dist_to_vert - 0.001
            )
            
            # If we hit something closer, it's occluded
            if result:
                 # Check if we hit the same object (self-occlusion check)
                 # If we hit the same object, we need to be careful. 
                 # But generally if we hit a face of the same object closer than the vertex, it is occluded.
                 continue
            
            # If not occluded, this is the closest visible vertex
            return index
                    
        return -1

    def connect_verts(self, context):
        obj = context.active_object
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        
        try:
            v1 = bm.verts[self.start_vert_index]
            v2 = bm.verts[self.end_vert_index]
            
            # We need to use bpy.ops.mesh.vert_connect_path to cut across edges (J-key behavior)
            # This operator works on selection.
            
            # We need to use bpy.ops.mesh.vert_connect_path to cut across edges (J-key behavior)
            # This operator works on selection.
            
            # Deselect all using bmesh to avoid undo step
            for v in bm.verts: v.select = False
            for e in bm.edges: e.select = False
            for f in bm.faces: f.select = False
            
            v1.select = True
            v2.select = True
            
            # Flush selection to ensure blender knows about it
            bmesh.update_edit_mesh(obj.data)
            
            # Call the operator
            bpy.ops.ed.undo_push(message="Connect Verts")
            bpy.ops.mesh.vert_connect_path()
            self.undo_steps += 1
            
        except ValueError:
            self.report({'WARNING'}, "Could not connect vertices")
        except IndexError:
             self.report({'WARNING'}, "Vertex index error")
        except Exception as e:
            self.report({'WARNING'}, f"Operation failed: {e}")

    def update_edge_preview(self, context, event):
        edge_index, hit_pos = self.find_closest_edge(context, event)
        self.preview_edge_index = edge_index
        self.preview_edge_point_3d = hit_pos

    def execute_edge_split(self, context):
        if self.preview_edge_index == -1 or not self.preview_edge_point_3d:
            return

        obj = context.active_object
        bm = bmesh.from_edit_mesh(obj.data)
        bm.edges.ensure_lookup_table()
        bm.verts.ensure_lookup_table()
        
        try:
            edge = bm.edges[self.preview_edge_index]
            
            bpy.ops.ed.undo_push(message="Split Edge")
            self.undo_steps += 1
            
            res = bmesh.ops.subdivide_edges(bm, edges=[edge], cuts=1)
            new_vert = res['geom_inner'][0]
            
            mw = obj.matrix_world
            mwi = mw.inverted()
            local_hit = mwi @ self.preview_edge_point_3d
            
            new_vert.co = local_hit
            
            bmesh.update_edit_mesh(obj.data)
            
            if self.start_vert_index != -1:
                # Deselect all using bmesh
                for v in bm.verts: v.select = False
                for e in bm.edges: e.select = False
                for f in bm.faces: f.select = False
                
                bm.verts.ensure_lookup_table()
                if self.start_vert_index < len(bm.verts):
                    v1 = bm.verts[self.start_vert_index]
                    v1.select = True
                    new_vert.select = True
                    
                    bmesh.update_edit_mesh(obj.data)
                    bpy.ops.mesh.vert_connect_path()
                    self.undo_steps += 1
            
            # Set new start vertex
            bm = bmesh.from_edit_mesh(obj.data)
            bm.verts.ensure_lookup_table()
            
            closest_v = None
            min_d = 0.0001
            
            for v in bm.verts:
                if (v.co - local_hit).length < min_d:
                    closest_v = v
                    break
            
            if closest_v:
                self.start_vert_index = closest_v.index
                self.update_points(context)
            else:
                self.start_vert_index = -1
                self.start_point_2d = None
                
        except Exception as e:
            print(f"Error in execute_edge_split: {e}")
            self.report({'WARNING'}, "Failed to split edge")

    def handle_a_key(self, context, event):
        # Deprecated, logic moved to update_edge_preview and execute_edge_split
        pass

    def find_closest_edge(self, context, event):
        obj = context.active_object
        region = context.region
        rv3d = context.region_data
        
        coord = (event.mouse_region_x, event.mouse_region_y)
        view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        
        # Raycast to find face
        depsgraph = context.evaluated_depsgraph_get()
        result, location, normal, index, hit_obj, matrix = context.scene.ray_cast(
            depsgraph, ray_origin, view_vector
        )
        
        if not result or hit_obj != obj:
            return -1, None
            
        # We hit a face. Find the closest edge of this face to the hit location.
        mw = obj.matrix_world
        mwi = mw.inverted()
        local_hit = mwi @ location
        
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        
        if index >= len(bm.faces):
            return -1, None
            
        face = bm.faces[index]
        
        closest_edge_index = -1
        min_dist_sq = float('inf')
        closest_point_on_edge = None
        
        for edge in face.edges:
            # Project local_hit onto edge
            v1 = edge.verts[0].co
            v2 = edge.verts[1].co
            
            if self.use_midpoint_snap:
                closest_pt = (v1 + v2) / 2
            else:
                # Point on segment
                closest_pt, percent = mathutils.geometry.intersect_point_line(local_hit, v1, v2)
                
                # Clamp percent 0-1
                if percent < 0:
                    closest_pt = v1
                elif percent > 1:
                    closest_pt = v2
                
            dist_sq = (closest_pt - local_hit).length_squared
            
            if dist_sq < min_dist_sq:
                min_dist_sq = dist_sq
                closest_edge_index = edge.index
                closest_point_on_edge = closest_pt
                
        world_point = mw @ closest_point_on_edge
        
        return closest_edge_index, world_point

    def update_hover(self, context, event):
        # Find closest vertex for hover effect
        idx = self.find_closest_vertex(context, event)
        
        if idx != -1:
            obj = context.active_object
            bm = bmesh.from_edit_mesh(obj.data)
            bm.verts.ensure_lookup_table()
            
            try:
                v = bm.verts[idx]
                mw = obj.matrix_world
                region = context.region
                rv3d = context.region_data
                
                co_2d = view3d_utils.location_3d_to_region_2d(region, rv3d, mw @ v.co)
                
                if co_2d:
                    mouse_co = Vector((event.mouse_region_x, event.mouse_region_y))
                    dist = (co_2d - mouse_co).length
                    
                    # Threshold for hover highlight (e.g. 20 pixels)
                    if dist < 20.0:
                        self.hover_vert_index = idx
                        self.hover_point_2d = co_2d
                        return
            except IndexError:
                pass
                
        self.hover_vert_index = -1
        self.hover_point_2d = None

    def update_points(self, context):
        obj = context.active_object
        if not obj: return

        region = context.region
        rv3d = context.region_data
        mw = obj.matrix_world
        
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        
        if self.start_vert_index != -1:
            try:
                v1 = bm.verts[self.start_vert_index]
                self.start_point_2d = view3d_utils.location_3d_to_region_2d(region, rv3d, mw @ v1.co)
            except IndexError:
                self.start_point_2d = None
        
        if self.end_vert_index != -1:
            try:
                v2 = bm.verts[self.end_vert_index]
                self.end_point_2d = view3d_utils.location_3d_to_region_2d(region, rv3d, mw @ v2.co)
            except IndexError:
                self.end_point_2d = None
        else:
            self.end_point_2d = None
