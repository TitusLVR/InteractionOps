import bpy
import blf
import gpu
import bmesh
from math import sin, cos, pi
import numpy as np
from mathutils import Vector
from mathutils.kdtree import KDTree
from gpu_extras.batch import batch_for_shader


# SNAP_DIST_SQ = 30**2 #Pixels Squared Tolerance


def draw_iops_text(self, context, _uidpi, _uifactor):
    prefs = bpy.context.preferences.addons["InteractionOps"].preferences
    tColor = prefs.text_color
    tKColor = prefs.text_color_key
    tCSize = prefs.text_size
    tCPosX = prefs.text_pos_x
    tCPosY = prefs.text_pos_y
    tShadow = prefs.text_shadow_toggle
    tSColor = prefs.text_shadow_color
    tSBlur = prefs.text_shadow_blur
    tSPosX = prefs.text_shadow_pos_x
    tSPosY = prefs.text_shadow_pos_y

    iops_text = (
        ("Move selected to 2D Cursor (highlighted)", "1"),
        ("Move selected to 2D Cursor (nearest)", "2"),
        ("Move 2D Cursor to Highlighted", "4"),
        ("Move only by X", "X"),
        ("Move only by Y", "Y"),
    )

    # FontID
    font = 0
    blf.color(font, tColor[0], tColor[1], tColor[2], tColor[3])
    blf.size(font, tCSize)
    if tShadow:
        blf.enable(font, blf.SHADOW)
        blf.shadow(font, int(tSBlur), tSColor[0], tSColor[1], tSColor[2], tSColor[3])
        blf.shadow_offset(font, tSPosX, tSPosY)
    else:
        blf.disable(0, blf.SHADOW)

    textsize = tCSize
    # get leftbottom corner
    offset = tCPosY
    columnoffs = (textsize * 21) * _uifactor
    for line in reversed(iops_text):
        blf.color(font, tColor[0], tColor[1], tColor[2], tColor[3])
        blf.position(font, tCPosX * _uifactor, offset, 0)
        blf.draw(font, line[0])

        blf.color(font, tKColor[0], tKColor[1], tKColor[2], tKColor[3])
        textdim = blf.dimensions(0, line[1])
        coloffset = columnoffs - textdim[0] + tCPosX
        blf.position(0, coloffset, offset, 0)
        blf.draw(font, line[1])
        offset += (tCSize + 5) * _uifactor


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


def draw_point(point, context):
    if point is None:
        return

    point = context.region.view2d.view_to_region(point.x, point.y)
    color = bpy.context.preferences.themes[0].view_3d.editmesh_active

    radius = bpy.context.preferences.addons[
        "InteractionOps"
    ].preferences.vo_cage_ap_size
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
    if not self.source or not self.target:
        return

    prefs = context.preferences.addons["InteractionOps"].preferences
    start = context.region.view2d.view_to_region(self.source[0], self.source[1])
    end = context.region.view2d.view_to_region(self.preview[0], self.preview[1])

    line_thickness = prefs.drag_snap_line_thickness
    color = (*bpy.context.preferences.themes[0].view_3d.empty, 0.5)
    shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    batch = batch_for_shader(shader, "LINE_STRIP", {"pos": (start, end)})
    shader.bind()
    # color and thickness
    region = bpy.context.region
    shader.uniform_float("viewportSize", (region.width, region.height))
    shader.uniform_float("lineWidth", line_thickness)
    shader.uniform_float("color", color)
    batch.draw(shader)


def draw_snap_points(self, context):
    draw_point(self.source, context)
    draw_point(self.preview, context)


