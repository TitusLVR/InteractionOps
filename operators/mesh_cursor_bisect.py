import bpy
import mathutils
import bmesh
from mathutils import Vector
import gpu
from gpu_extras.batch import batch_for_shader


class IOPS_OT_Mesh_Cursor_Bisect(bpy.types.Operator):
    """Bisect mesh using 3D cursor position and orientation"""
    bl_idname = "iops.mesh_cursor_bisect"
    bl_label = "Cursor Bisect"
    bl_description = "Bisect the mesh using the 3D cursor position and orientation"
    bl_options = {'REGISTER', 'UNDO'}

    
    axis: bpy.props.EnumProperty(
        name="Bisect Axis",
        description="Choose the axis for bisecting",
        items=[
            ('X', "X Axis", "Bisect along the X axis"),
            ('Y', "Y Axis", "Bisect along the Y axis"),
            ('Z', "Z Axis", "Bisect along the Z axis"),
        ],
        default='Y'
    )

    _handle = None

    def draw_callback(self, context):
        """Draw a plane centered at the 3D cursor location, perpendicular to the selected axis."""
        cursor = context.scene.cursor
        plane_co = cursor.location

        # Get the active object's transformation matrix
        obj = context.object
        if obj is None:
            return
        matrix_world = obj.matrix_world

        # Determine the axis direction
        if self.axis == 'X':
            color = (1.0, 0.0, 0.0, 0.3)
            u = Vector((0.0, 1.0, 0.0))
            v = Vector((0.0, 0.0, 1.0))
        elif self.axis == 'Y':
            color = (0.0, 1.0, 0.0, 0.3)
            u = Vector((1.0, 0.0, 0.0))
            v = Vector((0.0, 0.0, 1.0))
        elif self.axis == 'Z':
            color = (0.0, 0.0, 1.0, 0.3)
            u = Vector((1.0, 0.0, 0.0))
            v = Vector((0.0, 1.0, 0.0))

        # Transform the directions to world space
        u = matrix_world.to_3x3() @ u
        v = matrix_world.to_3x3() @ v

        # Define the plane corners centered at the cursor location
        size = 1.0  # Plane size
        corners = [
            plane_co + (u + v) * size,
            plane_co + (u - v) * size,
            plane_co + (-u - v) * size,
            plane_co + (-u + v) * size,
        ]

        # Draw the plane
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        batch = batch_for_shader(shader, 'TRI_FAN', {"pos": corners})
        shader.bind()
        shader.uniform_float("color", color)  # Axis-specific color with transparency
        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('NONE')  # Disable depth test for proper overlay
        batch.draw(shader)
        gpu.state.depth_test_set('LESS')  # Reset depth test
        gpu.state.blend_set('NONE')  # Reset blend mode

    def invoke(self, context, event):
        if context.area.type == 'VIEW_3D':
            self._handle = bpy.types.SpaceView3D.draw_handler_add(
                self.draw_callback, (context,), 'WINDOW', 'POST_VIEW'
            )
            context.window_manager.modal_handler_add(self)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        else:
            self.report({'WARNING'}, "View3D not found, cannot run operator")
            return {'CANCELLED'}

    def modal(self, context, event):
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            # allow navigation
            return {'PASS_THROUGH'}
        elif event.type in {'ESC', 'RIGHTMOUSE'}:  # Cancel the operation
            self.cancel(context)
            return {'CANCELLED'}
        elif event.type == 'LEFTMOUSE':  # Confirm the operation
            self.execute(context)
            self.cancel(context)
            return {'FINISHED'}
        elif event.type in {'X', 'Y', 'Z'}:  # Change the bisect axis
            self.axis = event.type
            context.area.tag_redraw()
        elif event.type in {'UP_ARROW', 'DOWN_ARROW'}:  # Adjust plane size
            if event.type == 'UP_ARROW':
                self.plane_size += 0.1
            elif event.type == 'DOWN_ARROW':
                self.plane_size = max(0.1, self.plane_size - 0.1)
            context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    # Assuming this is inside your Operator class execute method
    def execute(self, context):
        # --- Context ---
        # Get the active object and its data
        obj = context.object

        # --- Context Checks ---
        if not obj:
            self.report({'ERROR'}, "No active object selected.")
            return {'CANCELLED'}
        if obj.type != 'MESH':
            self.report({'ERROR'}, "Active object is not a Mesh.")
            return {'CANCELLED'}
        if obj.mode != 'EDIT':
            self.report({'ERROR'}, "Not in Edit Mode. Please switch to Edit Mode.")
            return {'CANCELLED'}

        # --- Get Data ---
        cursor = context.scene.cursor
        plane_co_world = cursor.location.copy()
        matrix_world = obj.matrix_world
        matrix_world_inv = matrix_world.inverted_safe()

        # --- Define Plane in Local Space ---
        plane_co_local = matrix_world_inv @ plane_co_world
        plane_no_local = Vector((0.0, 0.0, 0.0))
        if self.axis == 'X':
            plane_no_local = Vector((1.0, 0.0, 0.0))
        elif self.axis == 'Y':
            plane_no_local = Vector((0.0, 1.0, 0.0))
        elif self.axis == 'Z':
            plane_no_local = Vector((0.0, 0.0, 1.0))
        else:
            self.report({'ERROR'}, "Invalid axis specified.")
            return {'CANCELLED'}
        # plane_no_local.normalize() # Already unit vectors

        # --- Use BMesh ---
        bm = bmesh.from_edit_mesh(obj.data)

        # --- Get Selected Geometry ---
        # Focus on selected faces as requested
        selected_faces = [f for f in bm.faces if f.select]

        if not selected_faces:
            self.report({'WARNING'}, "No faces selected for bisection.")
            # No need to update mesh if nothing happened
            return {'CANCELLED'}

        # The 'geom' parameter needs all elements involved. It's safest to include
        # the vertices and edges associated with the selected faces.
        # Use sets for efficiency in gathering unique elements.
        geom_faces = set(selected_faces)
        geom_edges = set(e for f in geom_faces for e in f.edges)
        geom_verts = set(v for f in geom_faces for v in f.verts)

        # Combine into a list for the operator
        geom = list(geom_verts) + list(geom_edges) + list(geom_faces)

        # --- Perform Bisection ---
        try:
            # Perform the bisection ONLY on the selected geometry
            result = bmesh.ops.bisect_plane(
                bm,
                geom=geom,                  # Pass only the selected geometry elements
                plane_co=plane_co_local,
                plane_no=plane_no_local,
                # use_fill=self.use_fill,
                # clear_inner=self.clear_inner,
                # clear_outer=self.clear_outer,
            )

            # --- Manage Selection After Cut ---
            # 1. Deselect the original faces that were part of the input 'geom'
            #    (Necessary if clear_inner/outer=False leaves parts behind)
            for f in selected_faces:
                # Check if face still exists (it might have been deleted)
                if f.is_valid:
                    f.select_set(False)
            # Optionally deselect original edges/verts too if needed, but face deselection often covers it visually.

            # 2. Select the newly created geometry (boundary edges/verts, and new face if use_fill=True)
            if result and 'geom_cut' in result:
                for element in result['geom_cut']:
                    # Check element is still valid after topology changes
                    if element.is_valid:
                        element.select_set(True)

            # Ensure selection changes are registered back to the mesh data
            bm.select_flush_mode() # Recommended after manual selections

            # Update the actual mesh data from the BMesh structure
            bmesh.update_edit_mesh(obj.data)

            # Force viewport update if needed (sometimes helps immediately see changes)
            # context.view_layer.update()

        except Exception as e:
            self.report({'ERROR'}, f"BMesh bisect failed: {e}")
            # Avoid updating mesh on error to prevent partial changes? Or allow update?
            # Let's assume we don't update on error.
            return {'CANCELLED'}
        # finally:
            # bm.free() # Not needed with 'from_edit_mesh'

        return {'FINISHED'}


    def cancel(self, context):
        if self._handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
        self._handle = None

