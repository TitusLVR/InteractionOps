import bpy
from ..utils.functions import get_addon


class IOPS_OT_transform_orientation_create(bpy.types.Operator):
    """Tooltip"""

    bl_idname = "iops.transform_orientation_create"
    bl_label = "Create custom transformation orientation"

    def execute(self, context):
        bpy.ops.transform.create_orientation(use=True)
        return {"FINISHED"}


class IOPS_OT_homonize_uvmaps_names(bpy.types.Operator):
    """UVmaps names homonization. Make uvmap names identical"""

    bl_idname = "iops.homonize_uvmaps_names"
    bl_label = "UVmaps names homonization"

    @classmethod
    def poll(self, context):
        return (
            context.active_object
            and context.mode == "OBJECT"
            and context.view_layer.objects.active.type == "MESH"
        )

    def execute(self, context):
        objs = []
        for ob in bpy.context.selected_objects:
            if ob.type == "MESH":
                objs.append(ob)
        if objs:
            for ob in objs:
                uv_list = ob.data.uv_layers
                if uv_list:
                    for ch in range(len(uv_list)):
                        uv_list[ch].name = "ch" + str(ch + 1)
                        print(uv_list[ch].name)
        return {"FINISHED"}


class IOPS_OT_transform_orientation_delete(bpy.types.Operator):
    """Tooltip"""

    bl_idname = "iops.transform_orientation_delete"
    bl_label = "Delete custom transformation orientation "

    def execute(self, context):
        slot = bpy.context.scene.transform_orientation_slots[0]
        if slot.custom_orientation:
            bpy.ops.transform.delete_orientation()
        return {"FINISHED"}


class IOPS_OT_transform_orientation_cleanup(bpy.types.Operator):
    """Tooltip"""

    bl_idname = "iops.transform_orientation_cleanup"
    bl_label = "Transformation orientations cleanup "

    def execute(self, context):
        slots = bpy.context.scene.transform_orientation_slots
        for s in slots:
            if s.custom_orientation:
                bpy.ops.transform.select_orientation(
                    orientation=str(s.custom_orientation.name)
                )
                bpy.ops.transform.delete_orientation()
        return {"FINISHED"}


class IOPS_OT_edit_origin(bpy.types.Operator):
    """Tooltip"""

    bl_idname = "iops.edit_origin"
    bl_label = "Edit origin enable"

    @classmethod
    def poll(self, context):
        return context.area.type == "VIEW_3D" and context.active_object

    def execute(self, context):
        if context.tool_settings.use_transform_data_origin:
            bpy.context.active_object.show_in_front = (
                context.tool_settings.use_transform_data_origin
            ) = False
        else:
            bpy.context.active_object.show_in_front = (
                context.tool_settings.use_transform_data_origin
            ) = True
        return {"FINISHED"}


class IOPS_OT_uvmaps_cleanup(bpy.types.Operator):
    """Tooltip"""

    bl_idname = "iops.uvmaps_cleanup"
    bl_label = "UVmaps cleanup"

    @classmethod
    def poll(self, context):
        return (
            context.active_object
            and context.mode == "OBJECT"
            and context.view_layer.objects.active.type == "MESH"
        )

    def execute(self, context):
        objs = []
        for ob in bpy.context.selected_objects:
            if ob.type == "MESH":
                objs.append(ob)

        if objs:
            for ob in objs:
                uv_list = ob.data.uv_layers.keys()
                for uv in uv_list:
                    ob.data.uv_layers.remove(ob.data.uv_layers[uv])
        return {"FINISHED"}


