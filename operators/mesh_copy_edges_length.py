import bpy
import bmesh


def get_unit_scale():
    """Get the unit scale based on the current scene units"""
    units = bpy.data.scenes["Scene"].unit_settings.length_unit
    if units == "MICROMETERS":
        return 0.000001
    elif units == "MILLIMETERS":
        return 0.001
    elif units == "CENTIMETERS":
        return 0.01
    elif units == "METERS":
        return 1.0
    elif units == "KILOMETERS":
        return 1000.0
    elif units == "ADAPTIVE":
        return 1.0
    else:
        return 1.0


class IOPS_MESH_OT_CopyEdgesLength(bpy.types.Operator):
    """Copy the active edge length to the clipboard"""

    bl_idname = "iops.mesh_copy_edge_length"
    bl_label = "Copy Active Edge Length to Clipboard"

    @classmethod
    def poll(cls, context):
        return (
            context.mode == "EDIT_MESH"
            and context.active_object
            and context.active_object.type == "MESH"
        )

    def execute(self, context):
        active_object = context.active_object
        bm = bmesh.from_edit_mesh(active_object.data)
        bm.edges.ensure_lookup_table()
        selected_verts = [v for v in bm.verts if v.select]
        selected_edges = [e for e in bm.edges if e.select]

        if selected_edges:
            # Add the length of all selected edges and store it in the clipboard
            total_length = (
                sum(e.calc_length() for e in selected_edges) / get_unit_scale()
            )
            bpy.context.window_manager.clipboard = str(total_length)
            self.report({"INFO"}, "Copied the sum of edges' length to clipboard")
            bm.free()
            return {"FINISHED"}
        # if only 2 verts are selected, copy the distance between them
        elif len(selected_verts) == 2:
            bpy.context.window_manager.clipboard = str(
                (selected_verts[0].co - selected_verts[1].co).length
            )
            self.report(
                {"INFO"},
                "Copied the distance between the 2 selected verts to clipboard",
            )
            bm.free()
            return {"FINISHED"}
        else:
            # Invalid Selection
            self.report({"ERROR"}, "Invalid Selection")
            return {"CANCELLED"}
