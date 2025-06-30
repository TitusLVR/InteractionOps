import bpy
import re
from bpy.props import (
    IntProperty,
    StringProperty,
    BoolProperty,
)
from mathutils import Vector
from ..utils.functions import get_object_col_names 


def distance_vec(point1: Vector, point2: Vector):
    """Calculate distance between two points."""
    return (point2 - point1).length


class IOPS_OT_Object_Name_From_Active(bpy.types.Operator):
    """Rename Object as Active ObjectName"""

    bl_idname = "iops.object_name_from_active"
    bl_label = "IOPS Object Name From Active"
    bl_options = {"REGISTER", "UNDO"}

    new_name: StringProperty(
        name="New Name",
        default="",
    )

    active_name: StringProperty(
        name="Active Name",
        default="",
    )

    pattern: StringProperty(
        name="Pattern",
        description="""Naming Syntaxis:
    [N] - Name
    [C] - Counter
    [T] - Object Type
    [COL] - Collection Name
    """,
        default="[N]_[C]",
    )

    use_distance: BoolProperty(
        name="By Distance",
        description="Rename Selected Objects Based on Distance to Active Object",
        default=True,
    )

    counter_digits: IntProperty(
        name="Counter Digits",
        description="Number Of Digits For Counter",
        default=2,
        min=2,
        max=10,
    )

    counter_shift: BoolProperty(
        name="+1",
        description="+1 shift for counter, useful when we need to rename active object too",
        default=True,
    )

    rename_active: BoolProperty(
        name="Rename Active", description="Rename active also", default=True
    )

    rename_mesh_data: BoolProperty(
        name="Rename Mesh Data", description="Rename Mesh Data", default=True
    )

    trim_prefix: IntProperty(
        name="Prefix",
        description="Number Of Digits for Prefix trim",
        default=0,
        min=0,
        max=100,
    )

    trim_suffix: IntProperty(
        name="Suffix",
        description="Number Of Digits for Suffix trim",
        default=0,
        min=0,
        max=100,
    )
    use_trim: BoolProperty(
        name="Trim", description="Trim Name Prefix/Suffix", default=False
    )
    rename_linked: BoolProperty(
        name="Rename Linked",
        description="Rename Linked Objects",
        default=False,
    )

    def invoke(self, context, event):
        self.active_name = context.view_layer.objects.active.name
        self.new_name = self.active_name
        return self.execute(context)

    def execute(self, context):
        if self.pattern:
            if self.active_name != context.view_layer.objects.active.name:
                context.view_layer.objects.active.name = self.active_name
            # Trim string
            if self.use_trim:
                name = self.active_name
                if self.trim_suffix == 0:
                    self.new_name = name[(self.trim_prefix) :]
                else:
                    self.new_name = name[(self.trim_prefix) : -(self.trim_suffix)]
            else:
                self.trim_suffix = self.trim_prefix = 0

            digit = "{0:0>" + str(self.counter_digits) + "}"
            # Combine objects
            active = bpy.context.view_layer.objects.active
            Objects = bpy.context.selected_objects
            if active:
                active_collection = active.users_collection[0]
            else:
                active_collection = ""
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
            
            if self.rename_linked:
                if active.children_recursive:
                    to_rename.extend([child.name for child in active.children_recursive])
                

            for name in to_rename:
                o = bpy.data.objects[name]
                pattern = re.split(r"(\[\w+\])", self.pattern)
                # i - index, p - pattern
                for i, p in enumerate(pattern):
                    if p == "[N]":
                        pattern[i] = self.new_name
                    if p == "[C]":
                        pattern[i] = digit.format(counter)
                    if p == "[T]":
                        pattern[i] = o.type.lower()
                    if p == "[COL]":
                        pattern[i] = get_object_col_names(o) 
                o.name = "".join(pattern)
                # Rename object mesh data
                if self.rename_mesh_data:
                    if o.type == "MESH":
                        o.data.name = o.name
                counter += 1
        else:
            self.report({"ERROR"}, "Please fill the pattern field")
        return {"FINISHED"}

    def draw(self, context):
        layout = self.layout
        col_active_name = layout.column(align=True)
        col_active_name.enabled = False
        col_active_name.prop(self, "active_name", text="Old Name")

        col = layout.column(align=True)
        col.prop(self, "new_name", text="New Name")
        col.separator()
        col = layout.column(align=True)
        # Trim
        row = col.row(align=True)
        sub = row.row(align=True)
        sub.enabled = self.use_trim
        sub.prop(self, "trim_prefix")
        row.prop(self, "use_trim", toggle=True)
        sub = row.row(align=True)
        sub.enabled = self.use_trim
        sub.prop(self, "trim_suffix")
        # Pattern
        col = layout.column(align=True)
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
        
        col.prop(self, "rename_active", text="Active Object")
        col.prop(self, "use_distance", text="By Distance")
        col.prop(self, "rename_mesh_data", text="Object's MeshData")
        col.prop(self, "rename_linked", text="Linked Objects")
