import bpy
import bmesh

from bpy.props import (
    BoolProperty,
)


class IOPS_OT_Mesh_UV_Channel_Hop(bpy.types.Operator):
    """Cyclic switching uv channels and uv seams on active object"""

    bl_idname = "iops.mesh_uv_channel_hop"
    bl_label = "Object UV Channel Hop"
    bl_options = {"REGISTER", "UNDO"}

    mark_seam: BoolProperty(
        name="Mark Seams", description="Mark seams by UV Islands", default=True
    )
    hop_previous: BoolProperty(
        name="Hop to Previous", description="Hop to previous UV Channel", default=False
    )
    set_render: BoolProperty(
        name="Set Render Channel", description="Set Render Channel", default=True
    )

    @classmethod
    def poll(cls, context):
        return (
            context.area.type == "VIEW_3D"
            and context.active_object
            and context.active_object.type == "MESH"
            and context.active_object.mode == "EDIT"
        )

    def execute(self, context):
        # Switch UV Channel by modulo of uv_layers length and set render channel
        ob = context.active_object
        me = ob.data
        # save curentrly selected faces, deselect all faces, select all faces
        bm = bmesh.from_edit_mesh(me)
        # list of selected faces
        selected_faces = [f for f in bm.faces if f.select]
        # Deselect all and select all faces
        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.mesh.select_all(action="SELECT")
        # switch uv channel
        if self.hop_previous:
            ob.data.uv_layers.active_index = (ob.data.uv_layers.active_index - 1) % len(
                ob.data.uv_layers
            )
        else:
            ob.data.uv_layers.active_index = (ob.data.uv_layers.active_index + 1) % len(
                ob.data.uv_layers
            )
        # clear seams and mark seams by UV Islands
        if self.mark_seam:
            bpy.ops.mesh.mark_seam(clear=True)
            bpy.ops.uv.select_all(action="SELECT")
            bpy.ops.uv.seams_from_islands(mark_seams=True)
        # set active render channel
        if self.set_render:
            ob.data.uv_layers[ob.data.uv_layers.active_index].active_render = True
        # Deselect all and select previously selected faces
        bpy.ops.mesh.select_all(action="DESELECT")
        # Restore selection from selected_faces list
        if selected_faces:
            for f in selected_faces:
                f.select = True
            bmesh.update_edit_mesh(me)
        # Get active render channel
        active_render = ""
        for uv_layer in ob.data.uv_layers:
            if uv_layer.active_render:
                active_render = uv_layer.name
        # Print report
        self.report(
            {"INFO"},
            f"UV Active Channel: {ob.data.uv_layers.active.name}, UV Active Render: {active_render}",
        )
        return {"FINISHED"}