class IOPS_PT_TPS_Panel(bpy.types.Panel):
    """Tranformation,PivotPoint,Snapping panel"""

    bl_label = "IOPS TPS"
    bl_idname = "IOPS_PT_TPS_Panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    # bl_category = 'Item'

    def draw(self, context):
        # ver = bpy.app.version[2]
        prefs = context.preferences
        inputs = prefs.inputs
        tool_settings = context.tool_settings
        view = context.space_data
        scene = context.scene
        orient_slot = scene.transform_orientation_slots[0]
        orientation = orient_slot.custom_orientation
        # snap_elements = scene.tool_settings.snap_elements
        snap_elements = scene.tool_settings.snap_elements_base

        ueops, _, _, _ = get_addon("Unreal OPS")
        machinetools, _, _, _ = get_addon("MACHIN3tools")
        batchops, _, _, _ = get_addon("Batch Operations™")

        layout = self.layout
        layout.ui_units_x = 27.5
        row = layout.row(align=True)
        try:
            if context.area.type == "VIEW_3D":
                row.prop(view, "lock_cursor", text="", icon="ORIENTATION_CURSOR")
                inputs.use_mouse_depth_navigate = not view.lock_cursor
                row.separator()
                row.prop(inputs, "use_rotate_around_active", text="", icon="ORIENTATION_GIMBAL")
                row.separator()
                row.prop(tool_settings, "use_mesh_automerge", text="")
                row.prop(
                    tool_settings, "use_mesh_automerge_and_split", text="", icon="MOD_BOOLEAN"
                )
                row.separator()
                row.prop(
                    tool_settings, "use_transform_correct_face_attributes", text="", icon="UV"
                )
                row.prop(
                    tool_settings,
                    "use_transform_correct_keep_connected",
                    text="",
                    icon="STICKY_UVS_LOC",
                )

                row.prop(
                    tool_settings, "use_edge_path_live_unwrap", text="", icon="UV_SYNC_SELECT"
                )
                row.separator()
                row.operator("iops.transform_orientation_create", text="", icon="ADD")
                row.separator()
                row.operator("iops.homonize_uvmaps_names", text="", icon="UV_DATA")
                row.operator("iops.uvmaps_cleanup", text="", icon="BRUSH_DATA")
                row.operator("iops.object_name_from_active", text="", icon="OUTLINER_DATA_FONT")

                if batchops:
                    row.separator()
                    row.operator(
                        "batch_ops_objects.rename", text="", icon="OUTLINER_DATA_FONT"
                    ).use_pattern = False

                if ueops:
                    row.separator()
                    row.operator(
                        "ueops.add_object_to_active_object_collection", icon="ADD", text=""
                    )
                    row.operator("ueops.remove_object_from_collection", icon="REMOVE", text="")
                    row.operator(
                        "ueops.outliner_make_collection_active_by_active_object",
                        text="",
                        icon="LAYER_ACTIVE",
                    )
                    row.operator(
                        "ueops.select_collection_objects", text="", icon="RESTRICT_SELECT_OFF"
                    )
                    row.operator("ueops.cleanup_empty_collections", text="", icon="PANEL_CLOSE")

                if (
                    machinetools
                    and context.preferences.addons[
                        "MACHIN3tools"
                    ].preferences.activate_shading_pie
                ):
                    row.separator()
                    active = context.active_object
                    if active:
                        if active.type == "MESH":
                            mesh = active.data
                            row.operator(
                                "machin3.shade", text="", icon="NODE_MATERIAL"
                            ).shade_type = "SMOOTH"
                            row.operator(
                                "machin3.shade", text="", icon="MATCUBE"
                            ).shade_type = "FLAT"
                            try:
                                state = mesh.use_auto_smooth
                            except AttributeError:
                                state = False
                            row.operator(
                                "machin3.toggle_auto_smooth",
                                text="",
                                icon="AUTO",
                                depress=state,
                            )

                        if bpy.app.version < (4, 1, 0):
                            if mesh.use_auto_smooth:
                                if mesh.has_custom_normals:
                                    row.operator(
                                        "iops.object_clear_normals",
                                        text="",
                                        icon="COLORSET_06_VEC",
                                    )
                                else:
                                    row.prop(mesh, "auto_smooth_angle", text="")
                            row.scale_x = 0.25
                            row.operator("machin3.toggle_auto_smooth", text="30").angle = 30
                            row.operator("machin3.toggle_auto_smooth", text="60").angle = 60
                            row.operator("machin3.toggle_auto_smooth", text="90").angle = 90
                            row.operator("machin3.toggle_auto_smooth", text="180").angle = 180
                        else:
                            if bpy.types.IOPS_OT_object_clear_normals.poll(context):
                                row.operator(
                                    "iops.object_clear_normals", text="", icon="COLORSET_06_VEC"
                                )
                            row.scale_x = 0.25
                            row.operator("iops.object_auto_smooth", text="30").angle = 30
                            row.operator("iops.object_auto_smooth", text="60").angle = 60
                            row.operator("iops.object_auto_smooth", text="90").angle = 90
                            row.operator("iops.object_auto_smooth", text="180").angle = 180
                        row.scale_x = 1
                col = layout.column(align=True)
                col.separator()
                row = layout.row(align=True)
                grid_flow = row.grid_flow(
                    row_major=False,
                    columns=4,
                    even_columns=False,
                    even_rows=True,
                    align=False,
                )
                # Column 1
                col = grid_flow.column(align=True)
                # col.label(text="Transformation:")
                col.alignment = "CENTER"
                row = col.row(align=True)
                row.operator("wm.context_toggle", text="M", icon='CHECKBOX_HLT' if context.space_data.show_gizmo_object_translate else 'CHECKBOX_DEHLT').data_path = 'space_data.show_gizmo_object_translate'
                row.operator("wm.context_toggle", text="R", icon='CHECKBOX_HLT' if context.space_data.show_gizmo_object_rotate else 'CHECKBOX_DEHLT').data_path = 'space_data.show_gizmo_object_rotate'
                row.operator("wm.context_toggle", text="S", icon='CHECKBOX_HLT' if context.space_data.show_gizmo_object_scale else 'CHECKBOX_DEHLT').data_path = 'space_data.show_gizmo_object_scale'
                col.separator()
                col.prop(orient_slot, "type", expand=True)
                if orientation:
                    col.prop(orientation, "name", text="", icon="OBJECT_ORIGIN")
                    col.operator(
                        "iops.transform_orientation_delete", text="", icon="REMOVE"
                    )
                # Column 2
                col = grid_flow.column(align=True)
                # col.label(text="PivotPoint:")
                col.alignment = "CENTER"
                col.prop(tool_settings, "transform_pivot_point", expand=True)
                col.separator()                   
                if bpy.app.version > (2, 80, 0):
                    row = col.row(align=True)
                    # row.prop(tool_settings, "use_transform_data_origin", text="", icon='OBJECT_ORIGIN')
                    o_state = True if tool_settings.use_transform_data_origin else False
                    row.operator(
                        "iops.edit_origin", text="", icon="OBJECT_ORIGIN", depress=o_state
                    )
                    row.separator()
                    row.prop(
                        tool_settings,
                        "use_transform_pivot_point_align",
                        text="",
                        icon="CENTER_ONLY",
                    )
                    row.separator()
                    row.prop(
                        tool_settings,
                        "use_transform_skip_children",
                        text="",
                        icon="TRANSFORM_ORIGINS",
                    )
                    row.separator()
                    row.alignment="LEFT"
                else:
                    col.prop(tool_settings, "use_transform_pivot_point_align", text="")
                    col.alignment = "CENTER"
                # Column 3
                col = grid_flow.column(align=True)
                # col.label(text="Snapping:")
                row = col.row(align=False)
                row.alignment="LEFT"
                # Snap elements
                row.prop(tool_settings, "snap_elements", text="")
                col.separator()
                # if "INCREMENT" in snap_elements:
                #     row.separator()
                #     row.prop(
                #         tool_settings, "use_snap_grid_absolute", text="", icon="SNAP_GRID"
                #     )
                # Snap targets
                col.prop(tool_settings, "snap_target", expand=True)
                col.separator()
                row = col.row(align=True)
                row.alignment="LEFT"
                # split = row.split(factor=0.5, align=True)
                # row = split.row(align=True)
                row.prop(tool_settings, "use_snap_self", text="", icon="SNAP_ON")
                row.prop(
                    tool_settings, "use_snap_align_rotation", text="", icon="SNAP_NORMAL"
                )
                row.separator()

                if "VOLUME" in snap_elements:
                    row.prop(
                        tool_settings,
                        "use_snap_peel_object",
                        text="",
                        icon="SNAP_PEEL_OBJECT",
                    )
                    row.separator()
                if "FACE_NEAREST" in snap_elements:
                    row.prop(
                        tool_settings,
                        "se_snap_to_same_target",
                        text="",
                        icon="GP_CAPS_ROUND",
                    )
                    row.separator()

                # split = split.split()
                # row = split.row(align=True)
                row.prop(tool_settings, "use_snap_backface_culling", text="", icon="XRAY")
                row.separator()
                row.prop(
                    tool_settings,
                    "use_snap_selectable",
                    text="",
                    icon="RESTRICT_SELECT_OFF",
                )
                row.separator()
                row.prop(tool_settings, "use_snap_translate", text="", icon="CON_LOCLIMIT")
                row.prop(tool_settings, "use_snap_rotate", text="", icon="CON_ROTLIMIT")
                row.prop(tool_settings, "use_snap_scale", text="", icon="CON_SIZELIMIT")

                #Rotate increment
                col.separator()
                row = col.row(align=True)
                row.prop(tool_settings, "snap_angle_increment_3d", text="")
                row.prop(tool_settings, "snap_angle_increment_3d_precision", text="")

                # Column 4
                col = grid_flow.column(align=True)
                col.label(text=" ")
                row = col.row(align=True)
                col = row.column(align=True)
                col.operator("iops.set_snap_combo", text="", icon="EVENT_A").idx = 1
                col.operator("iops.set_snap_combo", text="", icon="EVENT_B").idx = 2
                col.operator("iops.set_snap_combo", text="", icon="EVENT_C").idx = 3
                col.operator("iops.set_snap_combo", text="", icon="EVENT_D").idx = 4
                col.operator("iops.set_snap_combo", text="", icon="EVENT_E").idx = 5
                col.operator("iops.set_snap_combo", text="", icon="EVENT_F").idx = 6
                col.operator("iops.set_snap_combo", text="", icon="EVENT_G").idx = 7
                col.operator("iops.set_snap_combo", text="", icon="EVENT_H").idx = 8

                # col.prop(prefs, "snap_combo_list", expand=True, text="")
                # col.operator("iops.save_snap_combo", text="", icon="ADD")
        except AttributeError:
            pass

        try:
            if context.area.type == "IMAGE_EDITOR":
                sima = context.space_data
                show_uvedit = sima.show_uvedit
                snap_uv_element = tool_settings.snap_uv_element
                # ima = sima.image
                show_uvedit = sima.show_uvedit
                # uvedit = sima.uv_editor

                # Main row of buttons
                row = layout.row(align=True)
                row.operator("iops.reload_images", text="", icon="FILE_REFRESH")
                row.separator()
                row.prop(sima, "display_channels", icon_only=True, expand=True)
                # row.prop(sima, "display_channels", icon="IMAGE_RGB_ALPHA").value = "COLOR_ALPHA"
                # row.prop(sima, "display_channels", icon="IMAGE_RGB").value = "COLOR"
                # row.prop(sima, "display_channels", icon="IMAGE_ALPHA").value = "ALPHA"
                # row.prop(sima, "display_channels", icon="COLOR_RED").value = "RED"
                # row.prop(sima, "display_channels", icon="COLOR_GREEN").value = "GREEN"
                # row.prop(sima, "display_channels", icon="COLOR_BLUE").value = "BLUE"
                row.separator()
                row.prop(sima, "show_repeat", text="", icon="IMAGE_PLANE")

                if context.active_object.type == "MESH" and context.mode == "EDIT_MESH":
                    # Columns begin
                    row = layout.row(align=True)
                    grid_flow = row.grid_flow(
                        row_major=True,
                        columns=3,
                        even_columns=True,
                        even_rows=True,
                        align=False,
                    )
                    # Column 1
                    col = grid_flow.column(align=True)
                    # Column 1
                    col.label(text="UV Selection mode:")
                    if show_uvedit:
                        col.prop(tool_settings, "use_uv_select_sync", text="")
                        col.separator()
                        if tool_settings.use_uv_select_sync:
                            col.template_edit_mode_selection()
                        else:
                            col.prop(tool_settings, "uv_select_mode", expand=True)
                            col.separator()
                            col.prop(tool_settings, "uv_sticky_select_mode", text="")
                    # Column 2
                    col = grid_flow.column(align=True)
                    col.label(text="PivotPoint:")
                    # col.prop(sima, "pivot_point", icon_only=False)
                    col.prop(sima, "pivot_point", expand=True)
                    # Column 3
                    col = grid_flow.column(align=True)
                    col.label(text="Snapping:")
                    if show_uvedit:
                        # Snap.
                        col.prop(tool_settings, "snap_uv_element", expand=True)
                        if "VERTEX" in snap_uv_element:
                            col.label(text="Target:")
                            col.prop(tool_settings, "snap_target", expand=True)
                        col.label(text="Affect:")
                        row = col.row(align=True)
                        row.prop(
                            tool_settings, "use_snap_translate", text="Move", toggle=True
                        )
                        row.prop(
                            tool_settings, "use_snap_rotate", text="Rotate", toggle=True
                        )
                        row.prop(tool_settings, "use_snap_scale", text="Scale", toggle=True)
                        col.separator()
                        row = col.row(align=True)
                        row.prop(tool_settings, "snap_angle_increment_2d", text="")
                        row.prop(tool_settings, "snap_angle_increment_2d_precision", text="")
        except AttributeError:
            pass


