import bpy
from bpy.types import Menu

from ..operators.falloff.fields import edit_mesh_poll
from ..operators.falloff.props import active_field
from ..operators.falloff.tool import TYPE_ICONS


def _draw_settings(layout, settings):
    """Active field, stack and tool settings: the bottom slot of the pie."""
    col = layout.column(align=True)
    col.ui_units_x = 9

    box = col.box()
    sub = box.column(align=True)
    f = active_field(settings)
    sub.popover("IOPS_PT_falloff_stack",
                text=f.name if f else "No Field",
                icon=TYPE_ICONS.get(f.type, "NONE") if f else "NONE")
    if f is not None:
        sub.separator()
        sub.prop(f, "type", text="")
        sub.prop(f, "curve", text="")
        sub.prop(f, "blend", text="")
        row = sub.row(align=True)
        row.prop(f, "strength")
        row.prop(f, "invert", text="", icon="ARROW_LEFTRIGHT")

    box = col.box()
    sub = box.column(align=True)
    sub.prop(settings, "basis", text="")
    row = sub.row(align=True)
    row.prop(settings, "show_weights", text="Weights", toggle=True)
    row.operator("iops.mesh_falloff_pivot_reset", text="Reset Pivot")


class IOPS_MT_Falloff_More(Menu):
    """Operations that do not fit the pie's slots."""
    bl_idname = "IOPS_MT_Falloff_More"
    bl_label = "More"

    def draw(self, context):
        col = self.layout.column()
        col.operator("iops.mesh_falloff_normal_offset", text="Normal Offset",
                     icon="NORMALS_VERTEX")
        col.separator()
        col.operator("iops.mesh_field_edge_slide", text="Field Edge Slide",
                     icon="OP_EDGE_SLIDE")
        col.operator("iops.mesh_field_offset_edge_slide", text="Field Offset Edge Slide",
                     icon="OP_OFFSET_EDGE_SLIDE")


class IOPS_MT_Pie_Falloff(Menu):
    bl_idname = "IOPS_MT_Pie_Falloff"
    bl_label = "IOPS Falloff"

    @classmethod
    def poll(cls, context):
        return edit_mesh_poll(context)

    def draw(self, context):
        settings = context.scene.IOPS.falloff
        pie = self.layout.menu_pie()
        # Blender pie fill order: W, E, S, N, NW, NE, SW, SE
        pie.operator("iops.mesh_falloff_move", text="Move", icon="CON_LOCLIKE")
        pie.operator("iops.mesh_falloff_rotate", text="Rotate", icon="CON_ROTLIKE")
        _draw_settings(pie, settings)
        pie.operator("iops.mesh_falloff_scale", text="Scale", icon="CON_SIZELIKE")
        pie.operator("iops.mesh_falloff_fit", text="Fit", icon="SHADING_BBOX")
        pie.menu("IOPS_MT_Falloff_More", text="More", icon="COLLAPSEMENU")
        pie.operator_menu_enum("iops.mesh_falloff_field_add", "type",
                               text="Add Field", icon="ADD")
        pie.operator("iops.mesh_falloff_clear", text="Clear", icon="TRASH")


class IOPS_OT_Call_Pie_Falloff(bpy.types.Operator):
    """IOPS Falloff Pie"""

    bl_idname = "iops.call_pie_falloff"
    is_bindable = True
    bl_label = "IOPS Pie Falloff"

    @classmethod
    def poll(cls, context):
        return (context.area is not None and context.area.type == "VIEW_3D"
                and edit_mesh_poll(context))

    def execute(self, context):
        bpy.ops.wm.call_menu_pie(name="IOPS_MT_Pie_Falloff")
        return {"FINISHED"}
