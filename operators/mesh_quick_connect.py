import bpy
import bmesh
from bpy_extras import view3d_utils
import mathutils
from mathutils import Vector

from ..ui.draw import primitives as draw, draw_scope, Role
from ..ui.draw import safe_handler_add, safe_handler_remove
from ..ui.draw.theme import get_theme
from ..ui.hud import (HUDOverlay, HelpOverlay, HUDSection, HUDItem,
                      HUDParam, ItemState,
                      handle_hud_toggle, handle_help_toggle, capture_event)

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
        
        # HUD (cursor-following): operator title + live param values.
        self._hud = HUDOverlay("quick_connect")
        self._hud.title = "Quick Connect"
        self._hud.add_param(HUDParam(
            "Snap midpoint", lambda: self.use_midpoint_snap, kind="bool"))
        self._hud.add_param(HUDParam(
            "Screen space",  lambda: self.use_screen_space, kind="bool"))
        self._hud.bind_region(context.region)
        # Help overlay (corner): hotkey legend.
        self._help = HelpOverlay("quick_connect")
        self._help.add_section(HUDSection("Quick Connect", [
            HUDItem("Connect",         "LMB Drag",  ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Split edge",      "Hold A",    ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Snap midpoint",   "S",         ItemState.ON if self.use_midpoint_snap else ItemState.OFF),
            HUDItem("Screen space",    "W",         ItemState.ON if self.use_screen_space else ItemState.OFF),
            HUDItem("Finish",          "Space",     ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Cancel",          "Esc / RMB", ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Hide params",     "/",         ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Toggle help",     "H",         ItemState.ON, default_state=ItemState.OFF, always_show=True),
        ]))
        self._help.bind_region(context.region)
        self._last_event = capture_event(event, getattr(self, "_last_event", None))

        args = (context,)
        self._handle = safe_handler_add(bpy.types.SpaceView3D, self.draw_callback_px, args, 'WINDOW', 'POST_PIXEL', tick=True)
        self._handle_text = safe_handler_add(bpy.types.SpaceView3D, self.draw_shortcuts_callback, args, 'WINDOW', 'POST_PIXEL', tick=True)

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
        helpo = getattr(self, "_help", None)
        last_event = getattr(self, "_last_event", None)
        if helpo is not None:
            helpo.set_state("S", ItemState.ON if self.use_midpoint_snap else ItemState.OFF)
            helpo.set_state("W", ItemState.ON if self.use_screen_space else ItemState.OFF)
            helpo.draw(context, last_event)
        if hud is not None:
            hud.draw(context, last_event)

    def modal(self, context, event):
        context.area.tag_redraw()
        self._last_event = capture_event(event, getattr(self, "_last_event", None))
        try:
            theme_prefs = context.preferences.addons["InteractionOps"]\
                .preferences.iops_theme
        except (KeyError, AttributeError):
            theme_prefs = None
        if theme_prefs is not None:
            helpo = getattr(self, "_help", None)
            hud = getattr(self, "_hud", None)
            if helpo is not None and helpo.handle_drag_event(context, event, theme_prefs):
                return {'RUNNING_MODAL'}
            if hud is not None and hud.handle_drag_event(context, event, theme_prefs):
                return {'RUNNING_MODAL'}
            if helpo is not None and helpo.handle_toggle_event(event, theme_prefs):
                return {'RUNNING_MODAL'}
            if hud is not None and hud.handle_param_toggle_event(event, theme_prefs):
                return {'RUNNING_MODAL'}

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
            safe_handler_remove(self._handle, bpy.types.SpaceView3D, 'WINDOW')
            self._handle = None
        if self._handle_text:
            safe_handler_remove(self._handle_text, bpy.types.SpaceView3D, 'WINDOW')
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
        """Picks the active mesh's vertex under the mouse. If `use_screen_space`
        is on, runs the canonical screen-space-with-occlusion path; otherwise
        raycasts and finds the closest mesh vertex to the hit point."""
        from ..utils.picking import (
            raycast_from_mouse, nearest_vertex_screen,
        )
        mouse_coord = (event.mouse_region_x, event.mouse_region_y)
        obj = context.active_object
        if obj is None:
            return -1

        if self.use_screen_space:
            idx, _co = nearest_vertex_screen(
                context, obj, mouse_coord, check_occlusion=True)
            return -1 if idx is None else idx

        # Raycast first; if the cursor hovers our active mesh, snap to the
        # vertex closest to the hit point in OBJECT space (cheaper, picks
        # behind-face vertices the screen-space scan would miss).
        hit, location, _normal, _idx, hit_obj, _mat = raycast_from_mouse(
            context, mouse_coord, restrict_to={obj})
        if not hit:
            idx, _co = nearest_vertex_screen(
                context, obj, mouse_coord, check_occlusion=True)
            return -1 if idx is None else idx

        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        hit_pos_local = obj.matrix_world.inverted() @ location
        closest_index = -1
        min_dist_sq = float("inf")
        for v in bm.verts:
            d = (v.co - hit_pos_local).length_squared
            if d < min_dist_sq:
                min_dist_sq = d
                closest_index = v.index
        return closest_index

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
        """Raycast to the active mesh's face, then pick the edge of that face
        whose closest-point-on-segment (or midpoint, if `use_midpoint_snap`)
        is nearest to the hit point. Returns `(edge_index, world_point)`."""
        from ..utils.picking import raycast_from_mouse, closest_point_on_segment
        obj = context.active_object
        if obj is None:
            return -1, None

        mouse_coord = (event.mouse_region_x, event.mouse_region_y)
        hit, location, _normal, face_idx, hit_obj, _mat = raycast_from_mouse(
            context, mouse_coord, restrict_to={obj})
        if not hit:
            return -1, None

        mw = obj.matrix_world
        local_hit = mw.inverted() @ location

        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        if face_idx >= len(bm.faces):
            return -1, None
        face = bm.faces[face_idx]

        closest_edge_index = -1
        min_dist_sq = float("inf")
        closest_point_on_edge = None
        for edge in face.edges:
            v1, v2 = edge.verts[0].co, edge.verts[1].co
            if self.use_midpoint_snap:
                closest_pt = (v1 + v2) / 2
            else:
                closest_pt, _t = closest_point_on_segment(local_hit, v1, v2)
            d = (closest_pt - local_hit).length_squared
            if d < min_dist_sq:
                min_dist_sq = d
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
