import bpy


def get_addon(addon, debug=False):
    import addon_utils

    # look for addon by name and find folder name and path
    # Note, this will also find addons that aren't registered!

    for mod in addon_utils.modules():
        name = mod.bl_info["name"]
        version = mod.bl_info.get("version", None)
        foldername = mod.__name__
        path = mod.__file__
        enabled = addon_utils.check(foldername)[1]

        if name == addon:
            return enabled, foldername, version, path

    return False, None, None, None


class IOPS_OT_transform_orientation_create(bpy.types.Operator):
    """Tooltip"""
    bl_idname = "iops.transform_orientation_create"
    bl_label = "Create custom transformation orientation"

    def execute(self, context):
        bpy.ops.transform.create_orientation(use=True)
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


class IOPS_OT_uvmaps_cleanup(bpy.types.Operator):
    """Tooltip"""
    bl_idname = "iops.uvmaps_cleanup"
    bl_label = "UVmaps cleanup"

    @classmethod
    def poll(self, context):
        return (context.mode == "OBJECT" and
                context.view_layer.objects.active.type == "MESH")

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


class IOPS_PT_iops_tm_panel(bpy.types.Panel):
    """Creates a Panel from Tranformation,PivotPoint,Snapping panels"""
    bl_label = "IOPS TPS"
    bl_idname = "IOPS_PT_iops_tm_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Item'

    def draw(self, context):
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
        layout.ui_units_x = 20.0
        row = layout.row(align=True)
        row.prop(tool_settings, "use_snap", text="")
        row.prop(tool_settings, "use_mesh_automerge", text="")
        row.operator("iops.transform_orientation_create", text="", icon='ADD')
        row.separator()
        row.operator("iops.transform_orientation_cleanup", text="", icon='BRUSH_DATA')
        row.operator("iops.uvmaps_cleanup", text="", icon='UV_DATA')

        if batchops:
            row.separator()
            row.operator("batch_ops_objects.rename", text="", icon='OUTLINER_DATA_FONT')

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


class IOPS_PT_iops_transform_panel(bpy.types.Panel):
    """Creates a Panel from Tranformation,PivotPoint,Snapping panels"""
    bl_label = "IOPS TM"
    bl_idname = "IOPS_PT_iops_transform_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Item'
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(self, context):
        return (context.area.type == "VIEW_3D" and
                len(context.view_layer.objects.selected) != 0 and
                context.view_layer.objects.active.type == "MESH")

    def draw(self, context):
        obj = context.view_layer.objects.active
        layout = self.layout
        layout.ui_units_x = 8.0
        col = layout.column(align=True)
        col.prop(obj, "location")
        col.prop(obj, "rotation_euler")
        col.prop(obj, "scale")
        col.prop(obj, "dimensions")
