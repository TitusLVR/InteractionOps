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


def draw_curve_pts(self, context):
    coords = self.get_curve_pts() # <- sequence
    shader = gpu.shader.from_builtin("3D_UNIFORM_COLOR")
    batch = batch_for_shader(shader, "POINTS", {"pos": coords})
    shader.bind()
    shader.uniform_float("color", (1, 0, 0, 1))
    batch.draw(shader)
    # pass

def draw_ui(self, context):
    _points = "Number of cuts: {0}"
    _debug = "Debug: {0}"
    debug = self.pairs
    # Font
    font = 0
    blf.size(font, 20, 72)
    # Curve subdivide points
    blf.position(font, 60, 30, 0),
    blf.draw(font, _points.format(self.points_num))


class IOPS_OT_CurveSubdivide(bpy.types.Operator):
    """ Subdivide Curve """
    bl_idname = "iops.curve_subdivide"
    bl_label = "CURVE: Subdivide"
    bl_options = {"REGISTER", "UNDO"}

    pairs = []

    points_num : IntProperty(
    name = "Number of cuts",
    description = "",
    default = 1
    )

    @classmethod
    def poll(self, context):
         return (context.active_object.type == "CURVE" and context.active_object.mode == "EDIT")

    def execute(self, context):
        self.subdivide(self.points_num)
        return {"FINISHED"}

    def subdivide(self, points):
        obj = bpy.context.active_object
        self.points_num = points
        bpy.ops.curve.subdivide(number_cuts=self.points_num)

    def get_curve_pts(self):
        obj = bpy.context.active_object
        pts = []
        sequence = []

        # Store selected curve points
        if obj.type == "CURVE":
            for s in obj.data.splines:
                for b in s.bezier_points:
                    if b.select_control_point:
                        pts.append(b)

        # P = (0.5)**3 * A + 3(0.5)**3 * Ha + 3(0.5) ** 3 * Hb + 0.5**3 * B

        for idx in range(len(pts) - 1):
            A   = pts[idx].co @ obj.matrix_world + obj.location
            Ahl = pts[idx].handle_left @ obj.matrix_world + obj.location 
            Ahr = pts[idx].handle_right @ obj.matrix_world + obj.location  # Ha
    
            B   = pts[idx+1].co @ obj.matrix_world + obj.location
            Bhl = pts[idx+1].handle_left @ obj.matrix_world + obj.location  # Hb
            Bhr = pts[idx+1].handle_right @ obj.matrix_world + obj.location    

            for ip in range(self.points_num):
                p = 1 / (self.points_num + 1) * (ip + 1)
                point = ((1 - p) ** 3 * A 
                        + 3 * (1 - p) ** 2 * p * Ahr 
                        + 3 * (1 - p) * p ** 2 * Bhl 
                        + p ** 3 * B)
                sequence.append(point)
        return sequence

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
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_curve, "WINDOW")
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_ui, "WINDOW")
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

            self.pairs = self.get_curve_pts()
            print("----------------------------------------")
            print(self.pairs)

            # Add modal handler to enter modal mode
            context.window_manager.modal_handler_add(self)
            return {"RUNNING_MODAL"}
        else:
            self.report({"WARNING"}, "No active object, could not finish")
            return {"CANCELLED"}