class IOPS_OT_DragSnapUV(bpy.types.Operator):
    """Quick drag & snap uv to another uv"""

    bl_idname = "iops.uv_drag_snap_uv"
    bl_label = "IOPS Drag Snap UV"
    bl_options = {"REGISTER", "UNDO"}

    source = None
    target = None
    preview = None
    active = None
    lmb = False

    nearest = None

    # Handlers list
    sd_handlers = []

    @classmethod
    def poll(cls, context):
        return (
            context.area.type == "IMAGE_EDITOR"
            and len(context.view_layer.objects.selected) != 0
        )

    def clear_draw_handlers(self):
        for handler in self.sd_handlers:
            bpy.types.SpaceImageEditor.draw_handler_remove(handler, "WINDOW")

    def get_vector_length(self, vector):
        length = np.linalg.norm(vector)
        return length

    def build_tree(self, context, type):
        for area in bpy.context.screen.areas:
            if area.type == "IMAGE_EDITOR":
                cursor = area.spaces.active.cursor_location
        bm = bmesh.from_edit_mesh(bpy.context.active_object.data)
        uv_layer = bm.loops.layers.uv.verify()

        selected_faces = set()
        all_faces = set()
        uvs = []

        for face in bm.faces:
            for loop in face.loops:
                all_faces.add(face)
                if loop[uv_layer].select:
                    selected_faces.add(face)

        if type == "all":
            for face in all_faces:
                for loop in face.loops:
                    loop_uv = loop[uv_layer]
                    uvs.append(loop_uv.uv)
                    uvs.append(cursor)

        elif type == "selected":
            for face in selected_faces:
                for loop in face.loops:
                    loop_uv = loop[uv_layer]
                    uvs.append(loop_uv.uv)

        ## Make an array of uv coordinates in 3D
        coordinates = [(uv.x, uv.y, 0) for uv in uvs]
        ## Create a jd tree from that
        kd = KDTree(len(coordinates))
        ## Populate it
        for i, v in enumerate(coordinates):
            kd.insert(v, i)
        ## Initialize it
        kd.balance()

        return kd

    def execute(self, context):

        bpy.ops.transform.translate(
            value=self.snap(self.x, self.y), orient_type="GLOBAL"
        )

        try:
            self.clear_draw_handlers()
        except ValueError:
            pass
        return {"FINISHED"}

    def snap(self, x, y):
        if not self.target:
            return Vector((0, 0, 0))

        dir = self.target - self.source

        if x and y:
            return dir

        elif not x:
            return (0, dir[1], 0)

        elif not y:
            return (dir[0], 0, 0)

    def update_distances(self, context, event, kd):
        mouse_pos_uv = Vector(
            (
                context.region.view2d.region_to_view(
                    event.mouse_region_x, event.mouse_region_y
                )
            )
        )

        self.nearest = None

        ## Search
        nearest, _, _ = kd.find((mouse_pos_uv.x, mouse_pos_uv.y, 0))

        self.nearest = nearest

        return self.nearest

    def move_closest_to_cursor(self, context, kd):
        for area in bpy.context.screen.areas:
            if area.type == "IMAGE_EDITOR":
                cursor = area.spaces.active.cursor_location
        ## Search
        nearest, _, _ = kd.find((cursor.x, cursor.y, 0))

        if nearest:
            dx = cursor.x - nearest.x
            dy = cursor.y - nearest.y

            bpy.ops.transform.translate(value=(dx, dy, 0), orient_type="GLOBAL")
            # bmesh.update_edit_mesh(bpy.context.active_object.data)
        else:
            self.report({"WARNING"}, "UVs are not selected?")

    def modal(self, context, event):
        context.area.tag_redraw()
        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            # allow navigation
            return {"PASS_THROUGH"}

        elif event.type == "TWO" and event.value == "PRESS":
            self.move_closest_to_cursor(context, self.kd_selected)
            self.clear_draw_handlers()
            return {"FINISHED"}

        elif event.type == "FOUR" and event.value == "PRESS":
            for area in bpy.context.screen.areas:
                if area.type == "IMAGE_EDITOR":
                    cursor = area.spaces.active.cursor_location
            cursor.x, cursor.y = self.nearest.x, self.nearest.y
            self.clear_draw_handlers()
            return {"FINISHED"}

        elif event.type == "ONE" and event.value == "PRESS":
            for area in bpy.context.screen.areas:
                if area.type == "IMAGE_EDITOR":
                    cursor = area.spaces.active.cursor_location
            self.source = self.nearest
            self.target = Vector((*cursor, 0))
            self.execute(context)
            return {"FINISHED"}

        elif event.type == "MOUSEMOVE":
            self.update_distances(context, event, self.kd)
            self.preview = self.nearest
            if self.source:
                self.target = self.nearest

        elif event.type in {"LEFTMOUSE"} and event.value == "PRESS":
            if self.source:
                if event.ctrl:
                    DISTANCE = self.get_vector_length(self.snap(self.x, self.y))
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

        elif event.type == "X" and event.value == "PRESS":
            if self.source and self.target:
                self.y = False
                self.execute(context)
            else:
                try:
                    self.report({"WARNING"}, "Nothing to move")
                    self.clear_draw_handlers()
                except ValueError:
                    pass
            return {"FINISHED"}

        elif event.type == "Y" and event.value == "PRESS":
            if self.source and self.target:
                self.x = False
                self.execute(context)
            else:
                try:
                    self.report({"WARNING"}, "Nothing to move")
                    self.clear_draw_handlers()
                except ValueError:
                    pass
            return {"FINISHED"}

        elif event.type in {"LEFTMOUSE"} and event.value == "RELEASE":
            if not self.source:
                self.report({"WARNING"}, "WRONG SOURCE OR TARGET")
                self.clear_draw_handlers()
                return {"CANCELLED"}
            elif not self.target:
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

        self.kd = self.build_tree(context, type="all")
        self.kd_selected = self.build_tree(context, type="selected")

        self.x = True
        self.y = True

        if context.space_data.type == "IMAGE_EDITOR":
            args = (self, context)
            self.active = context.view_layer.objects.active
            self.update_distances(context, event, self.kd)
            self.lmb = False

            uidpi = int((72 * context.preferences.system.ui_scale))
            args_text = (self, context, uidpi, context.preferences.system.ui_scale)

            # Add draw handlers
            self.handle_snap_line = bpy.types.SpaceImageEditor.draw_handler_add(
                draw_snap_line, args, "WINDOW", "POST_PIXEL"
            )
            self.handle_snap_points = bpy.types.SpaceImageEditor.draw_handler_add(
                draw_snap_points, args, "WINDOW", "POST_PIXEL"
            )
            self.handle_iops_text = bpy.types.SpaceImageEditor.draw_handler_add(
                draw_iops_text, args_text, "WINDOW", "POST_PIXEL"
            )
            self.sd_handlers = [
                self.handle_snap_line,
                self.handle_snap_points,
                self.handle_iops_text,
            ]
            # Add modal handler to enter modal mode
            context.window_manager.modal_handler_add(self)
            return {"RUNNING_MODAL"}
        else:
            self.report({"WARNING"}, "Active space must be a View3d")
            return {"CANCELLED"}
