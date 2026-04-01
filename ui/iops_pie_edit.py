import bpy
import os
from bpy.types import Menu

from ..operators.open_asset_in_current_blender import IOPS_OT_OpenAssetInCurrentBlender


def draw_open_asset_in_pie_if_poll(pie, context):
    if not IOPS_OT_OpenAssetInCurrentBlender.poll(context):
        return
    pie.operator(
        IOPS_OT_OpenAssetInCurrentBlender.bl_idname,
        text=IOPS_OT_OpenAssetInCurrentBlender.bl_label,
        icon="BLENDER",
    )


def get_text_icon(context, operator):
    """Labels/icons for IOPS_MT_Pie_Edit cardinals (Blender 5.x object types/modes)."""
    obj = context.object
    if not obj:
        return "Esc", "EVENT_ESC"

    m = obj.mode

    if obj.type == "MESH":
        match operator:
            case "f1":
                return "Vertex", "VERTEXSEL"
            case "f2":
                return "Edge", "EDGESEL"
            case "f3":
                return "Face", "FACESEL"
            case "esc":
                return "Esc", "EVENT_ESC"

    elif obj.type == "ARMATURE":
        if m == "EDIT":
            match operator:
                case "f1":
                    return "Object Mode", "OBJECT_DATA"
                case "f2":
                    return "Pose Mode", "POSE_HLT"
                case "f3":
                    return "Set Parent to Bone", "BONE_DATA"
                case "esc":
                    return "Object Mode", "OBJECT_DATA"
        elif m == "POSE":
            match operator:
                case "f1":
                    return "Edit Mode", "EDITMODE_HLT"
                case "f2":
                    return "Object Mode", "OBJECT_DATA"
                case "f3":
                    return "Set Parent to Bone", "BONE_DATA"
                case "esc":
                    return "Object Mode", "OBJECT_DATA"
        else:
            match operator:
                case "f1":
                    return "Edit Mode", "EDITMODE_HLT"
                case "f2":
                    return "Pose Mode", "POSE_HLT"
                case "f3":
                    return "Set Parent to Bone", "BONE_DATA"
                case "esc":
                    return "Frame Selected", "VIEWZOOM"

    elif obj.type == "EMPTY":
        match operator:
            case "f1":
                return "Open Instance Collection .blend", "FILE_BACKUP"
            case "f2":
                return "Realize Instances", "OUTLINER_OB_GROUP_INSTANCE"
            case "f3":
                return "F3", "EVENT_F3"
            case _:
                return "Esc", "EVENT_ESC"

    elif obj.type in {"CURVE", "CURVES"}:
        if m == "OBJECT":
            match operator:
                case "f1":
                    return "Edit Mode", "EDITMODE_HLT"
                case "f2":
                    return "Duplicate", "DUPLICATE"
                case "f3":
                    return "Origin", "OBJECT_ORIGIN"
                case "esc":
                    return "Frame Selected", "VIEWZOOM"
        elif obj.type == "CURVE" and m == "EDIT":
            match operator:
                case "f1":
                    return "Object Mode", "OBJECT_DATA"
                case "f2":
                    return "Subdivide", "MOD_MULTIRES"
                case "f3":
                    return "Spline Type", "CURVE_DATA"
                case "esc":
                    return "Esc", "EVENT_ESC"
        elif obj.type == "CURVES" and m in {"EDIT", "EDIT_CURVES"}:
            match operator:
                case "f1":
                    return "Object Mode", "OBJECT_DATA"
                case "f2":
                    return "Subdivide", "MOD_MULTIRES"
                case "f3":
                    return "Cyclic", "CURVE_DATA"
                case "esc":
                    return "Esc", "EVENT_ESC"
        elif obj.type == "CURVES" and m == "SCULPT_CURVES":
            match operator:
                case "f1":
                    return "Edit Mode", "EDITMODE_HLT"
                case "f2":
                    return "Object Mode", "OBJECT_DATA"
                case "f3":
                    return "Sculpt Toggle", "SCULPTMODE_HLT"
                case "esc":
                    return "Esc", "EVENT_ESC"

    elif obj.type == "CAMERA":
        match operator:
            case "f1":
                return "Active Camera", "VIEW_CAMERA"
            case "f2":
                return "Camera View", "CAMERA_DATA"
            case "f3":
                return "Cam to View", "VIEW_PERSPECTIVE"
            case "esc":
                return "Frame to Cam", "VIEW_CAMERA"

    elif obj.type == "LIGHT":
        match operator:
            case "f1":
                return "Duplicate", "DUPLICATE"
            case "f2":
                return "Origin", "OBJECT_ORIGIN"
            case "f3":
                return "Cursor to Active", "CURSOR"
            case "esc":
                return "Frame Selected", "VIEWZOOM"

    elif obj.type == "FONT":
        if m == "OBJECT":
            match operator:
                case "f1":
                    return "Edit Mode", "EDITMODE_HLT"
                case "f2":
                    return "Convert to Mesh", "MESH_DATA"
                case "f3":
                    return "Origin", "OBJECT_ORIGIN"
                case "esc":
                    return "Frame Selected", "VIEWZOOM"
        elif m == "EDIT":
            match operator:
                case "f1":
                    return "Object Mode", "OBJECT_DATA"
                case "f2":
                    return "Duplicate", "DUPLICATE"
                case "f3":
                    return "Origin", "OBJECT_ORIGIN"
                case "esc":
                    return "Esc", "EVENT_ESC"

    elif obj.type == "LATTICE":
        if m == "OBJECT":
            match operator:
                case "f1":
                    return "Edit Mode", "EDITMODE_HLT"
                case "f2":
                    return "Duplicate", "DUPLICATE"
                case "f3":
                    return "Origin", "OBJECT_ORIGIN"
                case "esc":
                    return "Frame Selected", "VIEWZOOM"
        elif m == "EDIT":
            match operator:
                case "f1":
                    return "Object Mode", "OBJECT_DATA"
                case "f2":
                    return "Duplicate", "DUPLICATE"
                case "f3":
                    return "Origin", "OBJECT_ORIGIN"
                case "esc":
                    return "Esc", "EVENT_ESC"

    elif obj.type == "META":
        if m == "OBJECT":
            match operator:
                case "f1":
                    return "Edit Mode", "EDITMODE_HLT"
                case "f2":
                    return "Duplicate", "DUPLICATE"
                case "f3":
                    return "Origin", "OBJECT_ORIGIN"
                case "esc":
                    return "Frame Selected", "VIEWZOOM"
        elif m == "EDIT":
            match operator:
                case "f1":
                    return "Object Mode", "OBJECT_DATA"
                case "f2":
                    return "Duplicate", "DUPLICATE"
                case "f3":
                    return "Origin", "OBJECT_ORIGIN"
                case "esc":
                    return "Esc", "EVENT_ESC"

    elif obj.type == "LIGHT_PROBE":
        match operator:
            case "f1":
                return "Duplicate", "DUPLICATE"
            case "f2":
                return "Origin", "OBJECT_ORIGIN"
            case "f3":
                return "Cursor to Active", "CURSOR"
            case "esc":
                return "Frame Selected", "VIEWZOOM"

    return "Esc", "EVENT_ESC"


