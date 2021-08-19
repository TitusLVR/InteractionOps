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

from ..utils.functions import get_active_and_selected


class IOPS_OT_Align_between_two(bpy.types.Operator):
    """Align active object between two selected objects. Works for two objects also."""
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
        default='Y',
    )
    up_axis: EnumProperty(
        name='Up',
        description='Up axis',
        items=[
            ('X', 'X',  '', '', 0),
            ('Y', 'Y',  '', '', 1),
            ('Z', 'Z',  '', '', 2),
            ],
        default='Z',
    )
    align: BoolProperty(
        name="Align",
        description="Align Duplicates Between Selected Objects",
        default=False
        )

    count: IntProperty(
        name="Count",
        description="Number of Duplicates",
        default=1,
        soft_min=0,
        soft_max=100000000
    )

    select_duplicated:BoolProperty(
        name="Select Duplicated",
        description="Enabled = Select Duplicated Objects, Disabled = Keep Selection",
        default=True
        )

    def align_between(self):
        sequence = []
        active, objects = get_active_and_selected()
        if len(bpy.context.selected_objects) == 2:
            axis = active.location - objects[-1].location
            
            A = active.location 
            B = objects[-1].location 

            for ip in range(self.count):
                p = 1 / (self.count + 1) * (ip + 1)
                point = ((1 - p)  * A + p * B)
                sequence.append(point)

        elif len(bpy.context.selected_objects) == 3:
            posA, posB = [ob.location for ob in objects]
            axis = posA - posB
            
            for idx in range(len(objects) - 1):
                A = objects[idx].location 
                B = objects[idx + 1].location 

                for ip in range(self.count):
                    p = 1 / (self.count + 1) * (ip + 1)
                    point = ((1 - p)  * A + p * B)
                    sequence.append(point)

        collection = bpy.data.collections.new("Objects Between")
        bpy.context.scene.collection.children.link(collection)
        new_objects = []
        for p in sequence:
            new_ob = active.copy()
            new_ob.data = active.data.copy()
            # position
            new_ob.location = p 
            # rotation
            if self.align:                    
                new_ob.rotation_mode = 'QUATERNION'
                new_ob.rotation_quaternion = axis.to_track_quat(self.track_axis, self.up_axis)
                new_ob.rotation_mode = 'XYZ'
            
            collection.objects.link(new_ob)
            new_ob.select_set(False)
            new_objects.append(new_ob)
                    
        if self.select_duplicated:
            active.select_set(False)
            for ob in objects:
                ob.select_set(False)
            for ob in new_objects:
                ob.select_set(True)
            bpy.context.view_layer.objects.active = new_objects[-1] 
        
        else:
            return
    
    @classmethod
    def poll(self, context):
        return (context.area.type == "VIEW_3D" and
                context.mode == "OBJECT" and
                len(context.view_layer.objects.selected) == 2 or
                len(context.view_layer.objects.selected) == 3)
    
    def execute(self, context):
        if self.track_axis != self.up_axis:
            self.align_between()
            self.report({"INFO"}, "Aligned!")
        else:
            self.report({"WARNING"}, "SAME AXIS")
        return {"FINISHED"}


    def draw(self, context):
            layout = self.layout
            col = layout.column(align=True) 
            # col.prop(self, "use_active_collection")
            col.prop(self, "track_axis")
            col.prop(self, "up_axis")
            col.separator()
            col.prop(self, "align")
            col.prop(self, "count")
            col.separator()
            col.prop(self, "select_duplicated")

