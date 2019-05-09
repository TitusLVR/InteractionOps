import bpy
import gpu
import bmesh
import numpy
import math
from math import radians, degrees
from mathutils import Vector, Matrix, Euler
from math import sin, cos, pi
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from bpy_extras.view3d_utils import region_2d_to_vector_3d, region_2d_to_origin_3d, location_3d_to_region_2d


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
    for i in range(segments-1):
        tricomp = (startID, tri + 1, tri + 2)
        triangles.append(tricomp)
        tri += 1
    tricomp = (startID, tri, startID+1)
    triangles.append(tricomp)
    return triangles


# draw a circle on scene
def draw_circle_fill_2d(self, context):
    point = self.target
    if point != (0, 0):
        position = point
        color = (1, 0, 0, 1)
        radius = 6
        segments = 12
        # create vertices
        coords = generate_circle_verts(position, radius, segments)
        # create triangles
        triangles = generate_circle_tris(segments, 0)
        # set shader and draw
        shader = gpu.shader.from_builtin('2D_UNIFORM_COLOR')
        batch = batch_for_shader(shader, 'TRIS', {"pos": coords}, indices = triangles)
        shader.bind()
        shader.uniform_float("color", color)
        batch.draw(shader)


# draw multiple circle in one batch on screen
def draw_multicircles_fill_2d_bbox(self, context):
    positions = (self.object_bbox(context))[0]
    if positions is not None:
        color = (0.873, 0.623, 0.15, 0.1)
        radius = 3
        segments = 12
        coords = []
        triangles = []
        # create vertices
        for center in positions:
            actCoords = generate_circle_verts(center, radius, segments)
            coords.extend(actCoords)
        # create triangles
        for tris in range(len(positions)):
            actTris = generate_circle_tris(segments, tris*(segments+1))
            triangles.extend(actTris)
        # set shader and draw
        shader = gpu.shader.from_builtin('2D_UNIFORM_COLOR')
        batch = batch_for_shader(shader, 'TRIS', {"pos": coords}, indices = triangles)
        shader.bind()
        shader.uniform_float("color", color)
        batch.draw(shader)


def draw_bbox_lines(self, context):
    coords = (self.object_bbox(context))[1]
    if len(coords) != 0:
        if len(coords) == 8:
            indices = (
                (0, 1), (1, 2), (2, 3), (3, 0),
                (4, 5), (5, 6), (6, 7), (7, 4),
                (0, 4), (1, 5), (2, 6), (3, 7)
                )
        elif len(coords) > 8:
            indices = (
                # Bbox                       
                (0, 1), (1, 2), (2, 3), (0, 3),  # X-                      
                (4, 5), (5, 6), (6, 7), (4, 7),   # X+                        
                (0, 4),  # Y- BTM                        
                (1, 5),  # Y- UP                        
                (3, 7),  # Y-BTM                        
                (2, 6),  # Y+UP
                # SUBD                        
                (8, 10), (9, 11),  # X-                        
                (12, 14), (13, 15),  # X+                        
                (16, 17), (8, 12),  # Y-                        
                (10, 14), (18, 19),  # Y+                        
                (11, 15), (16, 19),  # Z-                        
                (17, 18), (9, 13),  # Z+
                # Center
                (20, 23),  # +X
                (20, 21),  # -X
                (20, 27),  # +Y
                (20, 25),  # -Y
                (20, 31),  # +Z
                (20, 29),  # -Z
                )
        else:
            indices = ()

        shader = gpu.shader.from_builtin('3D_UNIFORM_COLOR')
        batch = batch_for_shader(shader, 'LINES', {"pos": coords}, indices = indices)
        shader.bind()
        shader.uniform_float("color", (0.573, 0.323, 0.15, 1))
        batch.draw(shader)


