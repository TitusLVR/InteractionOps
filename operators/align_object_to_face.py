import bpy
import blf
from bpy.props import (IntProperty,
                       FloatProperty,
                       BoolProperty,
                       StringProperty,
                       FloatVectorProperty)
import bmesh
import math
from math import radians, degrees
from mathutils import Vector, Matrix, Euler


def draw_callback_px(self, context):
        #_location = "Location: x = {0:.4f}, y = {1:.4f}, z = {2:.4f}"
        #_rotation = "Rotation: x = {0:.4f}, y = {1:.4f}, z = {2:.4f}"
        _align_edge = "Edge index: {0}"
        _axis_move = "Move Axis: " + str(self.axis_move)

        # Font
        font = 0
        blf.size(font, 20, 72)
        blf.color(font,1,1,0,1)
        

        # Align axis text overlay
        blf.position(font, 60, 120, 0)
        blf.draw(font, "Align axis: " + self.axis_rotate)

        # Move axis text overlay
        #blf.position(font, 60, 150, 0)
        #blf.draw(font, _align_edge.format(self.get_edge_idx(self.counter)))

        # Active axis text overlay
        blf.position(font, 60, 90, 0)
        blf.draw(font, _axis_move)

        # Location text overlay
        #blf.position(font, 60, 60, 0)
        #blf.draw(font, _location.format(self.loc[0], self.loc[1], self.loc[2]))

        # Rotation text overlay
        #blf.position(font, 60, 30, 0),
        #blf.draw(font, _rotation.format(degrees(self.rot[0]),
         #                               degrees(self.rot[1]),
          #                              degrees(self.rot[2])
           #                             ))


class AlignObjectToFace(bpy.types.Operator):
    """ Align object to selected face """
    bl_idname = "iops.align_object_to_face"
    bl_label = "MESH: Align object to face"
    bl_options = {"REGISTER", "UNDO"}

    axis_move    : StringProperty()
    axis_rotate  : StringProperty()
    loc          : FloatVectorProperty()
    loc_start    : FloatVectorProperty()
    edge_idx     : IntProperty()
    counter      : IntProperty()
    flip         : BoolProperty()

    rot = Euler()
    rot_start = Euler()

    @classmethod
    def poll(self, context):
        return len(context.selected_objects) > 0

    def rotate(self, axis):
        if axis == 'X':
            self.rot[0] += radians(90)
        elif axis == 'Y':
            self.rot[1] += radians(90)
        elif axis == 'Z':
            self.rot[2] += radians(90)

    def move(self, axis_move, step):
        if axis_move == 'X':
            self.loc[0] += step
        elif axis_move == 'Y':
            self.loc[1] += step
        elif axis_move == 'Z':
            self.loc[2] += step

    def get_edge_idx(self, idx):
        """Return edge index from (counter % number of edges) of a face"""
        obj = bpy.context.active_object
        polymesh = obj.data
        bm = bmesh.from_edit_mesh(polymesh)
        face = bm.faces.active
        face.edges.index_update()
        index = abs(idx % len(face.edges))

        return index

    def align_to_face(self, idx, axis, flip):
        """ Takes face normal and aligns it to global axis.
            Uses one of the face edges to further align it to another axis."""
        _axis = axis
        obj = bpy.context.active_object
        mx = obj.matrix_world
        loc = mx.to_translation()  # Store location
        scale = mx.to_scale()      # Store scale
        polymesh = obj.data
        bm = bmesh.from_edit_mesh(polymesh)
        face = bm.faces.active

        # Vector from and edge
        vector_edge = (face.edges[idx].verts[0].co -
                       face.edges[idx].verts[1].co).normalized()

        # Build vectors for new matrix
        n = face.normal if flip else (face.normal * -1)  # Z
        t = vector_edge                                  # Y
        c = t.cross(n)                                   # X

        # Assemble new matrix
        if axis == 'Z':
            mx_rot = Matrix((c, t, n)).transposed().to_4x4()
        elif axis == 'Y':
            mx_rot = Matrix((t, n, c)).transposed().to_4x4()
        elif axis == 'X':
            mx_rot = Matrix((n, c, t)).transposed().to_4x4()

        # Apply new matrix
        obj.matrix_world = mx_rot.inverted()
        obj.location = loc
        obj.scale = scale

    def modal(self, context, event):
        context.area.tag_redraw()

        if event.type in {'MIDDLEMOUSE'}:
            # Allow navigation
            return {'PASS_THROUGH'}
        # ---------------------------------------------------------
        # Moving object while SHIFT is pressed for testing purpose
        # ---------------------------------------------------------
        if event.shift:
            if event.type in {'X', 'Y', 'Z'} and event.value == "PRESS":
                self.axis_move = event.type
                bpy.context.object.location = self.loc
                print("Changed to: " + self.axis_move)

            elif event.type == "WHEELDOWNMOUSE":
                self.move(self.axis_move, -0.5)
                bpy.context.object.location = self.loc
                print("Moving along: " + self.axis_move)

            elif event.type == "WHEELUPMOUSE":
                self.move(self.axis_move, 0.5)
                bpy.context.object.location = self.loc
                print("Moving along: " + self.axis_move)
        # ---------------------------------------------------------
        elif event.type in {'X', 'Y', 'Z'} and event.value == "PRESS":
                self.axis_rotate = event.type
                self.align_to_face(self.get_edge_idx(self.counter),
                                   self.axis_rotate,
                                   self.flip)
                self.report({"INFO"}, event.type)

        elif event.type == "WHEELDOWNMOUSE":
                if self.counter > 1:
                    self.counter -= 1

                self.align_to_face(self.get_edge_idx(self.counter),
                                   self.axis_rotate,
                                   self.flip)
                self.report({"INFO"}, event.type)

        elif event.type == "WHEELUPMOUSE":
                self.counter += 1
                self.align_to_face(self.get_edge_idx(self.counter),
                                   self.axis_rotate,
                                   self.flip)
                self.report({"INFO"}, event.type)

        elif event.type == 'F' and event.value == "PRESS":
                self.flip = not self.flip
                self.align_to_face(self.get_edge_idx(self.counter),
                                   self.axis_rotate,
                                   self.flip)
                self.report({"INFO"}, event.type)

        elif event.type in {"LEFTMOUSE", "SPACE"}:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, "WINDOW")
            return {"FINISHED"}

        elif event.type in {"RIGHTMOUSE", "ESC"}:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, "WINDOW")
            bpy.context.object.location = self.loc_start
            bpy.context.object.rotation_euler = self.rot_start
            return {"CANCELLED"}

        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        if context.object and context.area.type == "VIEW_3D":
            # Initialize axis and assign starting values for object's location
            self.axis_move = 'Z'
            self.axis_rotate = 'Z'
            self.flip = True
            self.loc_start = bpy.context.object.location
            self.rot_start = bpy.context.object.rotation_euler
            self.loc = self.loc_start
            self.rot = self.rot_start
            self.edge_idx = 1
            self.counter = 0

            self.align_to_face(self.edge_idx, self.axis_rotate, self.flip)

            # Add drawing handler for text overlay rendering
            args = (self, context)
            self._handle = bpy.types.SpaceView3D.draw_handler_add(
                            draw_callback_px,
                            args,
                            'WINDOW',
                            'POST_PIXEL')

            # Add modal handler to enter modal mode
            context.window_manager.modal_handler_add(self)
            return {"RUNNING_MODAL"}
        else:
            self.report({"WARNING"}, "No active object, could not finish")
            return {"CANCELLED"}
