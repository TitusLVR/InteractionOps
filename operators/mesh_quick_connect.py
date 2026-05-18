import bpy
import bmesh
from bpy_extras import view3d_utils
import mathutils
from mathutils import Vector

from ..ui.draw import primitives as draw, draw_scope, Role
from ..ui.draw.theme import get_theme
from ..ui.hud import HUDOverlay, HUDSection, HUDItem, ItemState

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
        
        self._hud = HUDOverlay("quick_connect",
                               verbosity=get_theme(context).hud.verbosity)
        self._hud.add_section(HUDSection("Quick Connect", [
            HUDItem("Connect",        "LMB Drag",     ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Split edge",     "Hold A",       ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Snap midpoint",  "S",            ItemState.ON if self.use_midpoint_snap else ItemState.OFF),
            HUDItem("Screen space",   "W",            ItemState.ON if self.use_screen_space else ItemState.OFF),
            HUDItem("Finish",         "Space",        ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Cancel",         "Esc / RMB",    ItemState.ON, default_state=ItemState.OFF, always_show=True),
        ]))
        self._hud.bind_region(context.region)
        self._last_event = event

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
        hud = getattr(self, "_hud", None)
        if hud is None:
            return
        hud.set_state("S", ItemState.ON if self.use_midpoint_snap else ItemState.OFF)
        hud.set_state("W", ItemState.ON if self.use_screen_space else ItemState.OFF)
        hud.draw(context, getattr(self, "_last_event", None))

    def modal(self, context, event):
        context.area.tag_redraw()
        self._last_event = event

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
            def _v3(p):
                return Vector((p[0], p[1], 0.0))

            with draw_scope(blend="ALPHA"):
                if self.start_vert_index == -1 and self.hover_point_2d:
                    draw.points([_v3(self.hover_point_2d)],
                                role=Role.CLOSEST_POINT, context=context)

                if not self.start_point_2d:
                    return

                coords_line = [_v3(self.start_point_2d)]
                coords_points = [_v3(self.start_point_2d)]

                if self.end_point_2d:
                    coords_line.append(_v3(self.end_point_2d))
                    coords_points.append(_v3(self.end_point_2d))
                else:
                    coords_line.append(_v3(self.mouse_pos))

                draw.edges_3d(coords_line, role=Role.ACTIVE_LINE, context=context)
                draw.points(coords_points, role=Role.ACTIVE_POINT, context=context)

                if self.is_a_held and self.preview_edge_point_3d:
                    region = context.region
                    rv3d = context.region_data
                    preview_2d = view3d_utils.location_3d_to_region_2d(
                        region, rv3d, self.preview_edge_point_3d)
                    if preview_2d:
                        draw.points([_v3(preview_2d)],
                                    role=Role.PREVIEW_POINT, context=context)
        except ReferenceError:
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
