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

    rename_mesh_data_single: BoolProperty(
        name="Rename Mesh Data",
        description="Rename mesh data when only one object is selected",
        default=False,
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

    copy_to_clipboard: BoolProperty(
        name="Copy to Clipboard",
        description="Copy the active object name to the clipboard",
        default=True,
    )

    def invoke(self, context, event):
        self.active_name = context.view_layer.objects.active.name
        self.new_name = self.active_name
        return self.execute(context)

    def execute(self, context):
        Objects = context.selected_objects
        if len(Objects) == 1:
            if self.copy_to_clipboard:
                context.window_manager.clipboard = self.active_name            
            if self.rename_mesh_data_single and Objects[0].type == "MESH":
                Objects[0].data.name = Objects[0].name
            return {"FINISHED"}
        else:
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
        selected_count = len(context.selected_objects)

        if selected_count == 1:
            # Simple: one object
            col = layout.column(align=True)
            col.prop(self, "copy_to_clipboard", text="Copy Name to Clipboard")
            col.prop(self, "rename_mesh_data_single", text="Rename Mesh Data to Object Name")
        else:
            # Full: multiple objects
            col = layout.column(align=True)
            row = col.row()
            row.enabled = False
            row.prop(self, "active_name", text="Active")
            col.prop(self, "new_name", text="New Name")
            col.separator()
            row = col.row(align=True)
            row.prop(self, "use_trim", toggle=True)
            sub = row.row(align=True)
            sub.enabled = self.use_trim
            sub.prop(self, "trim_prefix", text="Prefix")
            sub.prop(self, "trim_suffix", text="Suffix")
            layout.separator()

            col = layout.column(align=True)
            col.prop(self, "pattern", text="Pattern")
            row = col.row(align=True)
            row.label(text="Counter Digits")
            row.prop(self, "counter_digits", text="")
            row.prop(self, "counter_shift", text="+1 Shift")
            layout.separator()

            col = layout.column(align=True)
            col.prop(self, "copy_to_clipboard", text="Copy Name to Clipboard")
            col.prop(self, "rename_active", text="Include Active Object")
            col.prop(self, "use_distance", text="Sort by Distance to Active")
            col.prop(self, "rename_mesh_data", text="Object's Mesh Data")
            col.prop(self, "rename_linked", text="Linked Objects")  
