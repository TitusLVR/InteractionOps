import bpy
from .. utils.functions import get_addon


class IOPS_OT_transform_orientation_create(bpy.types.Operator):
    """Tooltip"""
    bl_idname = "iops.transform_orientation_create"
    bl_label = "Create custom transformation orientation"

    def execute(self, context):
        bpy.ops.transform.create_orientation(use=True)
        return {'FINISHED'}


class IOPS_OT_homonize_uvmaps_names(bpy.types.Operator):
    """UVmaps names homonization. Make uvmap names identical"""
    bl_idname = "iops.homonize_uvmaps_names"
    bl_label = "UVmaps names homonization"

    @classmethod
    def poll(self, context):
        return (context.active_object and
                context.mode == "OBJECT" and
                context.view_layer.objects.active.type == "MESH" )

    def execute(self, context):
        objs = []
        for ob in bpy.context.selected_objects:
            if ob.type == 'MESH':
                objs.append(ob)
        if objs:
            for ob in objs:
                uv_list = ob.data.uv_layers
                if uv_list:
                    for ch in range(len(uv_list)):
                        uv_list[ch].name = "ch" + str(ch+1)
                        print (uv_list[ch].name)
        return {'FINISHED'}


class IOPS_OT_transform_orientation_delete(bpy.types.Operator):
    """Tooltip"""
    bl_idname = "iops.transform_orientation_delete"
    bl_label = "Delete custom transformation orientation "

    def execute(self, context):
        slot = bpy.context.scene.transform_orientation_slots[0]
        if slot.custom_orientation:
            bpy.ops.transform.delete_orientation()
        return {'FINISHED'}


class IOPS_OT_transform_orientation_cleanup(bpy.types.Operator):
    """Tooltip"""
    bl_idname = "iops.transform_orientation_cleanup"
    bl_label = "Transformation orientations cleanup "

    def execute(self, context):
        slots = bpy.context.scene.transform_orientation_slots
        for s in slots:
            if s.custom_orientation:
                bpy.ops.transform.select_orientation(orientation=str(s.custom_orientation.name))
                bpy.ops.transform.delete_orientation()
        return {'FINISHED'}


class IOPS_OT_edit_origin(bpy.types.Operator):
    """Tooltip"""
    bl_idname = "iops.edit_origin"
    bl_label = "Edit origin enable"

    @classmethod
    def poll(self, context):
        return (context.area.type == "VIEW_3D" and context.active_object)

    def execute(self, context):
        if context.tool_settings.use_transform_data_origin:
            bpy.context.active_object.show_in_front = context.tool_settings.use_transform_data_origin = False
        else:
            bpy.context.active_object.show_in_front = context.tool_settings.use_transform_data_origin = True
        return {'FINISHED'}


class IOPS_OT_uvmaps_cleanup(bpy.types.Operator):
    """Tooltip"""
    bl_idname = "iops.uvmaps_cleanup"
    bl_label = "UVmaps cleanup"

    @classmethod
    def poll(self, context):
        return (context.active_object and
                context.mode == "OBJECT" and
                context.view_layer.objects.active.type == "MESH" )

    def execute(self, context):
        objs = []
        for ob in bpy.context.selected_objects:
            if ob.type == 'MESH':
                objs.append(ob)

        if objs:
            for ob in objs:
                uv_list = ob.data.uv_layers.keys()
                for uv in uv_list:
                    ob.data.uv_layers.remove(ob.data.uv_layers[uv])
        return {'FINISHED'}


