import bpy
import blf
import gpu
import bmesh
from math import sin, cos, pi
import numpy as np
from mathutils import Vector, Matrix


class IOPS_OT_DragSnapCursor(bpy.types.Operator):
    """ Quick drag & snap using 3D Cursor """
    bl_idname = "iops.drag_snap_cursor"
    bl_label = "IOPS Drag Snap Cursor"
    bl_description = "Hold Q and LMB Click to quickly snap point to point using 3D Cursor"
    bl_options = {"REGISTER", "UNDO"}

    step = 1
    count = 0
    old_type = None
    old_value = None

    @classmethod
    def poll(cls, context):
        return (context.area.type == "VIEW_3D" and
                context.mode == "OBJECT" and
                len(context.view_layer.objects.selected) != 0)

    def modal(self, context, event):
        #prevent spamming
        # new_type = event.type
        # new_value = event.value
        # if new_type != self.old_type and new_value != self.old_value:
        #     print(event.type, event.value)
        #     self.old_type = new_type
        #     self.old_value = new_value

        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and event.value == 'PRESS':
            return {'PASS_THROUGH'}
        elif event.type in {'ESC', 'RIGHMOUSE'} and event.value == 'PRESS':
            return {'CANCELLED'}

        elif event.type == 'Q' and event.value == 'PRESS':
            print("Count:", self.count)
            bpy.ops.transform.translate('INVOKE_DEFAULT',
            cursor_transform=True,
            use_snap_self=True,
            snap_target='CLOSEST',
            use_snap_nonedit = True,
            snap_elements={'VERTEX'},
            snap=True,
            release_confirm=True
            )
            self.count += 1
            if self.count == 1:
                # print("Count:", 1)
                self.report({'INFO'}, "Step 2: Q to place cursor at point B")
            elif self.count == 2:
                bpy.context.scene.IOPS.dragsnap_point_a = bpy.context.scene.cursor.location
                # print("Count:", 2)
                self.report({'INFO'}, "Step 3: press Q")
            elif self.count == 3:
                # print("Count:", 3)
                bpy.context.scene.IOPS.dragsnap_point_b = bpy.context.scene.cursor.location
                vector = bpy.context.scene.IOPS.dragsnap_point_b - bpy.context.scene.IOPS.dragsnap_point_a
                bpy.ops.transform.translate(value=vector, orient_type='GLOBAL')
                return {'FINISHED'}

        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        self.report({'INFO'}, "Step 1: Q to place cursor at point A")
        # Add modal handler to enter modal mode
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    # a, b = bpy.context.scene.IOPS.dragsnap_point_a, bpy.context.scene.IOPS.dragsnap_point_b