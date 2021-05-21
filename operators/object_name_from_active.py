import bpy
import re
from bpy.props import (
        IntProperty,
        StringProperty
        )


class IOPS_OT_Object_Name_From_Active (bpy.types.Operator):
    """ Rename Object as Active ObjectName"""
    bl_idname = "iops.object_name_from_active"
    bl_label = "IOPS Object Name From Active"
    bl_options = {"REGISTER", "UNDO"}
    
    pattern: StringProperty(
        name="Pattern",
        description='''Naming Syntaxis: 
    [P] - Prefix 
    [N] - Name
    [S] - Suffix
    [C] - Counter
    [V] - Variouse''',
        default="[N]_[C]",
        )
    
    prefix: StringProperty(
        name="Prefix",
        default="",
        )

    suffix: StringProperty(
        name="Suffix",
        default="",
        )
    extra: StringProperty(
        name="Extra",
        default="",
        )
    
    counter_digits: IntProperty(
        name="Counter Digits",
        description="Number Of Digits For Counter",
        default=3,
        min=2,
        max=10
        )

    def execute(self, context): 
        if self.pattern:
            name = bpy.context.view_layer.objects.active.name            
            digit = "{0:0>" + str(self.counter_digits) + "}"
            active = bpy.context.view_layer.objects.active            
            counter = 0
            for o in bpy.context.selected_objects:
                if o is not active:
                    pattern = re.split(r"(\[\w+\])", self.pattern)
                    # i - index, p - pattern
                    for i, p in enumerate(pattern):
                        if p == "[P]":
                            pattern[i] = self.prefix
                        if p == "[N]":
                            pattern[i] = name
                        if p == "[S]":
                            pattern[i] = self.suffix
                        if p == "[E]":
                           pattern[i] = self.extra 
                        if p == "[C]":
                           pattern[i] = digit.format(counter)
                    o.name = "".join(pattern)
                    counter +=1   
        else:
            self.report ({'ERROR'}, "Please fill the pattern field")
        return {'FINISHED'}
    
    
    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True) 
        col.prop(self, "pattern")
        col.prop(self, "prefix")
        col.prop(self, "suffix")
        col.prop(self, "extra")
        col.prop(self, "counter_digits")
        
        
        
    
        