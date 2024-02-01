import bpy
import bmesh
from bpy.props import FloatProperty


class IOPS_OT_mesh_to_grid(bpy.types.Operator):
    """Gridify vertex position"""

    bl_idname = "iops.mesh_to_grid"
    bl_label = "IOPS mesh_to_grid"
    bl_options = {"REGISTER", "UNDO"}

    base: FloatProperty(
        name="Base",
        description="Nearest grid number in scene units (0.01 = 1cm, 10 = 10m)",
        default=0.01,
        soft_min=0.01,
        soft_max=10,
    )

    @classmethod
    def poll(cls, context):
        return context.mode == "EDIT_MESH" and context.area.type == "VIEW_3D"

    def round_to_base(self, coord, base):
        return base * round(coord / base)

    def execute(self, context):
        dg = bpy.context.evaluated_depsgraph_get()
        ob = context.view_layer.objects.active
        bm = bmesh.from_edit_mesh(ob.data)

        for v in bm.verts:
            pos_x = self.round_to_base(v.co[0], self.base)
            pos_y = self.round_to_base(v.co[1], self.base)
            pos_z = self.round_to_base(v.co[2], self.base)

            v.co = (pos_x, pos_y, pos_z)

        bmesh.update_edit_mesh(ob.data)
        dg.update()
        self.report({"INFO"}, "Vertices snapped to grid")
        return {"FINISHED"}
