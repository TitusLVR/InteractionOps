import bpy
import blf
from bpy.props import (IntProperty, 
                       FloatProperty, 
                       BoolProperty, 
                       StringProperty, 
                       FloatVectorProperty)
import bmesh
import math
from mathutils import Vector, Matrix, Euler

def draw_callback_px(self, context):
        _location = "Location: x = {0:.4f}, y = {1:.4f}, z = {2:.4f}"
        _axis_move = "Move Axis: " + str(self.axis_move)

        # Font
        font_id = 0
        blf.size(font_id, 20, 72)

        # Active axis text overlay
        blf.position(font_id, 15, 90, 0)
        blf.draw(font_id, _axis_move)

        # Location text overlay
        blf.position(font_id, 15, 60, 0)
        blf.draw(font_id, _location.format(self.loc[0], self.loc[1], self.loc[2]))


class AlignObjectToFace(bpy.types.Operator):
    """ Align object to selected face """
    bl_idname = "iops.align_object_to_face"
    bl_label = "iOps Align object to face"
    bl_options = {"REGISTER","UNDO"}

    axis_align  : StringProperty()
    axis_move   : StringProperty()
    loc         : FloatVectorProperty()
    loc_start   : FloatVectorProperty()

    @classmethod
    def poll(self,context):
        return len(context.selected_objects) > 0 

    def move(self, axis_move, step):
        if axis_move == 'X':
            self.loc[0] += step
        elif axis_move == 'Y':
            self.loc[1] += step
        elif axis_move == 'Z':
            self.loc[2] += step
        else: pass  
           
    def align_to_face(self, context):   
        """ Takes face normal and aligns it to global axis.
            Uses one of the face edges to further align it to another axis.""" 

        obj = context.active_object
        mx = obj.matrix_world
        loc = mx.to_translation()           #  Store location   
        polymesh = obj.data            
        bm = bmesh.from_edit_mesh(polymesh)    

        # Get active face
        face = bm.faces.active

        # Build vectors for new matrix               
        n = face.normal                # Z
        t = face.calc_tangent_edge()   # Y
        c = t.cross(n)                 # X

        # Assemble new matrix    
        mx_rot = Matrix((c, t, n)).transposed().to_4x4() 
        obj.matrix_world = mx_rot.inverted()
        obj.location = loc 

    def modal(self, context, event):  
        context.area.tag_redraw()
        # Moving object while SHIFT is pressed for testing purpose     
        # ---------------------------------------------------------
        if event.shift:
            if event.type in {'X','Y','Z'} and event.value == "PRESS":
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

        if event.type in {'X','Y','Z'} and event.value == "PRESS":
                self.axis_move = event.type
                print(event.type,"pressed")

        elif event.type == "WHEELDOWNMOUSE":
                print(event.type)

        elif event.type == "WHEELUPMOUSE":
                print(event.type)

        elif event.type in {"LEFTMOUSE", "SPACE"}:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, "WINDOW")
            return {"FINISHED"}

        elif event.type in {"RIGHTMOUSE", "ESC"}:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, "WINDOW")
            bpy.context.object.location = self.loc_start
            return {"CANCELLED"}

        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        if context.object and context.area.type == "VIEW_3D":    
            # Initialize axis and assign starting values for object's location     
            self.axis_move = 'Z'                                  
            self.loc_start = bpy.context.object.location  
            self.loc = self.loc_start

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

