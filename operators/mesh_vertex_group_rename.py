import bpy


class IOPS_OT_VertexGroupRenameActive(bpy.types.Operator):
    """Rename the active vertex group via a popup"""

    bl_idname = "iops.vertex_group_rename_active"
    bl_label = "Rename Active Group"
    bl_description = "Rename the active vertex group of the active object"
    bl_options = {"REGISTER", "UNDO"}

    name: bpy.props.StringProperty(
        name="Name",
        description="New name for the active vertex group",
        default="",
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.vertex_groups.active is not None

    def invoke(self, context, event):
        self.name = context.active_object.vertex_groups.active.name
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.activate_init = True
        self.layout.prop(self, "name", text="")

    def execute(self, context):
        vg = context.active_object.vertex_groups.active
        new_name = self.name.strip()
        if not new_name:
            self.report({"WARNING"}, "Vertex group name cannot be empty")
            return {"CANCELLED"}
        if new_name == vg.name:
            return {"FINISHED"}
        vg.name = new_name
        if vg.name != new_name:
            # Blender de-duplicated the name against another group
            self.report({"INFO"}, f"Renamed to '{vg.name}' (name was taken)")
        return {"FINISHED"}
