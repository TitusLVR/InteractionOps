# Single-color picker popup for the built-in render_passes widget
# (swatch -> iops.executor, script "render_passes_color_picker.py").
import bpy


class IOPS_OT_ExecSingleColorPicker(bpy.types.Operator):
    """Pick the viewport solid-mode Single color"""

    bl_idname = "iops.exec_single_color_picker"
    bl_label = "Single Color"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return getattr(context.space_data, "shading", None) is not None

    def draw(self, context):
        shading = context.space_data.shading
        col = self.layout.column()
        col.template_color_picker(shading, "single_color", value_slider=True)
        col.prop(shading, "single_color", text="")

    def execute(self, context):
        return {"FINISHED"}

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=240)


if not hasattr(bpy.types, "IOPS_OT_exec_single_color_picker"):
    bpy.utils.register_class(IOPS_OT_ExecSingleColorPicker)

bpy.ops.iops.exec_single_color_picker("INVOKE_DEFAULT")