class IOPS_PT_TPS_Panel(bpy.types.Panel):
    """Tranformation,PivotPoint,Snapping panel"""
    bl_label = "IOPS TPS"
    bl_idname = "IOPS_PT_TPS_Panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    # bl_category = 'Item'

    @classmethod
    def poll(self, context):
        return (context.area.type == "VIEW_3D" or context.area.type == "IMAGE_EDITOR")

    def draw(self, context):
        ver = bpy.app.version[2]
        tool_settings = context.tool_settings
        scene = context.scene
        orient_slot = scene.transform_orientation_slots[0]
        orientation = orient_slot.custom_orientation
        pivot = scene.tool_settings.transform_pivot_point
        snap_elements = scene.tool_settings.snap_elements
        snap_target = scene.tool_settings.snap_target

        uebok, _, _, _ = get_addon("UnrealEngine - Blender OK!")
        machinetools, _, _, _ = get_addon("MACHIN3tools")
        batchops, _, _, _ = get_addon("Batch Operations™")

        layout = self.layout
        layout.ui_units_x = 27.5
        row = layout.row(align=True)

        row.prop(tool_settings, "use_snap", text="")
        row.prop(tool_settings, "use_mesh_automerge", text="")
        row.operator("iops.transform_orientation_create", text="", icon='ADD')
        row.separator()
        row.operator("iops.transform_orientation_cleanup", text="", icon='BRUSH_DATA')
        row.operator("iops.uvmaps_cleanup", text="", icon='UV_DATA')

        if batchops:
            row.separator()
            row.operator("batch_ops_objects.rename", text="", icon='OUTLINER_DATA_FONT').use_pattern = False

        if uebok:
            row.separator()
            row.operator('uebok.add_object_to_active_object_collection', icon='ADD', text="")
            row.operator('uebok.remove_object_from_collection', icon='REMOVE', text="")
            row.operator('uebok.outliner_make_collection_active_by_active_object', text="", icon='LAYER_ACTIVE')
            row.operator('uebok.select_collection_objects', text="", icon='RESTRICT_SELECT_OFF')

        if machinetools:
            row.separator()
            active = context.active_object
            if active:
                if active.type == "MESH":
                    mesh = active.data
                    row.operator("machin3.shade_smooth", text="", icon='NODE_MATERIAL')
                    row.operator("machin3.shade_flat", text="", icon='MATCUBE')
                    state = True if mesh.use_auto_smooth else False
                    row.operator("machin3.toggle_auto_smooth", text="", icon='AUTO', depress=state)
                    if mesh.use_auto_smooth:
                        if mesh.has_custom_normals:
                            row.operator("mesh.customdata_custom_splitnormals_clear", text="Clear Custom Normals")
                        else:
                            row.prop(mesh, "auto_smooth_angle", text="")

        if context.area.type == "VIEW_3D":
            # Column 1
            split = layout.split()
            col = split.column(align=True)
            col.label(text="Transformation:")
            col.prop(orient_slot, "type", expand=True)
            if orientation:
                col.prop(orientation, "name", text="", icon='OBJECT_ORIGIN')
                col.operator("iops.transform_orientation_delete", text="", icon='REMOVE')
            # Column 2
            col = split.column(align=True)
            col.label(text="PivotPoint:")
            col.prop(tool_settings, "transform_pivot_point", expand=True)
            if ver != 80:
                row = col.row(align=True)
                #row.prop(tool_settings, "use_transform_data_origin", text="", icon='OBJECT_ORIGIN')
                o_state = True if tool_settings.use_transform_data_origin else False
                row.operator("iops.edit_origin", text="", icon='OBJECT_ORIGIN', depress=o_state)
                row.prop(tool_settings, "use_transform_pivot_point_align", text="", icon='CENTER_ONLY')
                row.prop(tool_settings, "use_transform_skip_children", text="", icon='TRANSFORM_ORIGINS')
            else:
                col.prop(tool_settings, "use_transform_pivot_point_align", text="")
            # Column 3
            col = split.column(align=True)
            col.label(text="Snapping:")
            row = col.row(align=False)
            # Snap elements
            row.prop(tool_settings, "snap_elements", text="")
            if 'INCREMENT' in snap_elements:
                row.separator()
                row.prop(tool_settings, "use_snap_grid_absolute", text="", icon='SNAP_GRID')
            # Snap targets
            col.prop(tool_settings, "snap_target", expand=True)

            row = col.row(align=False)
            split = row.split(factor=0.5, align=True)
            row = split.row(align=True)
            row.prop(tool_settings, "use_snap_self", text="", icon='SNAP_ON')
            row.prop(tool_settings, "use_snap_align_rotation", text="", icon='SNAP_NORMAL')
            if 'FACE' in snap_elements:
                row.prop(tool_settings, "use_snap_project", text="", icon='PROP_PROJECTED')
            if 'VOLUME' in snap_elements:
                row.prop(tool_settings, "use_snap_peel_object", text="", icon='SNAP_PEEL_OBJECT')
            split = split.split()
            row = split.row(align=True)
            row.prop(tool_settings, "use_snap_translate", text="", icon='CON_LOCLIMIT')
            row.prop(tool_settings, "use_snap_rotate", text="", icon='CON_ROTLIMIT')
            row.prop(tool_settings, "use_snap_scale", text="", icon='CON_SIZELIMIT')

        if context.area.type == "IMAGE_EDITOR":
            sima = context.space_data
            show_uvedit = sima.show_uvedit
            show_maskedit = sima.show_maskedit
            uvedit = sima.uv_editor
            snap_uv_element = tool_settings.snap_uv_element
            # Column 1
            split = layout.split()
            col = split.column(align=True)
            col.label(text="UV Selection mode:")
            if show_uvedit:
                col.prop(tool_settings, "use_uv_select_sync", text="")
                if tool_settings.use_uv_select_sync:
                    col.template_edit_mode_selection()
                else:
                    col.prop(tool_settings, "uv_select_mode", expand=True)
                    col.prop(uvedit, "sticky_select_mode", icon_only=False)
            # Column 2
            col = split.column(align=True)
            col.label(text="PivotPoint:")
            # col.prop(sima, "pivot_point", icon_only=False)
            col.prop(sima, "pivot_point", expand=True)
            # Column 3
            col = split.column(align=True)
            col.label(text="Snapping:")
            if show_uvedit:
                # Snap.
                col.prop(tool_settings, "snap_uv_element", expand=True)
                if 'VERTEX' in snap_uv_element:
                    col.label(text="Target:")
                    col.prop(tool_settings, "snap_target", expand=True)
                col.label(text="Affect:")
                row = col.row(align=True)
                row.prop(tool_settings, "use_snap_translate", text="Move", toggle=True)
                row.prop(tool_settings, "use_snap_rotate", text="Rotate", toggle=True)
                row.prop(tool_settings, "use_snap_scale", text="Scale", toggle=True)


