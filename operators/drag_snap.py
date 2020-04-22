import bpy
import blf
import gpu
import bmesh
from math import sin, cos, pi
import numpy as np
from mathutils import Vector, Matrix
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from bpy_extras.view3d_utils import region_2d_to_vector_3d, region_2d_to_origin_3d, location_3d_to_region_2d


SNAP_DIST_SQ = 20**2 #Pixels Squared Tolerance


# get circle vertices on pos 2D by segments
def generate_circle_verts(position, radius, segments):
    coords = []
    coords.append(position)
    mul = (1.0 / segments) * (pi * 2)
    for i in range(segments):
        coord = (sin(i * mul) * radius + position[0], cos(i * mul) * radius + position[1])
        coords.append(coord)
    return coords


# get circle triangles by segments
def generate_circle_tris(segments, startID):
    triangles = []
    tri = startID
    for i in range(segments - 1):
        tricomp = (startID, tri + 1, tri + 2)
        triangles.append(tricomp)
        tri += 1
    tricomp = (startID, tri, startID + 1)
    triangles.append(tricomp)
    return triangles


def draw_point(point):
    if point is None:
        return
    color = bpy.context.preferences.themes[0].view_3d.editmesh_active

    radius = bpy.context.preferences.addons['InteractionOps'].preferences.vo_cage_ap_size / 2
    segments = 12
    # create vertices
    coords = generate_circle_verts(point, radius, segments)
    # create triangles
    triangles = generate_circle_tris(segments, 0)
    # set shader and draw
    shader = gpu.shader.from_builtin('2D_UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'TRIS', {"pos": coords}, indices=triangles)
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)
   


def draw_snap_line(self, context):
    if not self.source[0] or not self.target[0]:
        return
    
    color = (*bpy.context.preferences.themes[0].view_3d.empty, 0.5)
    shader = gpu.shader.from_builtin("3D_UNIFORM_COLOR")
    batch = batch_for_shader(shader, "LINES", {"pos": (self.source[0], self.preview[0])})
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)
   


def draw_snap_points(self, context):
    draw_point(self.source[1])
    draw_point(self.preview[1])


class IOPS_OT_DragSnap(bpy.types.Operator):
    """ Quick drag & snap point to point """
    bl_idname = "iops.drag_snap"
    bl_label = "IOPS Drag Snap"
    bl_options = {"REGISTER", "UNDO"}

    source = None, None
    target = None, None
    preview = None, None
    active = None
    lmb = False

    nearest = None, None

    # Handlers list
    sd_handlers = []

    def clear_draw_handlers(self):
        for handler in self.sd_handlers:
            bpy.types.SpaceView3D.draw_handler_remove(handler, "WINDOW")
    
    def get_vector_length(self, vector):
        length = np.linalg.norm(vector)
        return length

    def execute(self, context):   
        bpy.ops.transform.translate(value=self.snap(), orient_type='GLOBAL')
        try:
            self.clear_draw_handlers()
        except ValueError:
            pass    
        return {"FINISHED"}

    def snap(self):
        if not self.target[0]:
            return Vector((0,0,0))
        return self.target[0] - self.source[0]

    def update_distances(self, context, event):
        mouse_pos = Vector((event.mouse_region_x, event.mouse_region_y))
        rv3d = context.region_data

        self.nearest = None, None
        min_dist = float('inf')

        for o in context.visible_objects:
            if o.type != 'MESH':
                continue

            for v in o.data.vertices:
                v_co3d = o.matrix_world @ v.co
                v_co2d = location_3d_to_region_2d(context.region, rv3d, v_co3d)

                if v_co2d is not None:
                    d_squared = (mouse_pos - v_co2d).length_squared
                    if d_squared > SNAP_DIST_SQ:
                        continue
                    if d_squared < min_dist:
                        min_dist = d_squared
                        self.nearest = v_co3d, v_co2d
        return self.nearest

    def modal(self, context, event):
        context.area.tag_redraw()
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            # allow navigation
            return {'PASS_THROUGH'}

        elif event.type == 'MOUSEMOVE':
            self.update_distances(context, event)
            self.preview = self.nearest
            if self.source[0]:
                self.target = self.nearest

        elif event.type in {"LEFTMOUSE"} and event.value == "PRESS":
            if self.source[0]:
                if event.ctrl:
                    DISTANCE = self.get_vector_length(self.snap())
                    # DISTANCE = np.round(DISTANCE, 5) # ACCEPT THE FATE, DON'T DO THIS
                    bpy.context.window_manager.clipboard = str(DISTANCE)
                    self.report({'INFO'}, "DISTANCE COPIED TO BUFFER: " + str(DISTANCE))
                    try:
                        self.clear_draw_handlers()
                    except ValueError:
                        pass    
                    return {"FINISHED"}    
                else:
                    self.target = self.nearest
                    self.execute(context)
                return {"FINISHED"}
            self.source = self.nearest
            self.lmb = True
        

        elif event.type in {"LEFTMOUSE"} and event.value == "RELEASE":
            if not self.source[0]:
                self.report({'WARNING'}, "WRONG SOURCE OR TARGET")
                self.clear_draw_handlers()
                return {'CANCELLED'}
            elif not self.target[0]:
                self.source = self.nearest
                self.report({'INFO'}, "Click target now...")
            else:    
                self.execute(context)
                return {"FINISHED"}
        
        if event.type == 'LEFTMOUSE':
            self.lmb = event.value == "PRESS"
            if self.lmb:
                self.source = self.nearest

        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            self.clear_draw_handlers()
            return {'CANCELLED'}

        # return {'PASS_THROUGH'}
        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        self.report({'INFO'}, "Snap Drag started: Pick source")
        if context.space_data.type == 'VIEW_3D':
            args = (self, context)
            self.active = context.view_layer.objects.active
            self.update_distances(context, event)
            self.lmb = False
            
            # Add draw handlers
            self.handle_snap_line = bpy.types.SpaceView3D.draw_handler_add(draw_snap_line, args, 'WINDOW', 'POST_VIEW')
            self.handle_snap_points = bpy.types.SpaceView3D.draw_handler_add(draw_snap_points, args, 'WINDOW', 'POST_PIXEL')
            self.sd_handlers = [self.handle_snap_line, self.handle_snap_points]
            # Add modal handler to enter modal mode
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        else:
            self.report({'WARNING'}, "Active space must be a View3d")
            return {'CANCELLED'}
