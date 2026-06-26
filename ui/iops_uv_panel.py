"""UV Tools sidebar panel (Image Editor, iOps tab).

Gathers the addon's UV-context operators as buttons. Buttons are always
shown; each operator's own poll() guards execution (e.g. drag_snap_uv needs
edit-mode + selected mesh)."""

import bpy


class IOPS_PT_UV_Panel(bpy.types.Panel):
    """IOPS UV Tools"""

    bl_label = "IOPS UV Tools"
    bl_idname = "IOPS_PT_UV_Panel"
    bl_space_type = "IMAGE_EDITOR"
    bl_region_type = "UI"
    bl_category = "iOps"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.scale_y = 1.1
        col.operator("iops.uv_info_rect", icon="MESH_PLANE", text="UV Info Rect")
        col.operator("iops.uv_drag_snap_uv", icon="SNAP_ON", text="Drag Snap UV")
