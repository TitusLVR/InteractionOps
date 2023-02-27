import bpy
import copy
import re
from bpy.props import (
        IntProperty,
        StringProperty,
        BoolProperty,
        )
from mathutils import Vector

def distance_vec(point1: Vector, point2: Vector):
    """Calculate distance between two points."""
    return (point2 - point1).length

class IOPS_OT_Object_Name_From_Active (bpy.types.Operator):
    """ Rename Object as Active ObjectName"""
    bl_idname = "iops.object_name_from_active"
    bl_label = "IOPS Object Name From Active"
    bl_options = {"REGISTER", "UNDO"}

    active_name:StringProperty(
        name="Name",
        default="",
        )

    pattern: StringProperty(
        name="Pattern",
        description='''Naming Syntaxis:
    [N] - Name
    [C] - Counter
    [T] - Object Type
    ''',
        default="[N]_[C]",
        )

    use_distance: BoolProperty(
        name="By Distance",
        description="Rename Selected Objects Based on Distance to Active Object",
        default=True
    )

    counter_digits: IntProperty(
        name="Counter Digits",
        description="Number Of Digits For Counter",
        default=3,
        min=2,
        max=10
        )

    counter_shift: BoolProperty(
        name="+1",
        description="+1 shift for counter, useful when we need to rename active object too",
        default=True
    )

    rename_active: BoolProperty(
        name="Rename Active",
        description="Rename active also",
        default=True
    )

    rename_mesh_data: BoolProperty(
        name="Rename Mesh Data",
        description="Rename Mesh Data",
        default=True
    )


    def invoke(self, context, event):
        self.active_name = context.view_layer.objects.active.name
        return self.execute(context)

    def execute(self, context):
        if self.pattern:
            if  self.active_name != context.view_layer.objects.active.name:
                context.view_layer.objects.active.name = self.active_name
            digit = "{0:0>" + str(self.counter_digits) + "}"
            # Combine objects
            active = bpy.context.view_layer.objects.active
            Objects = bpy.context.selected_objects
            to_rename = []
            if self.use_distance:
                Objects.sort(key=lambda obj: (obj.location - active.location).length)
            # Check active
            if self.rename_active:
                to_rename = [ob.name for ob in Objects]
            else:
                to_rename = [ob.name for ob in Objects if ob is not active]
            # counter
            counter = 0
            if self.counter_shift:
                counter = 1

            for name in to_rename:
                o = bpy.data.objects[name]
                pattern = re.split(r"(\[\w+\])", self.pattern)
                # i - index, p - pattern
                for i, p in enumerate(pattern):
                    if p == "[N]":
                        pattern[i] = self.active_name
                    if p == "[C]":
                        pattern[i] = digit.format(counter)
                    if p == "[T]":
                        pattern[i] = o.type.lower()
                o.name = "".join(pattern)
                # Rename object mesh data
                if self.rename_mesh_data:
                    if o.type == 'MESH':
                        o.data.name = "MD_" + o.name
                counter +=1
        else:
            self.report ({'ERROR'}, "Please fill the pattern field")
        return {'FINISHED'}


    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.prop(self, "active_name")
        col.separator()
        col.prop(self, "pattern")
        col.separator()
        row = col.row(align=True)
        row.label(text="Counter Digits:")
        row.alignment = "LEFT"
        row.prop(self, "counter_digits", text="       ")
        row.separator(factor=1.0)
        row.prop(self, "counter_shift")
        col = layout.column(align=True)
        col.label(text="Rename:")
        row = col.row(align=True)
        row.prop(self, "rename_active", text="Active Object")
        row.prop(self, "use_distance", text="By Distance")
        row.separator()
        row.prop(self, "rename_mesh_data", text="Object's MeshData")