def draw_edit_pie_cardinals(pie, context):
    t1, i1 = get_text_icon(context, "f1")
    t2, i2 = get_text_icon(context, "f2")
    t3, i3 = get_text_icon(context, "f3")
    te, ie = get_text_icon(context, "esc")
    pie.operator("iops.function_f1", text=t1, icon=i1)
    pie.operator("iops.function_f3", text=t3, icon=i3)
    pie.operator("iops.function_esc", text=te, icon=ie)
    pie.operator("iops.function_f2", text=t2, icon=i2)


class IOPS_MT_Pie_Edit_Modes(Menu):
    bl_label = "IOPS_MT_Pie_Edit_Modes"

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
    def poll(cls, context):
        if context.area.type not in {"VIEW_3D", "IMAGE_EDITOR"}:
            return False
        if context.active_object:
            return True
        return IOPS_OT_OpenAssetInCurrentBlender.poll(context)

    def draw(self, context):
        layout = self.layout
        pie = layout.menu_pie()

        if context.area.type == "VIEW_3D":
            if not context.active_object:
                draw_open_asset_in_pie_if_poll(pie, context)
                return
            # Open Linked Library Blend
            if (
                context.object.type == "EMPTY"
                and context.object.instance_collection
                and context.object.instance_type == "COLLECTION"
                # and context.object.instance_collection.library
            ):
                # 4 - LEFT - Size options
                box = pie.box()
                col = box.column(align=True)
                col.scale_y = 0.9
                col.label(text="Size")
                row = box.row(align=True)
                row.operator("iops.set_empty_size", text="0.1").size = 0.1
                row.operator("iops.set_empty_size", text="0.5").size = 0.5
                row.operator("iops.set_empty_size", text="1.0").size = 1.0
                row = box.row(align=True)
                row.operator("iops.set_empty_size", text="2.0").size = 2.0
                row.operator("iops.set_empty_size", text="5.0").size = 5.0
                row.operator("iops.set_empty_size", text="10.0").size = 10.0
                col.separator()
                col.prop(context.object, "empty_display_size", text="Custom Size")
                col.separator()
                col.operator("iops.copy_empty_size_from_active", text="Copy Size from Active", icon="COPYDOWN")
                
                # 6 - RIGHT - Display options
                box = pie.box()
                col = box.column(align=True)
                col.label(text="Display")
                flow = col.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=True, align=True)
                flow.scale_x = 1.35
                flow.operator("iops.set_empty_display", text="Plain Axes", icon="EMPTY_AXIS").display_type = "PLAIN_AXES"
                flow.operator("iops.set_empty_display", text="Arrows", icon="EMPTY_ARROWS").display_type = "ARROWS"
                flow.operator("iops.set_empty_display", text="Single Arrow", icon="EMPTY_SINGLE_ARROW").display_type = "SINGLE_ARROW"
                flow.operator("iops.set_empty_display", text="Circle", icon="MESH_CIRCLE").display_type = "CIRCLE"
                flow.operator("iops.set_empty_display", text="Cube", icon="MESH_CUBE").display_type = "CUBE"
                flow.operator("iops.set_empty_display", text="Sphere", icon="MESH_UVSPHERE").display_type = "SPHERE"
                flow.operator("iops.set_empty_display", text="Cone", icon="MESH_CONE").display_type = "CONE"
                flow.operator("iops.set_empty_display", text="Image", icon="IMAGE").display_type = "IMAGE"

                data = getattr(context.object, "data", None)
                if context.object.empty_display_type == "IMAGE" and isinstance(
                    data, bpy.types.Image
                ):
                    col.separator()
                    row = col.row(align=True)
                    row.operator(
                        "iops.reload_empty_reference_image",
                        text="Reload Image",
                        icon="FILE_REFRESH",
                    )
                    row.operator("object.duplicate_move", text="Duplicate")
                    o = row.operator("object.origin_set", text="Origin")
                    o.type = "ORIGIN_GEOMETRY"
                    o.center = "MEDIAN"

                # 2 - BOTTOM
                op = pie.operator("object.duplicates_make_real", text="Make Instances Real")
                op.use_hierarchy = True

                # 8 - TOP
                pie.operator(
                    "iops.expand_instance_collection",
                    text="Expand Collection to Scene",
                    icon="OUTLINER_OB_GROUP_INSTANCE",
                )

                # 7 - TOP-LEFT
                if context.object.instance_collection.library:
                    blendpath = os.path.abspath(
                        bpy.path.abspath(
                            context.object.instance_collection.library.filepath
                        )
                    )
                    library = context.object.instance_collection.library.name

                    op = pie.operator(
                        "iops.open_asset_in_new_blender",
                        text=f"Open {os.path.basename(blendpath)}",
                    )
                    op.blendpath = blendpath
                    op.library = library
                    
                    # 9 - TOP-RIGHT - Reload Library
                    op = pie.operator(
                        "iops.reload_instance_library",
                        text=f"Reload {os.path.basename(blendpath)}",
                        icon="FILE_REFRESH"
                    )
            elif context.object.type == "EMPTY":
                # 4 - LEFT - Size options
                box = pie.box()
                col = box.column(align=True)
                col.scale_y = 0.9
                col.label(text="Size")
                row = box.row(align=True)
                row.operator("iops.set_empty_size", text="0.1").size = 0.1
                row.operator("iops.set_empty_size", text="0.5").size = 0.5
                row.operator("iops.set_empty_size", text="1.0").size = 1.0
                row = box.row(align=True)
                row.operator("iops.set_empty_size", text="2.0").size = 2.0
                row.operator("iops.set_empty_size", text="5.0").size = 5.0
                row.operator("iops.set_empty_size", text="10.0").size = 10.0
                col.separator()
                col.prop(context.object, "empty_display_size", text="Custom Size")
                col.separator()
                col.operator("iops.copy_empty_size_from_active", text="Copy Size from Active", icon="COPYDOWN")
                
                # 6 - RIGHT - Display options
                box = pie.box()
                col = box.column(align=True)
                col.label(text="Display")
                flow = col.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=True, align=True)
                flow.scale_x = 1.35
                flow.operator("iops.set_empty_display", text="Plain Axes", icon="EMPTY_AXIS").display_type = "PLAIN_AXES"
                flow.operator("iops.set_empty_display", text="Arrows", icon="EMPTY_ARROWS").display_type = "ARROWS"
                flow.operator("iops.set_empty_display", text="Single Arrow", icon="EMPTY_SINGLE_ARROW").display_type = "SINGLE_ARROW"
                flow.operator("iops.set_empty_display", text="Circle", icon="MESH_CIRCLE").display_type = "CIRCLE"
                flow.operator("iops.set_empty_display", text="Cube", icon="MESH_CUBE").display_type = "CUBE"
                flow.operator("iops.set_empty_display", text="Sphere", icon="MESH_UVSPHERE").display_type = "SPHERE"
                flow.operator("iops.set_empty_display", text="Cone", icon="MESH_CONE").display_type = "CONE"
                flow.operator("iops.set_empty_display", text="Image", icon="IMAGE").display_type = "IMAGE"

                data = getattr(context.object, "data", None)
                if context.object.empty_display_type == "IMAGE" and isinstance(
                    data, bpy.types.Image
                ):
                    col.separator()
                    row = col.row(align=True)
                    row.operator(
                        "iops.reload_empty_reference_image",
                        text="Reload Image",
                        icon="FILE_REFRESH",
                    )
                    row.operator("object.duplicate_move", text="Duplicate")
                    o = row.operator("object.origin_set", text="Origin")
                    o.type = "ORIGIN_GEOMETRY"
                    o.center = "MEDIAN"
                
                # 7 - TOP-LEFT
                # 9 - TOP-RIGHT
                # 1 - BOTTOM-LEFT
                # 3 - BOTTOM-RIGHT
                # 2 - BOTTOM
                # 8 - TOP

            else:
                draw_edit_pie_cardinals(pie, context)

            draw_open_asset_in_pie_if_poll(pie, context)

        elif context.area.type == "IMAGE_EDITOR":
            if not context.active_object:
                draw_open_asset_in_pie_if_poll(pie, context)
                return
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

            draw_open_asset_in_pie_if_poll(pie, context)