class IOPS_OP_PlaceOrigin(bpy.types.Operator):
    """Visual origin placing helper tool"""
    bl_idname = "iops.visual_origin"
    bl_label = "Visual origin"
    bl_options = {"REGISTER", "UNDO"}

    mouse_pos = (0, 0)

    # RayCastResults
    result = False
    result_obj = None

    # BBoxResults
    pos_batch = []
    pos_batch_3d = []

    # DrawCalculations
    batch_idx = None
    target = (0, 0)

    @classmethod
    def poll(self, context):
        return (context.area.type == "VIEW_3D"                                
                and context.view_layer.objects.selected is not None)

    def place_origin(self, context):
        objs = context.view_layer.objects.selected
        pos = self.pos_batch_3d[self.batch_idx]
        context.scene.cursor.location = pos
        for ob in objs:
            context.view_layer.objects.active = ob
            bpy.ops.object.origin_set(type="ORIGIN_CURSOR")

    # Calculate distance between raycasts
    def calc_distance(self, context):
        mouse_pos = self.mouse_pos
        pos_batch = self.pos_batch
        if len(pos_batch) != 0:
            act_dist = numpy.linalg.norm(pos_batch[0]-Vector(mouse_pos))
            act_id = 0
            counter = 1
            itertargets = iter(self.pos_batch)
            next(itertargets)
            for pos in itertargets:
                dist = numpy.linalg.norm(pos-Vector(mouse_pos))
                if dist < act_dist:
                    act_id = counter
                    act_dist = dist
                counter += 1
            self.batch_idx = act_id
            self.target = pos_batch[act_id]

    def scene_ray_cast(self, context):
        # get the context arguments
        scene = context.scene
        region = context.region
        rv3d = context.region_data
        coord = self.mouse_pos
        view_layer = context.view_layer

        # get the ray from the viewport and mouse
        view_vector = region_2d_to_vector_3d(region, rv3d, coord)
        ray_origin = region_2d_to_origin_3d(region, rv3d, coord)

        ray_target = ray_origin + view_vector

        result, location, normal, index, obj, matrix = scene.ray_cast(view_layer, ray_origin, view_vector, distance=1.70141e+38)

        if result:
            self.result = result
            self.result_obj = obj
            return result, obj
        else:
            if self.result_obj is not None:
                pass
            else:
                obj = None
            return result, obj

    def object_bbox(self, context):
        scene = context.scene
        region = context.region
        rv3d = context.region_data
        coord = self.mouse_pos
        view_layer = context.view_layer
        res = self.result
        obj = self.result_obj
        context.view_layer.objects.active = obj
        verts_pos = []
        bbox_batch =[]
        bbox_batch_3d = []
        face_batch = []
        face_batch_3d = []
        if obj is not None:
            # verts = mesh.polygons[index].vertices
            matrix = obj.matrix_world
            matrix_trans = matrix.transposed()

            bbox = obj.bound_box
            bbox_verts_3d = []
            if len(bbox) != 0:
                SubD_Vert_POS = []
                bbox_Edges = (
                    (0, 1), (1, 2), (2, 3), (0, 3),
                    (4, 5), (5, 6), (6, 7), (4, 7),
                    (0, 4), (1, 5), (2, 6), (3, 7), (0, 6))
                bbox_SubD_Edges = (
                    (8, 10), (9, 11), (12, 14), (13, 15),
                    (16, 17), (8, 12), (10, 14), (18, 19),
                    (11, 15), (16, 19), (17, 18), (9, 13))
                # BBox
                for v in bbox:
                    pos = Vector(v) @  matrix_trans
                    bbox_verts_3d.append(pos)
                # BBox Edge subD
                for e in bbox_Edges:
                    vert1 = Vector(bbox[(e[0])])
                    vert2 = Vector(bbox[(e[1])])
                    vertmid = (vert1+vert2)/2
                    pos = Vector(vertmid) @  matrix_trans
                    bbox_verts_3d.append(pos)
                for e in bbox_SubD_Edges:
                    vert1 = Vector(bbox_verts_3d[(e[0])])
                    vert2 = Vector(bbox_verts_3d[(e[1])])
                    vertmid = (vert1+vert2)/2
                    pos = Vector(vertmid)
                    bbox_verts_3d.append(pos)

                # BBOX COLLECT
                for v in bbox_verts_3d:
                    pos3D = v
                    pos2D = location_3d_to_region_2d(region, rv3d, pos3D, default = None)
                    bbox_batch_3d.append(pos3D)
                    bbox_batch.append(pos2D)

            self.pos_batch = bbox_batch
            self.pos_batch_3d = bbox_batch_3d
            return [bbox_batch, bbox_batch_3d]
        else:
            return [bbox_batch, bbox_batch_3d]

    def modal(self, context, event):
        context.area.tag_redraw()
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            # allow navigation
            return {'PASS_THROUGH'}
        elif event.type == 'MOUSEMOVE':
            self.mouse_pos = event.mouse_region_x, event.mouse_region_y
            self.scene_ray_cast(context)
            self.object_bbox(context)
            self.calc_distance(context)
#            print ("VERT POS",self.getFaceVertPos(context))
#            print ("MOUSE POS",self.mouse_pos)
        elif event.type in {"LEFTMOUSE", "SPACE"}:
            self.place_origin(context)
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_bbox_lines, "WINDOW")
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_bbox_points, 'WINDOW')
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_bbox_act_point, 'WINDOW')
            return {"FINISHED"}
        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            self.mouse_pos = [0, 0]
            self.result = False
            self.result_obj = None
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_bbox_lines, "WINDOW")
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_bbox_points, 'WINDOW')
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_bbox_act_point, 'WINDOW')
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        if context.space_data.type == 'VIEW_3D':
            args = (self, context)
            self.mouse_pos = event.mouse_region_x, event.mouse_region_y
            self.result, self.result_obj = self.scene_ray_cast(context)
            # Add draw handlers
            self._handle_bbox_lines = bpy.types.SpaceView3D.draw_handler_add(draw_bbox_lines, args, 'WINDOW', 'POST_VIEW')
            self._handle_bbox_points = bpy.types.SpaceView3D.draw_handler_add(draw_multicircles_fill_2d_bbox, args, 'WINDOW', 'POST_PIXEL')
            self._handle_bbox_act_point = bpy.types.SpaceView3D.draw_handler_add(draw_circle_fill_2d, args, 'WINDOW', 'POST_PIXEL')

            # Add modal handler to enter modal mode
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        else:
            self.report({'WARNING'}, "Active space must be a View3d")
            return {'CANCELLED'}



