import bpy
import random
from bpy.props import (
        IntProperty,
        StringProperty,
        BoolProperty,
        )
from ..utils.functions import get_active_and_selected 

def get_random_obj_from_list(list):
    if len(list) != 0:
        obj = random.choice(list)
        return obj


class IOPS_OT_Object_Replace (bpy.types.Operator):
    """ Replace objects with active"""
    bl_idname = "iops.object_replace"
    bl_label = "IOPS Object Replace"
    bl_options = {"REGISTER", "UNDO"}
    
    # use_active_collection: BoolProperty(
    #     name="Active Collection",
    #     description="Use Active Collection",
    #     default=False
    #     )
    replace: BoolProperty(
        name="Add/Replace",
        description="Enabled = Replace, Disabled = Add",
        default=True
        )
    select_replaced:BoolProperty(
        name="Select Replaced",
        description="Enabled = Select Replaced Objects, Disabled = Keep Selection",
        default=True
        )

    def execute(self, context):
        active, objects = get_active_and_selected()
        if active and objects:
            collection = bpy.data.collections.new("Object Replace")
            bpy.context.scene.collection.children.link(collection)
            new_objects = []
            for ob in objects:
                new_ob = active.copy()
                new_ob.data = active.data.copy()
                new_ob.location = ob.location
                new_ob.scale = ob.scale
                new_ob.rotation_euler = ob.rotation_euler
                collection.objects.link(new_ob)
                new_ob.select_set(False)
                new_objects.append(new_ob)
            
            if self.select_replaced:
                active.select_set(False)
                for ob in objects:
                    ob.select_set(False)
                for ob in new_objects:
                    ob.select_set(True)
                bpy.context.view_layer.objects.active = new_objects[-1] 

            if self.replace:
                for ob in objects:
                    bpy.data.objects.remove(ob, do_unlink=True, do_id_user=True, do_ui_user=True)
            self.report ({'INFO'}, "Objects Were Replaced")
        else:
            self.report ({'ERROR'}, "Please Select Objects")
        return {'FINISHED'}
    
    
    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True) 
        # col.prop(self, "use_active_collection")
        col.prop(self, "replace")
        col.prop(self, "select_replaced")
        

