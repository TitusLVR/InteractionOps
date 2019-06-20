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
from mathutils import Vector, Matrix
import copy


def draw_callback_iops_aotf_px(self, context, _uidpi, _uifactor):
    prefs = bpy.context.preferences.addons['InteractionOps'].preferences
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
        ("Face edge index", str(self.get_edge_idx(self.counter))),
        ("Align to axis", str(self.axis_rotate)),
    )

    # FontID
    font = 0
    blf.color(font, tColor[0], tColor[1], tColor[2], tColor[3])
    blf.size(font, tCSize, _uidpi)
    if tShadow:
        blf.enable(font, blf.SHADOW)
        blf.shadow(font, int(tSBlur), tSColor[0], tSColor[1], tSColor[2], tSColor[3])
        blf.shadow_offset(font, tSPosX, tSPosY)
    else:
        blf.disable(0, blf.SHADOW)

    textsize = tCSize
    # get leftbottom corner
    offset = tCPosY
    columnoffs = (textsize * 10) * _uifactor
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

class IOPS_OT_AlignOriginToNormal(bpy.types.Operator):
    """ Align object to selected face """
    bl_idname = "iops.align_origin_to_normal"
    bl_label = "MESH: Align origin to face normal"
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
        return (context.area.type == "VIEW_3D" and
                context.mode == "EDIT_MESH" and
                len(context.view_layer.objects.selected) != 0 and
                context.view_layer.objects.active.type == "MESH")

    def align_update(self, event):
        self.align_to_face(self.get_edge_idx(self.counter), self.axis_rotate, self.flip)
        self.report({"INFO"}, event.type)

    def get_edge_idx(self, idx):
        """Return edge index from (counter % number of edges) of a face"""

        obj = bpy.context.view_layer.objects.active
        polymesh = obj.data
        bm = bmesh.from_edit_mesh(polymesh)
        face = bm.faces.active
        face.edges.index_update()
        index = abs(idx % len(face.edges))
        return index


    def align_origin_to_normal(self, idx, axis, flip):

        bpy.ops.view3d.snap_cursor_to_selected()
        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
        bpy.ops.object.mode_set(mode="EDIT")

        obj = bpy.context.view_layer.objects.active
        mx = obj.matrix_world.copy()
        loc = mx.to_translation()  # Store location
        scale = mx.to_scale()      # Store scale
        polymesh = obj.data
        bm = bmesh.from_edit_mesh(polymesh)
        face = bm.faces.active

        # Vector from and edge
        vector_edge = (face.edges[idx].verts[0].co -
                       face.edges[idx].verts[1].co).normalized()
        x = Vector((1,0,0))
        y = Vector((0,1,0))
        z = Vector((0,0,1))
        
        # Build vectors for new matrix
        n = face.normal                                  # Z
        t = vector_edge                                  # Y
        c = t.cross(n)                                   # X

        # Assemble new matrix
        mx_new = Matrix((c, t, n)).transposed().to_4x4()

        # New matrix rotation part
        new_rot = mx_new.to_euler()

        # Apply new matrix
        obj.matrix_world = mx_new.inverted()
        obj.location = loc
        obj.scale = scale
        
        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=False, properties=False)
        obj.rotation_euler = new_rot

    def modal(self, context, event):
            context.area.tag_redraw()
            if event.type in {'MIDDLEMOUSE'}:
                # Allow navigation
                return {'PASS_THROUGH'}
            elif event.type in {'X', 'Y', 'Z'} and event.value == "PRESS":
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
                self.mx_orig = []
                self.loc_start = []
                return {"FINISHED"}

            elif event.type in {"RIGHTMOUSE", "ESC"}:
                bpy.types.SpaceView3D.draw_handler_remove(self._handle, "WINDOW")
                bpy.types.SpaceView3D.draw_handler_remove(self._handle_edge, "WINDOW")
                active = context.view_layer.objects.active
                active.matrix_world = self.orig_mx
                # clean up
                self.orig_mx = []
                return {"CANCELLED"}

            return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        preferences = context.preferences
        if context.object and context.area.type == "VIEW_3D":

            # Apply transform so it works multiple times
            bpy.ops.object.mode_set(mode="OBJECT")
            bpy.ops.object.transform_apply(location=False, rotation=True, scale=False, properties=False)
            bpy.ops.object.mode_set(mode="EDIT")
            
            # Initialize axis and assign starting values for object's location
            self.axis_rotate = 'Z'
            self.flip = True
            self.edge_idx = 0
            self.counter = 0
            self.align_origin_to_normal(self.edge_idx, self.axis_rotate, self.flip)

            # Add drawing handler for text overlay rendering
            uidpi = int((72 * preferences.system.ui_scale))
            args = (self, context, uidpi, preferences.system.ui_scale)
            self._handle = bpy.types.SpaceView3D.draw_handler_add(draw_callback_iops_aotf_px, args, 'WINDOW', 'POST_PIXEL')

            # Add modal handler to enter modal mode
            context.window_manager.modal_handler_add(self)
            return {"RUNNING_MODAL"}

        else:
            self.report({"WARNING"}, "No active object, could not finish")
            return {"CANCELLED"}
