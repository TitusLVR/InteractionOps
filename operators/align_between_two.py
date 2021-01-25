import bpy

from mathutils import Vector, Matrix
from bpy.props import (BoolProperty,
                       EnumProperty,
                       FloatProperty,
                       IntProperty,
                       PointerProperty,
                       StringProperty,
                       FloatVectorProperty,
                       )

class IOPS_OT_Align_between_two(bpy.types.Operator):
    """Align active object between two selected objects"""
    bl_idname = "iops.align_between_two"
    bl_label = "Align Between Two"
    bl_options = {'REGISTER', 'UNDO'}

    track_axis: EnumProperty(
        name='Track',
        description='Track axis',
        items=[
            ('X', 'X',  '', '', 0),
            ('Y', 'Y',  '', '', 1),
            ('Z', 'Z',  '', '', 2),
            ('-X', '-X',  '', '', 3),
            ('-Y', '-Y',  '', '', 4),
            ('-Z', '-Z',  '', '', 5),
            ],
        default='Z',
    )
    up_axis: EnumProperty(
        name='Up',
        description='Up axis',
        items=[
            ('X', 'X',  '', '', 0),
            ('Y', 'Y',  '', '', 1),
            ('Z', 'Z',  '', '', 2),
            ],
        default='Y',
    )

    use_cursor: BoolProperty(
        name="Cursor as second object",
        description="Align active objcet between object and cursor",
        default=False
    )

    def rotate_between_two(self):
        if len(bpy.context.selected_objects) != 3: 
            return
        else:
            objTarget = bpy.context.view_layer.objects.active
            posA, posB = [ob.location for ob in bpy.context.selected_objects if ob != objTarget]
            midPoint = (posA + posB)/2
            objTarget.location = midPoint
            axis = posA - posB
            rotation_mode = objTarget.rotation_mode
            objTarget.rotation_mode = 'QUATERNION'
            objTarget.rotation_quaternion = axis.to_track_quat(self.track_axis, self.up_axis)
            objTarget.rotation_mode = rotation_mode

    def rotate_between_two_cursor(self):
        if len(bpy.context.selected_objects) != 2: 
            return
        else:
            objTarget = bpy.context.view_layer.objects.active
            posA = None
            for ob in bpy.context.selected_objects:
                if ob != objTarget:
                    posA = ob.location
            posB = bpy.context.scene.cursor.location
            midPoint = (posA + posB)/2
            objTarget.location = midPoint
            axis = posA - posB
            rotation_mode = objTarget.rotation_mode
            objTarget.rotation_mode = 'QUATERNION'
            objTarget.rotation_quaternion = axis.to_track_quat(self.track_axis, self.up_axis)
            objTarget.rotation_mode = rotation_mode
    
    def execute(self, context):
        if self.track_axis != self.up_axis:
            if self.use_cursor:
                self.rotate_between_two_cursor()
            else:
                self.rotate_between_two()
            
            self.report({"INFO"}, "Aligned!")
        else:
            self.report({"WARNING"}, "SAME AXIS")
        return {"FINISHED"}
