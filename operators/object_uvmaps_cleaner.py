import bpy

# from mathutils import Vector, Matrix
# from bpy.props import (BoolProperty,
#                        EnumProperty,
#                        FloatProperty,
#                        IntProperty,
#                        PointerProperty,
#                        StringProperty,
#                        FloatVectorProperty,
#                        )


def tag_redraw(context, space_type="VIEW_3D", region_type="WINDOW"):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.spaces[0].type == space_type:
                for region in area.regions:
                    if region.type == region_type:
                        region.tag_redraw()

def uvmap_clean_by_index(obj, index):
    obj_uvmaps = obj.data.uv_layers
    if obj_uvmaps:
        ch_num = len(obj_uvmaps)
        for i in range(ch_num, index, -1):
            if i != 1:
                obj_uvmaps.remove(obj_uvmaps[i - 1])
            else:
                obj_uvmaps.remove(obj_uvmaps[0])


class IOPS_OT_Clean_UVMap_0(bpy.types.Operator):
    """Clean all UVMaps on selected objects"""

    bl_idname = "iops.object_clean_uvmap_0"
    bl_label = "Remove All UVMaps"
    bl_options = {"REGISTER", "UNDO"}

    # @classmethod
    # def poll(cls, context):
    #     return (context.area.type == "VIEW_3D")

    def execute(self, context):
        selected_objs = [
            o
            for o in context.view_layer.objects.selected
            if o.type == "MESH" and o.data.polygons[:] != [] and o.visible_get()
        ]
        if selected_objs:
            for ob in selected_objs:
                uvmap_clean_by_index(ob, 0)
            tag_redraw(context)
            self.report({"INFO"}, "All UVMaps Were Removed")

        else:
            self.report({"ERROR"}, "Select MESH objects.")
        return {"FINISHED"}


class IOPS_OT_Clean_UVMap_1(bpy.types.Operator):
    """Clean from UVMap #2 and up - on selected objects"""

    bl_idname = "iops.object_clean_uvmap_1"
    bl_label = "Remove UVMap 1"
    bl_options = {"REGISTER", "UNDO"}

    # @classmethod
    # def poll(cls, context):
    #     return (context.area.type == "VIEW_3D")

    def execute(self, context):
        selected_objs = [
            o
            for o in context.view_layer.objects.selected
            if o.type == "MESH" and o.data.polygons[:] != [] and o.visible_get()
        ]
        if selected_objs:
            for ob in selected_objs:
                uvmap_clean_by_index(ob, 1)
            tag_redraw(context)
            self.report({"INFO"}, "UVMaps 2 to 8 Removed")

        else:
            self.report({"ERROR"}, "Select MESH objects.")
        return {"FINISHED"}


class IOPS_OT_Clean_UVMap_2(bpy.types.Operator):
    """Clean from UVMap #3 and up - on selected objects"""

    bl_idname = "iops.object_clean_uvmap_2"
    bl_label = "Remove UVMap 2"
    bl_options = {"REGISTER", "UNDO"}

    # @classmethod
    # def poll(cls, context):
    #     return (context.area.type == "VIEW_3D")

    def execute(self, context):
        selected_objs = [
            o
            for o in context.view_layer.objects.selected
            if o.type == "MESH" and o.data.polygons[:] != [] and o.visible_get()
        ]
        if selected_objs:
            for ob in selected_objs:
                uvmap_clean_by_index(ob, 2)
            tag_redraw(context)
            self.report({"INFO"}, "UVMaps 3 to 8 Removed")

        else:
            self.report({"ERROR"}, "Select MESH objects.")
        return {"FINISHED"}