class IOPS_OT_Set_Empty_Size(bpy.types.Operator):
    """Set empty size"""
    bl_idname = "iops.set_empty_size"
    bl_label = "Set Empty Size"
    
    size: bpy.props.FloatProperty(
        name="Size",
        description="Empty size to set",
        default=1.0,
        min=0.001,
        max=1000.0
    )
    
    def execute(self, context):
        # Get all selected objects that are empties (including instance collections)
        selected_empties = [obj for obj in context.selected_objects 
                           if obj.type == "EMPTY"]
        
        if selected_empties:
            for obj in selected_empties:
                obj.empty_display_size = self.size
        elif context.object and context.object.type == "EMPTY":
            # Fallback to active object if no selection
            context.object.empty_display_size = self.size
        
        return {"FINISHED"}


class IOPS_OT_Set_Empty_Display(bpy.types.Operator):
    """Set empty display type"""
    bl_idname = "iops.set_empty_display"
    bl_label = "Set Empty Display Type"
    
    display_type: bpy.props.EnumProperty(
        name="Display Type",
        description="Empty display type to set",
        items=[
            ("PLAIN_AXES", "Plain Axes", "Plain axes"),
            ("ARROWS", "Arrows", "Arrows"),
            ("SINGLE_ARROW", "Single Arrow", "Single arrow"),
            ("CIRCLE", "Circle", "Circle"),
            ("CUBE", "Cube", "Cube"),
            ("SPHERE", "Sphere", "Sphere"),
            ("CONE", "Cone", "Cone"),
            ("IMAGE", "Image", "Image")
        ],
        default="PLAIN_AXES"
    )
    
    def execute(self, context):
        # Get all selected objects that are empties (including instance collections)
        selected_empties = [obj for obj in context.selected_objects 
                           if obj.type == "EMPTY"]
        
        if selected_empties:
            for obj in selected_empties:
                obj.empty_display_type = self.display_type
        elif context.object and context.object.type == "EMPTY":
            # Fallback to active object if no selection
            context.object.empty_display_type = self.display_type
        
        return {"FINISHED"}


