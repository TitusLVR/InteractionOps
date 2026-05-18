import bpy
from bpy.props import (
    IntProperty,
    BoolProperty,
    StringProperty,
    FloatVectorProperty,
)
import bmesh
from mathutils import Vector, Matrix

from ..ui.draw import primitives as draw, draw_scope, Role
from ..ui.draw.theme import get_theme
from ..ui.hud import HUDOverlay, HUDSection, HUDItem, ItemState, handle_hud_toggle


class IOPS_OT_AlignObjectToFace(bpy.types.Operator):
    """Align object to selected face"""

    bl_idname = "iops.mesh_align_object_to_face"
    bl_label = "MESH: Align object to face"
    bl_options = {"REGISTER", "UNDO"}

    axis_move: StringProperty()
    axis_rotate: StringProperty()
    loc: FloatVectorProperty()
    edge_idx: IntProperty()
    counter: IntProperty()
    flip: BoolProperty()

    orig_mx = []

    @classmethod
    def poll(self, context):
        return (
            context.area.type == "VIEW_3D"
            and context.mode == "EDIT_MESH"
            and len(context.view_layer.objects.selected) != 0
            and context.view_layer.objects.active.type == "MESH"
        )

    def _build_hud(self, context):
        verbosity = get_theme(context).hud.verbosity
        hud = HUDOverlay("align_to_face", verbosity=verbosity)
        hud.add_section(HUDSection("Align to Face", [
            HUDItem("Cycle edge",    "Wheel",          ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Align axis",    "X / Y / Z",      ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Move (Shift)",  "Shift + X/Y/Z",  ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Confirm",       "LMB / Space",    ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Cancel",        "RMB / Esc",      ItemState.ON, default_state=ItemState.OFF, always_show=True),
            HUDItem("Help / Toggle HUD", "H", ItemState.ON, default_state=ItemState.OFF, always_show=True),
        ]))
        hud.bind_region(context.region)
        return hud

    def _sync_hud_header(self):
        if getattr(self, "hud", None) is None:
            return
        try:
            edge_idx = self.get_edge_idx(self.counter)
        except Exception:
            edge_idx = "?"
        self.hud.set_header(f"Edge {edge_idx} | Axis {self.axis_rotate}")

    def _draw_hud(self, context):
        if getattr(self, "hud", None) is None:
            return
        self.hud.draw(context, getattr(self, "_last_event", None))

    def _draw_edge(self, context):
        if not getattr(self, "edge_co", None):
            return
        with draw_scope(blend="ALPHA", depth="ALWAYS"):
            draw.edges_3d(list(self.edge_co), role=Role.ACTIVE_LINE, context=context)
            draw.points(list(self.edge_co), role=Role.ACTIVE_POINT, context=context)

    def align_update(self, event):
        self.align_to_face(self.get_edge_idx(self.counter), self.axis_rotate, self.flip)
        self._sync_hud_header()
        self.report({"INFO"}, event.type)

    def move(self, axis_move, step):
        if axis_move == "X":
            self.loc[0] += step
        elif axis_move == "Y":
            self.loc[1] += step
        elif axis_move == "Z":
            self.loc[2] += step

    def get_edge_idx(self, idx):
        """Return edge index from (counter % number of edges) of a face"""

        obj = bpy.context.view_layer.objects.active
        polymesh = obj.data
        bm = bmesh.from_edit_mesh(polymesh)
        face = bm.faces.active
        face.edges.index_update()
        index = abs(idx % len(face.edges))

        return index

    def align_to_face(self, idx, axis, flip):
        """Takes face normal and aligns it to global axis.
        Uses one of the face edges to further align it to another axis.
        Sets align edge coordinates"""
        obj = bpy.context.view_layer.objects.active
        mx = obj.matrix_world.copy()
        loc = mx.to_translation()
        scale = mx.to_scale()
        polymesh = obj.data
        bm = bmesh.from_edit_mesh(polymesh)
        face = bm.faces.active

        vector_edge = (
            face.edges[idx].verts[0].co - face.edges[idx].verts[1].co
        ).normalized()

        n = face.normal if flip else (face.normal * -1)
        t = vector_edge
        c = t.cross(n)

        if axis == "Z":
            mx_new = Matrix((c, t, n)).transposed().to_4x4()
        elif axis == "Y":
            mx_new = Matrix((t, n, c)).transposed().to_4x4()
        elif axis == "X":
            mx_new = Matrix((n, c, t)).transposed().to_4x4()

        obj.matrix_world = mx_new.inverted()
        obj.location = loc
        obj.scale = scale

        gpu_verts = [Vector(), Vector()]

        def scale_vert(scale):
            gpu_verts[0][0] = face.edges[idx].verts[0].co[0] * scale[0]
            gpu_verts[0][1] = face.edges[idx].verts[0].co[1] * scale[1]
            gpu_verts[0][2] = face.edges[idx].verts[0].co[2] * scale[2]
            gpu_verts[1][0] = face.edges[idx].verts[1].co[0] * scale[0]
            gpu_verts[1][1] = face.edges[idx].verts[1].co[1] * scale[1]
            gpu_verts[1][2] = face.edges[idx].verts[1].co[2] * scale[2]

        scale_vert(scale)

        self.edge_co = [
            gpu_verts[0] @ mx_new + obj.location,
            gpu_verts[1] @ mx_new + obj.location,
        ]

    def modal(self, context, event):
        context.area.tag_redraw()
        self._last_event = event
        if handle_hud_toggle(getattr(self, "_hud", None) or getattr(self, "hud", None), context, event):
            return {'RUNNING_MODAL'}
        if event.type in {"MIDDLEMOUSE"}:
            return {"PASS_THROUGH"}
        if event.shift:
            if event.type in {"X", "Y", "Z"} and event.value == "PRESS":
                self.axis_move = event.type
                bpy.context.object.location = self.loc

            elif event.type == "WHEELDOWNMOUSE":
                self.move(self.axis_move, -0.5)
                bpy.context.object.location = self.loc

            elif event.type == "WHEELUPMOUSE":
                self.move(self.axis_move, 0.5)
                bpy.context.object.location = self.loc
        elif event.type in {"X", "Y", "Z"} and event.value == "PRESS":
            self.flip = not self.flip
            self.axis_rotate = event.type
            self.align_update(event)

        elif event.type == "WHEELDOWNMOUSE":
            if self.counter > 0:
                self.counter -= 1
            self.align_update(event)

        elif event.type == "WHEELUPMOUSE":
            self.counter += 1
            self.align_update(event)

        elif event.type in {"LEFTMOUSE", "SPACE"}:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, "WINDOW")
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_edge, "WINDOW")
            return {"FINISHED"}

        elif event.type in {"RIGHTMOUSE", "ESC"}:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, "WINDOW")
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_edge, "WINDOW")
            active = context.view_layer.objects.active
            active.matrix_world = self.orig_mx
            self.orig_mx = []
            return {"CANCELLED"}

        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        if not (context.object and context.area.type == "VIEW_3D"):
            self.report({"WARNING"}, "No active object, could not finish")
            return {"CANCELLED"}

        active = context.view_layer.objects.active
        self.orig_mx = active.matrix_world.copy()

        self.axis_move = "Z"
        self.axis_rotate = "Z"
        self.flip = True
        self.edge_idx = 0
        self.counter = 0
        self.align_to_face(self.edge_idx, self.axis_rotate, self.flip)

        self.hud = self._build_hud(context)
        self._last_event = event
        self._sync_hud_header()

        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_hud, (context,), "WINDOW", "POST_PIXEL"
        )
        self._handle_edge = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_edge, (context,), "WINDOW", "POST_VIEW"
        )

        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}
