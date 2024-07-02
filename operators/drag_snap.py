import bpy
import gpu
from math import sin, cos, pi
import numpy as np
from mathutils import Vector
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from bpy_extras.view3d_utils import (
    location_3d_to_region_2d
)


SNAP_DIST_SQ = 30**2  # Pixels Squared Tolerance


# get circle vertices on pos 2D by segments
def generate_circle_verts(position, radius, segments):
    coords = []
    coords.append(position)
    mul = (1.0 / segments) * (pi * 2)
    for i in range(segments):
        coord = (
            sin(i * mul) * radius + position[0],
            cos(i * mul) * radius + position[1],
        )
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

    radius = (
        bpy.context.preferences.addons["InteractionOps"].preferences.vo_cage_ap_size / 1.5
    )
    segments = 12
    # create vertices
    coords = generate_circle_verts(point, radius, segments)
    # create triangles
    triangles = generate_circle_tris(segments, 0)
    # set shader and draw
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    batch = batch_for_shader(shader, "TRIS", {"pos": coords}, indices=triangles)
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def draw_snap_line(self, context):
    if not self.source[0] or not self.target[0]:
        return
    prefs = context.preferences.addons["InteractionOps"].preferences
    # color = prefs.vo_cage_color
    line_thickness = prefs.drag_snap_line_thickness
    color = (*bpy.context.preferences.themes[0].view_3d.empty, 0.5)
    shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    batch = batch_for_shader(
        shader, "LINES", {"pos": (self.source[0], self.preview[0])}
    )
    shader.bind()
    # color and thickness
    region = bpy.context.region
    shader.uniform_float("viewportSize", (region.width, region.height))
    shader.uniform_float("lineWidth", line_thickness)
    shader.uniform_float("color", color)
    
    batch.draw(shader)


def draw_snap_points(self, context):
    draw_point(self.source[1])
    draw_point(self.preview[1])


class IOPS_OT_DragSnap(bpy.types.Operator):
    """Quick drag & snap point to point"""

    bl_idname = "iops.object_drag_snap"
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

    @classmethod
    def poll(cls, context):
        return (
            context.area.type == "VIEW_3D"
            and context.mode == "OBJECT"
            and len(context.view_layer.objects.selected) != 0
        )

    def clear_draw_handlers(self):
        for handler in self.sd_handlers:
            bpy.types.SpaceView3D.draw_handler_remove(handler, "WINDOW")

    def get_vector_length(self, vector):
        length = np.linalg.norm(vector)
        return length

    def execute(self, context):
        # Double Click to quick snap 3d cursor
        if self.target[0] == self.source[0]:
            context.scene.cursor.location = self.target[0]
        else:
            bpy.ops.transform.translate(value=self.snap(), orient_type="GLOBAL")

        try:
            self.clear_draw_handlers()
        except ValueError:
            pass
        return {"FINISHED"}

    def snap(self):
        if not self.target[0]:
            return Vector((0, 0, 0))
        return self.target[0] - self.source[0]

    def update_distances(self, context, event):
        scene = context.scene
        region = context.region
        mouse_pos = Vector((event.mouse_region_x, event.mouse_region_y))
        rv3d = context.region_data
        view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, mouse_pos)
        ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, mouse_pos)
        depsgraph = context.evaluated_depsgraph_get()

        # if bpy.app.version[0] == 2 and bpy.app.version[1] > 90:
        #     hit, _ , _ , _ , hit_obj, _ = scene.ray_cast(view_layer.depsgraph, ray_origin, view_vector, distance=1.70141e+38)
        # elif bpy.app.version[0] == 2 and bpy.app.version[1] <= 90:
        #     hit, _ , _ , _ , hit_obj, _ = scene.ray_cast(view_layer, ray_origin, view_vector, distance=1.70141e+38)
        # elif bpy.app.version[0] == 3 and bpy.app.version[1] >= 0:
        hit, _, _, _, hit_obj, _ = scene.ray_cast(
            depsgraph, ray_origin, view_vector, distance=1.70141e38
        )

        self.nearest = None, None
        min_dist = float("inf")
        # if hasattr(hit_obj, "type") and hasattr(hit_obj, "name"):
        #     print(hit_obj.type, hit_obj.name, hit_obj.location)

        # if hit and hit_obj.type == 'MESH':
        if hit and hit_obj.type is not None:
            depsgraph = context.evaluated_depsgraph_get()
            # for object_instance in depsgraph.object_instances:
            #     # This is an object which is being instanced.
            #     obj = object_instance.object
            #     # `is_instance` denotes whether the object is coming from instances (as an opposite of
            #     # being an emitting object. )
            #     if not object_instance.is_instance:
            #         print(f"Object {obj.name} at {object_instance.matrix_world}")
            #     else:
            #         # Instanced will additionally have fields like uv, random_id and others which are
            #         # specific for instances. See Python API for DepsgraphObjectInstance for details,
            #         print(f"Instance of {obj.name} at {object_instance.matrix_world}")

            for v in hit_obj.data.vertices:
                v_co3d = hit_obj.matrix_world @ v.co
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
        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            # allow navigation
            return {"PASS_THROUGH"}

        elif event.type == "MOUSEMOVE":
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
                    self.report({"INFO"}, "DISTANCE COPIED TO BUFFER: " + str(DISTANCE))
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
                self.report({"WARNING"}, "WRONG SOURCE OR TARGET")
                self.clear_draw_handlers()
                return {"CANCELLED"}
            elif not self.target[0]:
                self.source = self.nearest
                self.report({"INFO"}, "Click target now...")
            else:
                self.execute(context)
                return {"FINISHED"}

        if event.type == "LEFTMOUSE":
            self.lmb = event.value == "PRESS"
            if self.lmb:
                self.source = self.nearest

        elif event.type in {"RIGHTMOUSE", "ESC"}:
            self.clear_draw_handlers()
            self.report({"INFO"}, "Drag snap - cancelled")
            return {"CANCELLED"}

        # return {'PASS_THROUGH'}
        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        self.report({"INFO"}, "Snap Drag started: Pick source")
        if context.space_data.type == "VIEW_3D":
            args = (self, context)
            self.active = context.view_layer.objects.active
            self.update_distances(context, event)
            self.lmb = False

            # Add draw handlers
            self.handle_snap_line = bpy.types.SpaceView3D.draw_handler_add(
                draw_snap_line, args, "WINDOW", "POST_VIEW"
            )
            self.handle_snap_points = bpy.types.SpaceView3D.draw_handler_add(
                draw_snap_points, args, "WINDOW", "POST_PIXEL"
            )
            self.sd_handlers = [self.handle_snap_line, self.handle_snap_points]
            # Add modal handler to enter modal mode
            context.window_manager.modal_handler_add(self)
            return {"RUNNING_MODAL"}
        else:
            self.report({"WARNING"}, "Active space must be a View3d")
            return {"CANCELLED"}