class IOPS_PT_TM_Panel(bpy.types.Panel):
    """Transform panel"""

    bl_label = "IOPS Transform panel"
    bl_idname = "IOPS_PT_TM_Panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    # bl_category = 'Item'
    # bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        obj = context.view_layer.objects.active
        layout = self.layout
        layout.ui_units_x = 8.0
        col = layout.column(align=True)
        col.prop(obj, "location")
        col.prop(obj, "rotation_euler")
        col.prop(obj, "scale")
        if getattr(obj, "dimensions", False) and obj.type in [
            "MESH",
            "CURVE",
            "FONT",
            "ARMATURE",
            "META",
            "GPENCIL",
        ]:
            col.prop(obj, "dimensions")


class IOPS_OT_Call_TPS_Panel(bpy.types.Operator):
    """Tranformation, PivotPoint, Snapping panel"""

    bl_idname = "iops.call_panel_tps"
    bl_label = "IOPS Transformation, PivotPoint, Snaps panel"

    @classmethod
    def poll(self, context):
        return context.area.type == "VIEW_3D" or context.area.type == "IMAGE_EDITOR"

    def execute(self, context):
        bpy.ops.wm.call_panel(name="IOPS_PT_TPS_Panel", keep_open=True)
        return {"FINISHED"}


