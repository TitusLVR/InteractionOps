import bpy
from bpy.types import Menu


class IOPS_MT_Pie_Edit_Submenu(Menu):
    bl_label = "IOPS_MT_Pie_Edit_Submenu"

    def draw(self, context):
        layout = self.layout
        layout.label(text="IOPS Modes")
        layout.separator()
        layout.operator("object.mode_set", text="Object Mode").mode = "OBJECT"
        layout.operator("object.mode_set", text="Edit Mode").mode = "EDIT"
        layout.operator("object.mode_set", text="Sculpt Mode").mode = "SCULPT"
        layout.operator("object.mode_set", text="Vertex Paint").mode = "VERTEX_PAINT"
        layout.operator("object.mode_set", text="Weight Paint").mode = "WEIGHT_PAINT"


class IOPS_MT_Pie_Edit(Menu):
    # bl_idname = "iops.pie_menu"
    bl_label = "IOPS_MT_Pie_Edit"

    @classmethod
    def poll(self, context):
        return (
            context.area.type in {"VIEW_3D", "IMAGE_EDITOR"} and context.active_object
        )

    def draw(self, context):
        layout = self.layout
        pie = layout.menu_pie()

        if context.area.type == "VIEW_3D":
            # 4 - LEFT
            pie.operator("iops.function_f1", text="Vertex", icon="VERTEXSEL")
            # 6 - RIGHT
            pie.operator("iops.function_f3", text="Face", icon="FACESEL")
            # 2 - BOTTOM
            pie.operator("iops.function_esc", text="Esc", icon="EVENT_ESC")
            # 8 - TOP
            pie.operator("iops.function_f2", text="Edge", icon="EDGESEL")
            # 7 - TOP - LEFT
            # pie.separator()
            # 9 - TOP - RIGHT
            # pie.separator()
            # 1 - BOTTOM - LEFT
            # pie.separator()
            # 3 - BOTTOM - RIGHT
            # pie.separator()
            # Additional items underneath
            box = pie.split()
            column = box.column()
            column.scale_y = 1.5
            column.scale_x = 1.5

            row = column.row(align=True)

            # r = row.row(align=True)
            # r.active = False if context.mode == 'PAINT_GPENCIL' else True
            # r.operator("machin3.surface_draw_mode", text="", icon="GREASEPENCIL")

            # r = row.row(align=True)
            # r.active = False if context.mode == 'TEXTURE_PAINT' else True
            # r.operator("object.mode_set", text="", icon="TPAINT_HLT").mode = 'TEXTURE_PAINT'

            r = row.row(align=True)
            r.active = False if context.mode == "WEIGHT_PAINT" else True
            r.operator("object.mode_set", text="", icon="WPAINT_HLT").mode = (
                "WEIGHT_PAINT"
            )

            r = row.row(align=True)
            r.active = False if context.mode == "VERTEX_PAINT" else True
            r.operator("object.mode_set", text="", icon="VPAINT_HLT").mode = (
                "VERTEX_PAINT"
            )

            r = row.row(align=True)
            r.active = False if context.mode == "SCULPT" else True
            r.operator("object.mode_set", text="", icon="SCULPTMODE_HLT").mode = (
                "SCULPT"
            )

            r = row.row(align=True)
            r.active = False if context.mode == "OBJECT" else True
            r.operator("object.mode_set", text="", icon="OBJECT_DATA").mode = "OBJECT"

            r = row.row(align=True)
            r.active = False if context.mode == "EDIT_MESH" else True
            r.operator("object.mode_set", text="", icon="EDITMODE_HLT").mode = "EDIT"

        if context.area.type == "IMAGE_EDITOR":
            if context.tool_settings.use_uv_select_sync == True:
                # 4 - LEFT
                pie.operator("iops.function_f1", text="Vertex", icon="VERTEXSEL")
                # 6 - RIGHT
                pie.operator("iops.function_f3", text="Face", icon="FACESEL")
                # 2 - BOTTOM
                pie.operator("iops.function_esc", text="Esc", icon="EVENT_ESC")
                # 8 - TOP
                pie.operator("iops.function_f2", text="Edge", icon="EDGESEL")
                # 7 - TOP - LEFT
            elif context.tool_settings.use_uv_select_sync == False:
                # 4 - LEFT
                pie.operator("iops.function_f1", text="Vertex", icon="VERTEXSEL")
                # 6 - RIGHT
                pie.operator("iops.function_f3", text="Face", icon="FACESEL")
                # 2 - BOTTOM
                pie.operator("iops.function_esc", text="Esc", icon="EVENT_ESC")
                # 8 - TOP
                pie.operator("iops.function_f2", text="Edge", icon="EDGESEL")
                # 7 - TOP - LEFT
                pie.separator()
                # 9 - TOP - RIGHT
                pie.operator("iops.function_f4", text="Island", icon="UV_ISLANDSEL")


class IOPS_OT_Call_Pie_Edit(bpy.types.Operator):
    """IOPS Pie"""

    bl_idname = "iops.call_pie_edit"
    bl_label = "IOPS Pie Edit"

    @classmethod
    def poll(self, context):
        return (
            context.area.type in {"VIEW_3D", "IMAGE_EDITOR"} and context.active_object
        )

    def execute(self, context):
        bpy.ops.wm.call_menu_pie(name="IOPS_MT_Pie_Edit")
        return {"FINISHED"}