class IOPS_OT_Clean_UVMap_3(bpy.types.Operator):
    """Clean from UVMap #4 and up - on selected objects"""

    bl_idname = "iops.object_clean_uvmap_3"
    bl_label = "Remove UVMap 3"
    bl_options = {"REGISTER", "UNDO"}

    # @classmethod
    # def poll(cls, context):
    #     return (context.area.type == "VIEW_3D")

    def execute(self, context):
        selected_objs = [
            o
            for o in context.view_layer.objects.selected
            if o.type == "MESH" and o.data.polygons[:] != [] and o.visible_get()
        ]
        if selected_objs:
            for ob in selected_objs:
                uvmap_clean_by_index(ob, 3)
            tag_redraw(context)
            self.report({"INFO"}, "UVMaps 4 to 8 Removed")

        else:
            self.report({"ERROR"}, "Select MESH objects.")
        return {"FINISHED"}


class IOPS_OT_Clean_UVMap_4(bpy.types.Operator):
    """Clean from UVMap #5 and up - on selected objects"""

    bl_idname = "iops.object_clean_uvmap_4"
    bl_label = "Remove UVMap 4"
    bl_options = {"REGISTER", "UNDO"}

    # @classmethod
    # def poll(cls, context):
    #     return (context.area.type == "VIEW_3D")

    def execute(self, context):
        selected_objs = [
            o
            for o in context.view_layer.objects.selected
            if o.type == "MESH" and o.data.polygons[:] != [] and o.visible_get()
        ]
        if selected_objs:
            for ob in selected_objs:
                uvmap_clean_by_index(ob, 4)
            tag_redraw(context)
            self.report({"INFO"}, "UVMaps 5 to 8 Removed")

        else:
            self.report({"ERROR"}, "Select MESH objects.")
        return {"FINISHED"}


class IOPS_OT_Clean_UVMap_5(bpy.types.Operator):
    """Clean from UVMap #6 and up - on selected objects"""

    bl_idname = "iops.object_clean_uvmap_5"
    bl_label = "Remove UVMap 5"
    bl_options = {"REGISTER", "UNDO"}

    # @classmethod
    # def poll(cls, context):
    #     return (context.area.type == "VIEW_3D")

    def execute(self, context):
        selected_objs = [
            o
            for o in context.view_layer.objects.selected
            if o.type == "MESH" and o.data.polygons[:] != [] and o.visible_get()
        ]
        if selected_objs:
            for ob in selected_objs:
                uvmap_clean_by_index(ob, 5)
            tag_redraw(context)
            self.report({"INFO"}, "UVMaps 6 to 8 Removed")

        else:
            self.report({"ERROR"}, "Select MESH objects.")
        return {"FINISHED"}


class IOPS_OT_Clean_UVMap_6(bpy.types.Operator):
    """Clean from UVMap #7 and up - on selected objects"""

    bl_idname = "iops.object_clean_uvmap_6"
    bl_label = "Remove UVMap 6"
    bl_options = {"REGISTER", "UNDO"}

    # @classmethod
    # def poll(cls, context):
    #     return (context.area.type == "VIEW_3D")

    def execute(self, context):
        selected_objs = [
            o
            for o in context.view_layer.objects.selected
            if o.type == "MESH" and o.data.polygons[:] != [] and o.visible_get()
        ]
        if selected_objs:
            for ob in selected_objs:
                uvmap_clean_by_index(ob, 6)
            tag_redraw(context)
            self.report({"INFO"}, "UVMaps 7 to 8 Removed")

        else:
            self.report({"ERROR"}, "Select MESH objects.")
        return {"FINISHED"}


class IOPS_OT_Clean_UVMap_7(bpy.types.Operator):
    """Clean UVMap #8  - on selected objects"""

    bl_idname = "iops.object_clean_uvmap_7"
    bl_label = "Remove UVMap 7"
    bl_options = {"REGISTER", "UNDO"}

    # @classmethod
    # def poll(cls, context):
    #     return (context.area.type == "VIEW_3D")

    def execute(self, context):
        selected_objs = [
            o
            for o in context.view_layer.objects.selected
            if o.type == "MESH" and o.data.polygons[:] != [] and o.visible_get()
        ]
        if selected_objs:
            for ob in selected_objs:
                uvmap_clean_by_index(ob, 7)
            tag_redraw(context)
            self.report({"INFO"}, "UVMap 8 Removed")

        else:
            self.report({"ERROR"}, "Select MESH objects.")
        return {"FINISHED"}
