import bpy
import gpu
from gpu_extras.batch import batch_for_shader
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


def draw_ui(self, context):       
    _points = "Number of cuts: {0}" 
    # Font
    font = 0
    blf.size(font, 20, 72)   
    # Curve subdivide points
    blf.position(font, 60, 30, 0),
    blf.draw(font, _points.format(self.points_num))

# TODO SORT THIS OUT ##############################


def draw_curve_pts(self, context):
    coords = self.get_curve_pts()
    shader = gpu.shader.from_builtin('3D_UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'LINES', {"pos": coords})
    shader.bind()
    shader.uniform_float("color", (1, 1, 0, 1))
    batch.draw(shader)

##################################################

class IOPS_OT_CurveSubdivide(bpy.types.Operator):
    """ Subdivide Curve """
    bl_idname = "iops.curve_subdivide"
    bl_label = "iOps curve subdivide"
    bl_options = {"REGISTER", "UNDO"}
    
    points_num : IntProperty(
    name = "Number of cuts",
    description = "",            
    default = 1
    )    

    @classmethod
    def poll(self, context):
         return (context.active_object.type == "CURVE" and
                context.active_object.mode == "EDIT")

    def execute(self, context):
        self.subdivide(self.points_num)
        return {"FINISHED"}        
        
    def subdivide(self, points):        
        obj = bpy.context.active_object
        self.points_num = points
        bpy.ops.curve.subdivide(number_cuts=self.points_num)

    def get_curve_pts(self):
        obj = bpy.context.active_object
        selected_pts = []
        # Store selected curve points
        if obj.type == "CURVE":
            for s in obj.data.splines:
                for b in s.bezier_points:
                    if b.select_control_point:
                        selected_pts.append(b.co)       
        return selected_pts

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
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_ui, "WINDOW")            
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_curve, "WINDOW")            
            return {"FINISHED"}

        elif event.type in {"RIGHTMOUSE", "ESC"}:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_ui, "WINDOW")           
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_curve, "WINDOW")           
            return {"CANCELLED"}

        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        if context.object and context.area.type == "VIEW_3D":                       
            self.points_num = 1

            # Add drawing handler for text overlay rendering
            args = (self, context)
            self._handle_ui = bpy.types.SpaceView3D.draw_handler_add(
                            draw_ui,
                            args,
                            'WINDOW',
                            'POST_PIXEL')
        
            self._handle_curve = bpy.types.SpaceView3D.draw_handler_add(
                            draw_curve_pts,
                            args,
                            'WINDOW',
                            'POST_VIEW')

            # Add modal handler to enter modal mode
            context.window_manager.modal_handler_add(self)
            return {"RUNNING_MODAL"}
        else:
            self.report({"WARNING"}, "No active object, could not finish")
            return {"CANCELLED"}
