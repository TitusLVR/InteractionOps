import bpy
import copy
import re
from bpy.props import (
        IntProperty,
        StringProperty,
        BoolProperty,
        )


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

    def invoke(self, context, event):       
        self.active_name = context.view_layer.objects.active.name
        return self.execute(context)

    def execute(self, context): 
        base_name = context.view_layer.objects.active.name
        
        if self.pattern:
            if  self.active_name != context.view_layer.objects.active.name:
                context.view_layer.objects.active.name = self.active_name
            digit = "{0:0>" + str(self.counter_digits) + "}"
            active = bpy.context.view_layer.objects.active                                    
            counter = 0
            if self.counter_shift:
                counter = 1
            for o in bpy.context.selected_objects:
                if o is not active and self.rename_active is False:
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
                    counter +=1
                else:
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
        row.prop(self, "counter_digits")
        row.prop(self, "counter_shift")
        row.prop(self, "rename_active")
        
        
        
    
        