class IOPS_OT_Copy_Empty_Size_From_Active(bpy.types.Operator):
    """Copy empty size from active object to all selected empties"""
    bl_idname = "iops.copy_empty_size_from_active"
    bl_label = "Copy Empty Size from Active"
    
    def execute(self, context):
        # Check if active object is an empty (including instance collections)
        if context.object and context.object.type == "EMPTY":
            
            active_size = context.object.empty_display_size
            
            # Get all selected objects that are empties (including instance collections)
            selected_empties = [obj for obj in context.selected_objects 
                               if obj.type == "EMPTY"]
            
            # Copy size to all selected empties (excluding the active one)
            for obj in selected_empties:
                if obj != context.object:  # Don't copy to itself
                    obj.empty_display_size = active_size
            
            if selected_empties:
                self.report({'INFO'}, f"Copied size {active_size} to {len(selected_empties)} empty objects")
            else:
                self.report({'INFO'}, "No other empty objects selected")
        else:
            self.report({'ERROR'}, "Active object must be an empty")
        
        return {"FINISHED"}


class IOPS_OT_ReloadEmptyReferenceImage(bpy.types.Operator):
    """Reload the image datablock used by a reference image empty."""

    bl_idname = "iops.reload_empty_reference_image"
    bl_label = "Reload Reference Image"

    @classmethod
    def poll(cls, context):
        obj = context.object
        if not obj or obj.type != "EMPTY" or obj.empty_display_type != "IMAGE":
            return False
        data = getattr(obj, "data", None)
        return bool(data and isinstance(data, bpy.types.Image))

    def execute(self, context):
        img = context.object.data
        img.reload()
        self.report({"INFO"}, "Reloaded image '%s'" % img.name)
        return {"FINISHED"}