class IOPS_OT_Call_TM_Panel(bpy.types.Operator):
    """Call Tranformation panel"""

    bl_idname = "iops.call_panel_tm"
    bl_label = "IOPS Transform panel"

    @classmethod
    def poll(self, context):
        return (
            context.area.type == "VIEW_3D"
            and len(context.view_layer.objects.selected) != 0
            and context.view_layer.objects.active.type
            in [
                "MESH",
                "CURVE",
                "EMPTY",
                "FONT",
                "LIGHT",
                "CAMERA",
                "ARMATURE",
                "LATTICE",
                "META",
                "SPEAKER",
                "GPENCIL",
                "SURFACE",
                "VOLUME",
                "LIGHT_PROBE",
            ]
            and bpy.context.view_layer.objects.active.mode == "OBJECT"
        )

    def execute(self, context):
        bpy.ops.wm.call_panel(name="IOPS_PT_TM_Panel", keep_open=True)
        return {"FINISHED"}


class IOPS_PT_VCol_Panel(bpy.types.Panel):
    """VCOL"""

    bl_label = "IOPS Vertex Color"
    bl_idname = "IOPS_PT_VCol_Panel"
    bl_space_type = "VIEW_3D"
    # bl_context = "mesh_edit"
    bl_region_type = "UI"
    bl_category = "iOps"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        # wm = context.window_manager
        # props = wm.IOPS_AddonProperties
        # tool_settings = context.tool_settings
        settings = context.tool_settings.image_paint
        brush = context.tool_settings.image_paint.brush

        layout = self.layout
        col = layout.column(align=True)
        col.prop(brush, "color", text="")
        if context.mode == "OBJECT":
            layout.template_ID(settings, "palette", new="palette.new")
            if settings.palette:
                layout.template_palette(settings, "palette", color=True)
        col.operator("iops.assign_vertex_color", icon="GROUP_VCOL", text="Set Color")
        col.separator()
        col.operator(
            "iops.assign_vertex_color_alpha", icon="GROUP_VCOL", text="Set Alpha"
        )
