import bpy


class IOPS_OT_ActiveObject_Scroll_UP(bpy.types.Operator):
    """Cyclic switching properties types UP"""

    bl_idname = "iops.object_active_object_scroll_up"
    bl_label = "Cyclic switching active object in selection UP"

    def execute(self, context):
        selected_objects = bpy.context.view_layer.objects.selected
        active = bpy.context.active_object

        for index, elem in enumerate(selected_objects):
            if elem == active:
                if index <= len(selected_objects):
                    idx = index + 1
                    try:
                        bpy.context.view_layer.objects.active = selected_objects[idx]
                    except IndexError:
                        idx = 0
                        bpy.context.view_layer.objects.active = selected_objects[idx]
                else:
                    idx = 0
                    bpy.context.view_layer.objects.active = selected_objects[idx]
                self.report({"INFO"}, "Active: " + context.active_object.name)
        return {"FINISHED"}


class IOPS_OT_ActiveObject_Scroll_DOWN(bpy.types.Operator):
    """Cyclic switching snap with types UP"""

    bl_idname = "iops.object_active_object_scroll_down"
    bl_label = "Cyclic switching active object in selection DOWN"

    def execute(self, context):
        selected_objects = bpy.context.view_layer.objects.selected
        active = bpy.context.active_object

        for index, elem in enumerate(selected_objects):
            if elem == active:
                if index > 0 and index <= len(selected_objects):
                    idx = index - 1
                    try:
                        bpy.context.view_layer.objects.active = selected_objects[idx]
                    except IndexError:
                        idx = 0
                        bpy.context.view_layer.objects.active = selected_objects[idx]
                else:
                    idx = len(selected_objects) - 1
                    try:
                        bpy.context.view_layer.objects.active = selected_objects[idx]
                    except IndexError:
                        idx = 0
                        bpy.context.view_layer.objects.active = selected_objects[idx]
                self.report({"INFO"}, "Active: " + context.active_object.name)

        return {"FINISHED"}