class IOPS_OT_Reload_Instance_Library(bpy.types.Operator):
    """Reload the linked libraries of selected instance collections"""
    bl_idname = "iops.reload_instance_library"
    bl_label = "Reload Instance Library"
    
    @classmethod
    def poll(cls, context):
        # Check if any selected object is an instance collection with a linked library
        for obj in context.selected_objects:
            if (obj.type == "EMPTY" 
                and obj.instance_collection 
                and obj.instance_collection.library):
                return True
        return False
    
    def execute(self, context):
        # Collect unique libraries from all selected instance collections
        libraries = set()
        for obj in context.selected_objects:
            if (obj.type == "EMPTY" 
                and obj.instance_collection 
                and obj.instance_collection.library):
                libraries.add(obj.instance_collection.library)
        
        # Reload each unique library
        for library in libraries:
            library.reload()
        
        if len(libraries) == 1:
            lib = next(iter(libraries))
            self.report({'INFO'}, f"Library '{lib.name}' reloaded.")
        else:
            self.report({'INFO'}, f"{len(libraries)} libraries reloaded.")
        
        return {"FINISHED"}


class IOPS_OT_Call_Pie_Edit(bpy.types.Operator):
    """IOPS Pie"""

    bl_idname = "iops.call_pie_edit"
    bl_label = "IOPS Pie Edit"

    @classmethod
    def poll(self, context):
        if context.area.type not in {"VIEW_3D", "IMAGE_EDITOR"}:
            return False
        if context.active_object:
            return True
        return IOPS_OT_OpenAssetInCurrentBlender.poll(context)

    def execute(self, context):
        bpy.ops.wm.call_menu_pie(name="IOPS_MT_Pie_Edit")
        return {"FINISHED"}
