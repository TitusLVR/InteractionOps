import bpy
import bmesh
from math import degrees


class IOPS_MESH_OT_CopyEdgesAngle(bpy.types.Operator):
    """Copy the angle between 2 selected edges"""

    bl_idname = "iops.mesh_copy_edges_angle"
    bl_label = "Copy Edges Angle"

    @classmethod
    def poll(cls, context):
        return (
            context.mode == "EDIT_MESH"
            and context.active_object
            and context.active_object.type == "MESH"
        )

    def edge_vector(self, edge):
        v1, v2 = edge.verts
        return (v2.co - v1.co).normalized()

    def execute(self, context):
        active_object = context.active_object
        bm = bmesh.from_edit_mesh(active_object.data)
        bm.edges.ensure_lookup_table()

        selected_edges = [e for e in bm.edges if e.select]

        if len(selected_edges) == 2:
            vec1 = self.edge_vector(selected_edges[0])
            vec2 = self.edge_vector(selected_edges[1])

            # Calculate angle in degrees
            angle_rad = vec1.angle(vec2)
            angle_deg = degrees(angle_rad)

            if angle_deg == 0:
                self.report({"WARNING"}, "Edges do not intersect")
                return {"FINISHED"}

            self.report({"INFO"}, f"Copied {angle_deg} to clipboard")

            bpy.context.window_manager.clipboard = str(angle_deg)
            bm.free()
            return {"FINISHED"}

        else:
            self.report({"ERROR"}, "Select only 2 edges.")
            return {"CANCELLED"}
