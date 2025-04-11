import bpy
import mathutils
import bmesh
from mathutils import Vector
import gpu
from gpu_extras.batch import batch_for_shader
# Removed heapq import as 'merge' wasn't used

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
    merge_doubles: bpy.props.BoolProperty(
        name="Merge Doubles",
        description="Merge vertices after bisecting",
        default=True
    )
    merge_distance: bpy.props.FloatProperty(
        name="Merge Distance",
        description="Distance for merging vertices after bisecting",
        default=0.005,
        min=0.0,
        max=10.0,
    )

    _handle = None
    # _plane_size removed as it wasn't defined or used consistently

    def draw_callback(self, context):
        cursor = context.scene.cursor
        plane_co = cursor.location
        obj = context.object
        if obj is None:
            return

        cursor_mx = bpy.context.scene.cursor.matrix

        if self.axis == 'X':
            color = (1.0, 0.0, 0.0, 0.3)
            u = Vector((0.0, 1.0, 0.0))
            v = Vector((0.0, 0.0, 1.0))
        elif self.axis == 'Y':
            color = (0.0, 1.0, 0.0, 0.3)
            u = Vector((1.0, 0.0, 0.0))
            v = Vector((0.0, 0.0, 1.0))
        else: # self.axis == 'Z'
            color = (0.0, 0.0, 1.0, 0.3)
            u = Vector((1.0, 0.0, 0.0))
            v = Vector((0.0, 1.0, 0.0))

        u = cursor_mx.to_3x3() @ u
        v = cursor_mx.to_3x3() @ v

        size = 1.0 # Keep a fixed size for the visual aid
        corners = [
            plane_co + (u + v) * size,
            plane_co + (u - v) * size,
            plane_co + (-u - v) * size,
            plane_co + (-u + v) * size,
        ]

        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        batch = batch_for_shader(shader, 'TRI_FAN', {"pos": corners})
        shader.bind()
        shader.uniform_float("color", color)
        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('NONE')
        batch.draw(shader)
        gpu.state.depth_test_set('LESS')
        gpu.state.blend_set('NONE')

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
        if event.type in {'MIDDLEMOUSE'}:
            return {'PASS_THROUGH'}
        elif event.type in {'ESC', 'RIGHTMOUSE'}:
            self.cancel(context)
            return {'CANCELLED'}
        elif event.type == 'LEFTMOUSE':
            self.execute(context)
            self.cancel(context)
            return {'FINISHED'}
        elif event.type == 'WHEELUPMOUSE':
            self.axis = {'X': 'Y', 'Y': 'Z', 'Z': 'X'}[self.axis]
            context.area.tag_redraw()
            return {'RUNNING_MODAL'} # Stay modal
        elif event.type == 'WHEELDOWNMOUSE':
            self.axis = {'X': 'Z', 'Z': 'Y', 'Y': 'X'}[self.axis]
            context.area.tag_redraw()
            return {'RUNNING_MODAL'} # Stay modal
        # Removed arrow key handling for plane size as it wasn't fully implemented

        # Redraw requested for axis changes or potentially other interactions
        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
             context.area.tag_redraw()

        return {'RUNNING_MODAL'}


    def execute(self, context):
        obj = context.object
        scene = context.scene
        cursor = scene.cursor

        if not obj:
            self.report({'ERROR'}, "No active object selected.")
            return {'CANCELLED'}
        if obj.type != 'MESH':
            self.report({'ERROR'}, "Active object is not a Mesh.")
            return {'CANCELLED'}
        if obj.mode != 'EDIT':
            self.report({'ERROR'}, "Not in Edit Mode. Please switch to Edit Mode.")
            return {'CANCELLED'}

        obj_mat_world = obj.matrix_world
        obj_mat_world_inv = obj_mat_world.inverted()
        cursor_mat_world = cursor.matrix

        plane_co_local = obj_mat_world_inv @ cursor.location

        if self.axis == 'X':
            base_normal = mathutils.Vector((1, 0, 0))
        elif self.axis == 'Y':
            base_normal = mathutils.Vector((0, 1, 0))
        else: # self.axis == 'Z'
            base_normal = mathutils.Vector((0, 0, 1))

        normal_world = cursor_mat_world.to_3x3() @ base_normal
        normal_world.normalize()

        plane_no_local = obj_mat_world_inv.to_3x3() @ normal_world
        plane_no_local.normalize()

        bm = bmesh.from_edit_mesh(obj.data)

        selected_faces = [f for f in bm.faces if f.select]
        if not selected_faces:
             # If no faces selected, operate on the whole mesh implicitly
             # by not restricting the 'geom' input (or providing all geometry)
             # For bisect_plane, providing None or all geom works
             geom = bm.verts[:] + bm.edges[:] + bm.faces[:] # Operate on everything
        else:
             # Operate only on selected faces and their constituent edges/verts
             geom_faces = set(selected_faces)
             geom_edges = set(e for f in geom_faces for e in f.edges)
             geom_verts = set(v for f in geom_faces for v in f.verts)
             geom = list(geom_verts) + list(geom_edges) + list(geom_faces)


        try:
            result = bmesh.ops.bisect_plane(
                bm,
                geom=geom,
                plane_co=plane_co_local,
                plane_no=plane_no_local,
                # clear_inner=False, # Default
                # clear_outer=False, # Default
                # use_fill=False     # Default
            )

            if self.merge_doubles:
                bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=self.merge_distance)
            else:
                if selected_faces:
                    for f in selected_faces:
                        if f.is_valid:
                            f.select_set(False)

                if result and 'geom_cut' in result:
                    for element in result['geom_cut']:
                        if element.is_valid:
                            element.select_set(True)
                bm.select_flush(True)

            bmesh.update_edit_mesh(obj.data)

        except Exception as e:
            self.report({'ERROR'}, f"BMesh bisect failed: {e}")
            # Avoid freeing BMesh here as 'from_edit_mesh' handles it
            return {'CANCELLED'}

        return {'FINISHED'}

    def cancel(self, context):
        if self._handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
        self._handle = None
        # Ensure redraw happens on cancel to remove the visual aid
        if context.area:
            context.area.tag_redraw()
