import bpy
import random
from bpy.props import (
    BoolProperty,
)
from ..utils.functions import get_active_and_selected


def get_random_obj_from_list(list):
    if len(list) != 0:
        obj = random.choice(list)
        return obj


class IOPS_OT_Object_Replace(bpy.types.Operator):
    """Replace objects with active"""

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
        default=True,
    )
    select_replaced: BoolProperty(
        name="Select Replaced",
        description="Enabled = Select Replaced Objects, Disabled = Keep Selection",
        default=True,
    )

    keep_rotation: BoolProperty(
        name="Keep Rotation",
        description="Enabled = Use Active Object Rotation, Disabled = Use Selected Object Rotation",
        default=False,
    )

    keep_scale: BoolProperty(
        name="Keep Scale",
        description="Enabled = Use Active Object Scale, Disabled = Use Selected Object Scale",
        default=False,
    )

    keep_active_object_collection: BoolProperty(
        name="Keep Active Object Collection",
        description="Enabled = Use Active Object Collection, Disabled = Object Replace Collection",
        default=True,
    )

    keep_object_collection: BoolProperty(
        name="Keep Object Collection",
        description="Enabled = Use Selected Object Collection, Disabled = Object Replace Collection. Keep in mind that this option will override the Keep Active Object Collection option.",
        default=True,
    )

    def execute(self, context):
        active, objects = get_active_and_selected()
        if active and objects:

            if self.keep_active_object_collection:
                collection = active.users_collection[0]
            else:
                collection = bpy.data.collections.new("Object Replace")
                bpy.context.scene.collection.children.link(collection)

            new_objects = []
            for ob in objects:
                if self.keep_object_collection:
                    collection = ob.users_collection[0]
                new_ob = active.copy()
                if active.type == "MESH":
                    new_ob.data = active.data.copy()
                # position
                new_ob.location = ob.location
                # scale
                if self.keep_scale:
                    new_ob.scale = active.scale
                else:
                    new_ob.scale = ob.scale
                # rotation
                if self.keep_rotation:
                    new_ob.rotation_euler = active.rotation_euler
                else:
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
                    bpy.data.objects.remove(
                        ob, do_unlink=True, do_id_user=True, do_ui_user=True
                    )
            self.report({"INFO"}, "Objects Were Replaced")
        else:
            self.report({"ERROR"}, "Please Select Objects")
        return {"FINISHED"}

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.prop(self, "keep_active_object_collection")
        col.prop(self, "keep_object_collection")
        # col.prop(self, "use_active_collection")
        col.prop(self, "replace")
        col.prop(self, "select_replaced")
        col.separator()
        col.prop(self, "keep_rotation")
        col.prop(self, "keep_scale")
