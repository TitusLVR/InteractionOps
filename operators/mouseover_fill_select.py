import bpy


class IOPS_MouseoverFillSelect(bpy.types.Operator):
    """Fill select faces at mouseover"""

    bl_idname = "iops.mesh_mouseover_fill_select"
    bl_label = "IOPS Mouseover Fill Select"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (
            context.object is not None
            and context.object.type == "MESH"
            and context.object.data.is_editmode
        )

    def invoke(self, context, event):
        loc = event.mouse_region_x, event.mouse_region_y
        bpy.ops.mesh.hide(unselected=False)
        bpy.ops.view3d.select(extend=True, location=loc)
        bpy.ops.mesh.select_linked(delimit={"NORMAL"})
        bpy.ops.mesh.reveal(select=True)
        return {"FINISHED"}
