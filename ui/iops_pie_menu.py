import bpy
from bpy.types import Menu
from ..utils.functions import get_addon
from ..operators.mesh_nonplanar_overlay import overlay_enabled


def op_if_poll(layout, idname, text=None, icon=None, **props):
    """Draw an operator button only when its poll() passes in the current context.

    Returns the operator properties object (like layout.operator) or None
    when the button was hidden (poll failed or operator is not registered).
    """
    module, _, func = idname.partition(".")
    try:
        if not getattr(getattr(bpy.ops, module), func).poll():
            return None
    except AttributeError:
        return None
    kwargs = {}
    if text is not None:
        kwargs["text"] = text
    if icon is not None:
        kwargs["icon"] = icon
    btn = layout.operator(idname, **kwargs)
    for key, value in props.items():
        setattr(btn, key, value)
    return btn


class IOPS_MT_Pie_Menu(Menu):
    # bl_idname = "iops.pie_menu"
    bl_label = "IOPS Pie"

    def draw(self, context):
        forgottentools, _, _, _ = get_addon("Forgotten Tools")
        optiloops, _, _, _ = get_addon("Optiloops")
        bmax_connector, _, _, _ = get_addon("BMAX Connector")
        bmoi_connector, _, _, _ = get_addon("BMOI Connector")
        # brush = context.tool_settings.image_paint.brush

        layout = self.layout
        pie = layout.menu_pie()

        # 4 - LEFT
        # pie.separator()
        # pie.operator("wm.call_menu_pie", text = "Some Other Pie 0", icon = "RIGHTARROW_THIN").name="Pie_menu"
        col = layout.menu_pie()
        box = col.column(align=True).box().column()
        box.label(text="IOPS")
        col.scale_x = 0.9
        col = box.column(align=True)
        col.prop(
            context.scene.IOPS,
            "iops_vertex_color",
            text="",
        )
        op_if_poll(col, "iops.mesh_assign_vertex_color", text="Set Vertex Color")
        col = box.column(align=True)
        row = col.row(align=True)
        op_if_poll(row, "iops.mesh_assign_vertex_color", text="White", fill_color_white=True)
        op_if_poll(row, "iops.mesh_assign_vertex_color", text="Grey", fill_color_grey=True)
        op_if_poll(row, "iops.mesh_assign_vertex_color", text="Black", fill_color_black=True)
        col = box.column(align=True)
        op_if_poll(col, "iops.mesh_assign_vertex_color_alpha", text="Set Vertex Alpha")
        col.separator()
        op_if_poll(col, "iops.materials_from_textures", text="Materials from Textures")
        col.separator()
        op_if_poll(col, "iops.object_replace", text="Object Replace")
        op_if_poll(col, "iops.object_aligner", text="Object Aligner")
        op_if_poll(col, "iops.object_radial_array", text="Radial Array")
        op_if_poll(col, "iops.object_mirror_rotate", text="Mirror Rotate")
        op_if_poll(col, "iops.object_align_between_two", text="Align Between Two")
        op_if_poll(col, "iops.mesh_quick_snap", text="Quick Snap")
        op_if_poll(col, "iops.mesh_quick_connect", text="Quick Connect")
        op_if_poll(col, "iops.mesh_to_tris_to_quads", text="Tris to Quads")
        op_if_poll(col, "iops.mesh_smart_inset", text="Smart Inset")
        op_if_poll(col, "iops.mesh_straight_bevel", text="Straight Bevel")
        op_if_poll(col, "iops.mesh_shear", text="Shear")
        op_if_poll(col, "iops.mesh_hinge", text="Hinge")
        op_if_poll(col, "iops.mesh_converge", text="Converge")
        op_if_poll(col, "iops.mesh_vert_fuse", text="Vert Fuse")
        # col.operator("iops.polygon_bevel", text="Polygon Bevel")  # WIP
        op_if_poll(col, "iops.object_drop_it", text="Drop It!")
        op_if_poll(col, "iops.object_kitbash_grid", text="Grid")
        op_if_poll(col, "iops.object_kitbash_grid", text="to Center", arrange_mode='CENTER')
        col.separator()
        op_if_poll(col, "iops.modifier_easy_array_caps", text="Easy Modifier - Array Caps")
        op_if_poll(col, "iops.modifier_easy_array_curve", text="Easy Modifier - Array Curve")
        op_if_poll(col, "iops.modifier_easy_curve", text="Easy Modifier - Curve")
        op_if_poll(col, "iops.modifier_easy_shwarp", text="Easy Modifier - SHWARP")
        col.separator()
        op_if_poll(col, "iops.assets_render_asset_thumbnail", text="Render Asset Thumbnail")
        col.separator()
        op_if_poll(col, "iops.reload_libraries", text="Reload Libraries")
        op_if_poll(col, "iops.reload_images", text="Reload Images")

        # 6 - RIGHT
        # pie.separator()

        other = pie.row()
        gap = other.column()
        gap.separator()
        gap.scale_y = 7
        other_menu = other.box().column()
        other_menu.scale_y = 1
        if bmax_connector:
            bmax_prefs = bpy.context.preferences.addons["BMAX_Connector"].preferences
            other_menu.label(text="BMax")
            if bmax_prefs.file_format == "FBX":
                op_if_poll(other_menu, "bmax.export", icon="EXPORT", text="Send to Maya/3dsmax")
                op_if_poll(other_menu, "bmax.import", icon="IMPORT", text="Get from Maya/3dsmax")
            if bmax_prefs.file_format == "USD":
                op_if_poll(other_menu, "bmax.export_usd", icon="EXPORT", text="Send to Maya/3dsmax")
                op_if_poll(other_menu, "bmax.import_usd", icon="IMPORT", text="Get from Maya/3dsmax")
            row = other_menu.row(align=True)
            row.prop(bmax_prefs, "export_reset_location", icon="EVENT_L", text="  ")
            row.prop(bmax_prefs, "export_reset_rotation", icon="EVENT_R", text="  ")
            row.prop(bmax_prefs, "export_reset_scale", icon="EVENT_S", text="  ")
            other_menu = other.box().column()
        if bmoi_connector:
            other_menu.label(text="BMoI")
            op_if_poll(other_menu, "bmoi3d.export", icon="EXPORT", text="Send to MoI3D")
            op_if_poll(other_menu, "bmoi3d.import", icon="IMPORT", text="Get from MoI3D")

        # 2 - BOTTOM
        wm = context.window_manager
        prefs = context.preferences.addons["B2RUVL"].preferences
        uvl = prefs.uvlayout_enable
        ruv = prefs.rizomuv_enable
        uvl_path = prefs.uvlayout_app_path
        ruv_path = prefs.rizomuv_app_path

        col = layout.menu_pie()
        box = col.column(align=True).box().column()
        box.label(text="B2RUVL")
        col_top = box.column(align=True)
        col_top.prop(wm.B2RUVL_PanelProperties, "uvMap")
        col_uvl = col_top.column(align=True)
        col_uvl.enabled = uvl is not False and len(uvl_path) != 0
        col_uvl.operator("b2ruvl.send_to_uvlayout")
        col_ruv = col_top.column(align=True)
        col_ruv.enabled = ruv is not False and len(ruv_path) != 0
        col_ruv.operator("b2ruvl.send_to_rizomuv")
        col_ruv.operator("b2ruvl.get_from_rizomuv")

        # 8 - TOP
        if context.mode == "EDIT_MESH":
            other = pie.column()
            gap = other.column()
            gap.separator()
            gap.scale_y = 7
            other_menu = other.box().column()
            other_menu.scale_y = 1
            other_menu.label(text="IOPS")
            # depress is a layout kwarg, not an operator prop, so this
            # one bypasses op_if_poll (poll always passes in EDIT_MESH).
            other_menu.operator("iops.mesh_nonplanar_overlay",
                                text="Non-Planar Overlay",
                                depress=overlay_enabled())
            if forgottentools:
                other_menu = other.box().column()
                other_menu.scale_y = 1
                other_menu.label(text="ForgottenTools")
                op_if_poll(other_menu, "mesh.connect_spread")
                op_if_poll(other_menu, "mesh.grid_fill_all")

                op_if_poll(other_menu, "mesh.dice_faces")
                op_if_poll(other_menu, "mesh.hinge")

                op_if_poll(other_menu, "mesh.forgotten_separate_duplicate")
                other_menu.operator(
                    "wm.call_panel", text="Selection Sets", icon="SELECT_SET"
                ).name = "MESH_PT_selection_sets_panel_frgttn"
        else:
            pie.separator()

        # 7 - TOP - LEFT
        pie.separator()
        # 9 - TOP - RIGHT
        if optiloops and context.mode == "EDIT_MESH":
            if op_if_poll(pie, "mesh.optiloops") is None:
                pie.separator()
        else:
            pie.separator()

        # 1 - BOTTOM - LEFT
        pie.separator()

        # 3 - BOTTOM - RIGHT
        pie.separator()


class IOPS_OT_Call_Pie_Menu(bpy.types.Operator):
    """IOPS Pie"""

    bl_idname = "iops.call_pie_menu"
    is_bindable = True
    bl_label = "IOPS Pie Menu"

    def execute(self, context):
        bpy.ops.wm.call_menu_pie(name="IOPS_MT_Pie_Menu")
        return {"FINISHED"}
