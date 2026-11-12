"""UV Align pie for the UV Editor (edit mode).

Slot labels follow the current select mode: vertex/edge -> selected UVs line
up, face/island -> whole islands move.
"""
import bpy
from bpy.types import Menu

from ..operators.uv_align_contextual import uv_align_mode

# (direction, point label, island label, icon) in Blender pie fill order:
# W, E, S, N, NW, NE, SW, SE
UV_ALIGN_PIE_SLOTS = (
    ("W", "Left", "Islands Left", "TRIA_LEFT"),
    ("E", "Right", "Islands Right", "TRIA_RIGHT"),
    ("S", "Bottom", "Islands Bottom", "TRIA_DOWN"),
    ("N", "Top", "Islands Top", "TRIA_UP"),
    ("CENTER_X", "Center X", "Islands Center X", "ALIGN_CENTER"),
    ("CENTER_Y", "Center Y", "Islands Center Y", "ALIGN_MIDDLE"),
    ("WORLD_UP", "World Up", "World Up", "WORLD"),
    ("FOLLOW_ACTIVE", "Follow Active", "Islands Follow Active", "FACESEL"),
)


def _uv_edit_context(context):
    return (
        context.area is not None
        and context.area.type == "IMAGE_EDITOR"
        and context.mode == "EDIT_MESH"
    )


class IOPS_MT_Pie_UV_Align(Menu):
    bl_idname = "IOPS_MT_Pie_UV_Align"
    bl_label = "IOPS UV Align"

    @classmethod
    def poll(cls, context):
        return _uv_edit_context(context)

    def draw(self, context):
        island = uv_align_mode(context) == "ISLAND"
        pie = self.layout.menu_pie()
        for direction, p_label, i_label, icon in UV_ALIGN_PIE_SLOTS:
            pie.operator(
                "iops.uv_align_contextual",
                text=i_label if island else p_label,
                icon=icon,
            ).direction = direction


class IOPS_OT_UV_Call_Pie_Align(bpy.types.Operator):
    """IOPS UV Align Pie"""

    bl_idname = "iops.uv_call_pie_align"
    is_bindable = True
    bl_label = "IOPS Pie UV Align"

    @classmethod
    def poll(cls, context):
        return _uv_edit_context(context)

    def execute(self, context):
        bpy.ops.wm.call_menu_pie(name="IOPS_MT_Pie_UV_Align")
        return {"FINISHED"}
