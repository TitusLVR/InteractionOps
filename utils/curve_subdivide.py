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
        _points = "Number of cuts: {0}" 
        # Font
        font = 0
        blf.size(font, 20, 72)   
        # Curve subdivide points
        blf.position(font, 60, 30, 0),
        blf.draw(font, _points.format(self.points_num))


class CurveSubdivide (bpy.types.Operator):
    """ Align object to selected face """
    bl_idname = "iops.curve_subdivide"
    bl_label = "iOps curve subdivide"
    bl_options = {"REGISTER", "UNDO"}

    
    points_num : IntProperty(
    name = "Number of cuts",
    description = "Max value for X axis",            
    default = 1    
    )    

    @classmethod
    def poll(self, context):
         return (context.active_object.type == 'CURVE')
     
    def execute(self, context):
        
        self.subdivide(self.points_num)
        return {"FINISHED"}        
          
        
    def subdivide(self, points):
        """Number of cuts add"""        
        obj = bpy.context.active_object
        self.points_num = points
        bpy.ops.curve.subdivide(number_cuts=self.points_num)
        #print (self.points_num)  

    def modal(self, context, event):
        context.area.tag_redraw()

        if event.type in {'MIDDLEMOUSE'}:
            # Allow navigation
            return {'PASS_THROUGH'}  

        elif event.type == "WHEELDOWNMOUSE":
                if self.points_num > 1:
                    self.points_num -= 1
                self.report({"INFO"}, event.type)

        elif event.type == "WHEELUPMOUSE":
                self.points_num += 1
                self.report({"INFO"}, event.type)                     

        elif event.type in {"LEFTMOUSE", "SPACE"} and event.value == "PRESS":
            self.execute(context)            
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, "WINDOW")            
            return {"FINISHED"}

        elif event.type in {"RIGHTMOUSE", "ESC"}:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, "WINDOW")           
            return {"CANCELLED"}

        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        if context.object and context.area.type == "VIEW_3D":                       
            self.points_num = 1
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
        
def register():
    bpy.utils.register_class(CurveSubdivide)


def unregister():
    bpy.utils.unregister_class(CurveSubdivide)


if __name__ == "__main__":
    register()