class IOPS_PT_TM_Panel(bpy.types.Panel):
    """Creates a Panel from Tranformation,PivotPoint,Snapping panels"""
    bl_label = "IOPS Transform panel"
    bl_idname = "IOPS_PT_TM_Panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    # bl_category = 'Item'
    # bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(self, context):
        return (context.area.type == "VIEW_3D" and
                len(context.view_layer.objects.selected) != 0 and
                context.view_layer.objects.active.type == "MESH" and
                bpy.context.view_layer.objects.active.mode == 'OBJECT')

    def draw(self, context):
        obj = context.view_layer.objects.active
        layout = self.layout
        layout.ui_units_x = 8.0
        col = layout.column(align=True)
        col.prop(obj, "location")
        col.prop(obj, "rotation_euler")
        col.prop(obj, "scale")
        col.prop(obj, "dimensions")

class IOPS_OT_Call_TPS_Panel(bpy.types.Operator):
    """Tranformation, PivotPoint, Snapping panel"""
    bl_idname = "iops.call_tps_panel"
    bl_label = "IOPS Transformation, PivotPoint, Snaps panel"

    @classmethod
    def poll(self, context):
        return context.area.type == "VIEW_3D"

    def execute(self, context):
        bpy.ops.wm.call_panel(name="IOPS_PT_TPS_Panel", keep_open=True)
        return {'FINISHED'}

class IOPS_OT_Call_TM_Panel(bpy.types.Operator):
    """Tranformation panel"""
    bl_idname = "iops.call_tm_panel"
    bl_label = "IOPS Transform panel"

    @classmethod
    def poll(self, context):
        return (context.area.type == "VIEW_3D" and
                len(context.view_layer.objects.selected) != 0 and
                context.view_layer.objects.active.type == "MESH" and
                bpy.context.view_layer.objects.active.mode == 'OBJECT')

    def execute(self, context):
        bpy.ops.wm.call_panel(name="IOPS_PT_TM_Panel", keep_open=True)
        return {'FINISHED'}

