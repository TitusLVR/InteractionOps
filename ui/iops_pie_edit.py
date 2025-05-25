import bpy
import os
from bpy.types import Menu


def get_text_icon(context, operator):
    if context.object.type == "MESH":
        match operator:
            case "f1":
                return "Vertex", "VERTEXSEL"
            case "f2":
                return "Edge", "EDGESEL"
            case "f3":
                return "Face", "FACESEL"
            case "esc":
                return "Esc", "EVENT_ESC"
    elif context.object.type == "ARMATURE":
        match operator:
            case "f1":
                return "Edit Mode", "EDITMODE_HLT"
            case "f2":
                return "Pose Mode", "POSE_HLT"
            case "f3":
                return "Set Parent to Bone", "BONE_DATA"
            case "esc":
                return "Esc", "EVENT_ESC"
    elif context.object.type == "EMPTY":
        match operator:
            case "f1":
                return "Open Instance Collection .blend", "FILE_BACKUP"
            case "f2":
                return "Make instance real", "OUTLINER_OB_GROUP_INSTANCE"
            case "f3":
                return "F3", "EVENT_F3"
            case _:
                return "Esc", "EVENT_ESC"


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
            # Open Linked Library Blend
            if (
                context.object.type == "EMPTY"
                and context.object.instance_collection
                and context.object.instance_type == "COLLECTION"
                # and context.object.instance_collection.library
            ):
                pie.separator()
                pie.separator()

                op = pie.operator("machin3.assemble_instance_collection", text="Expand Collection to Scene")

                if context.object.instance_collection.library:
                    blendpath = os.path.abspath(
                        bpy.path.abspath(
                            context.object.instance_collection.library.filepath
                        )   
                    )
                    library = context.object.instance_collection.library.name

                    op = pie.operator(
                        "machin3.open_library_blend",
                        text=f"Open {os.path.basename(blendpath)}",
                    )
                    op.blendpath = blendpath
                    op.library = library



            # Curve
            elif context.object.type == "CURVE":
                # 4 - LEFT
                pie.separator()
                # 6 - RIGHT
                pie.separator()
                # 2 - BOTTOM
                pie.operator("iops.function_esc", text="Esc", icon="EVENT_ESC")
                # 8 - TOP
                pie.operator("iops.function_f1", text="Edit", icon="CURVE_DATA")

            else:
                # 4 - LEFT
                pie.operator(
                    "iops.function_f1",
                    text=get_text_icon(context, "f1")[0],
                    icon=get_text_icon(context, "f1")[1],
                )
                # 6 - RIGHT
                pie.operator(
                    "iops.function_f3",
                    text=get_text_icon(context, "f3")[0],
                    icon=get_text_icon(context, "f3")[1],
                )
                # 2 - BOTTOM
                pie.operator(
                    "iops.function_esc",
                    text=get_text_icon(context, "esc")[0],
                    icon=get_text_icon(context, "esc")[1],
                )
                # 8 - TOP
                pie.operator(
                    "iops.function_f2",
                    text=get_text_icon(context, "f2")[0],
                    icon=get_text_icon(context, "f2")[1],
                )

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
                if context.object.type in {"MESH"}:
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
                    r.operator(
                        "object.mode_set", text="", icon="SCULPTMODE_HLT"
                    ).mode = "SCULPT"

                    r = row.row(align=True)
                    r.active = False if context.mode == "OBJECT" else True
                    r.operator("object.mode_set", text="", icon="OBJECT_DATA").mode = (
                        "OBJECT"
                    )

                    r = row.row(align=True)
                    r.active = False if context.mode == "EDIT_MESH" else True
                    r.operator("object.mode_set", text="", icon="EDITMODE_HLT").mode = (
                        "EDIT"
                    )

        elif context.area.type == "IMAGE_EDITOR":
            if context.tool_settings.use_uv_select_sync:
                # 4 - LEFT
                pie.operator("iops.function_f1", text="Vertex", icon="VERTEXSEL")
                # 6 - RIGHT
                pie.operator("iops.function_f3", text="Face", icon="FACESEL")
                # 2 - BOTTOM
                pie.operator("iops.function_esc", text="Esc", icon="EVENT_ESC")
                # 8 - TOP
                pie.operator("iops.function_f2", text="Edge", icon="EDGESEL")
                # 7 - TOP - LEFT
            elif not context.tool_settings.use_uv_select_sync:
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
