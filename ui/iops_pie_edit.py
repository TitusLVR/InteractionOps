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


def draw_empty_pie_size_display_and_image(pie, context):
    """Shared EMPTY pie UI: size column, display grid, optional image-empty row."""
    obj = context.object
    if not obj or obj.type != "EMPTY":
        return

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
    col.prop(obj, "empty_display_size", text="Custom Size")
    col.separator()
    col.operator("iops.copy_empty_size_from_active", text="Copy Size from Active", icon="COPYDOWN")

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

    data = getattr(obj, "data", None)
    if obj.empty_display_type == "IMAGE" and isinstance(data, bpy.types.Image):
        col.separator()
        row = col.row(align=True)
        row.operator(
            "iops.reload_empty_reference_image",
            text="Reload Image",
            icon="FILE_REFRESH",
        )
        o = row.operator("object.origin_set", text="Origin")
        o.type = "ORIGIN_GEOMETRY"
        o.center = "MEDIAN"


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
        arm = {
            "EDIT": {
                "f1": ("Object Mode", "OBJECT_DATA"),
                "f2": ("Pose Mode", "POSE_HLT"),
                "f3": ("Set Parent to Bone", "BONE_DATA"),
                "esc": ("Object Mode", "OBJECT_DATA"),
            },
            "POSE": {
                "f1": ("Edit Mode", "EDITMODE_HLT"),
                "f2": ("Object Mode", "OBJECT_DATA"),
                "f3": ("Set Parent to Bone", "BONE_DATA"),
                "esc": ("Object Mode", "OBJECT_DATA"),
            },
            "OBJECT": {
                "f1": ("Edit Mode", "EDITMODE_HLT"),
                "f2": ("Pose Mode", "POSE_HLT"),
                "f3": ("Set Parent to Bone", "BONE_DATA"),
                "esc": ("Esc", "EVENT_ESC"),
            },
        }
        row = arm.get(m, arm["OBJECT"])
        if operator in row:
            return row[operator]

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

    elif obj.type == "CURVE":
        if m == "OBJECT":
            match operator:
                case "f1":
                    return "Edit Mode", "EDITMODE_HLT"
                case "f2":
                    return "Duplicate", "DUPLICATE"
                case "f3":
                    return "Switch Direction", "CURVE_PATH"
                case "esc":
                    return "Toggle Cyclic", "CURVE_BEZCIRCLE"
        elif m == "EDIT":
            match operator:
                case "f1":
                    return "Object Mode", "OBJECT_DATA"
                case "f2":
                    return "Subdivide", "MOD_MULTIRES"
                case "f3":
                    return "Spline Type", "CURVE_DATA"
                case "esc":
                    return "Esc", "EVENT_ESC"

    elif obj.type == "CURVES":
        if m == "OBJECT":
            match operator:
                case "f1":
                    return "Edit Mode", "EDITMODE_HLT"
                case "f2":
                    return "Duplicate", "DUPLICATE"
                case "f3":
                    return "Toggle Cyclic", "CURVE_BEZCIRCLE"
                case "esc":
                    return "Esc", "EVENT_ESC"
        elif m in {"EDIT", "EDIT_CURVES"}:
            match operator:
                case "f1":
                    return "Object Mode", "OBJECT_DATA"
                case "f2":
                    return "Subdivide", "MOD_MULTIRES"
                case "f3":
                    return "Cyclic", "CURVE_DATA"
                case "esc":
                    return "Esc", "EVENT_ESC"
        elif m == "SCULPT_CURVES":
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
            case "f4":
                return "Lens +5", "ZOOM_IN"
            case "esc":
                return "Toggle DOF", "VIEW_CAMERA"

    elif obj.type == "LIGHT":
        match operator:
            case "f1":
                return "Duplicate", "DUPLICATE"
            case "f2":
                return "Toggle Shadow", "LIGHT_SPOT"
            case "f3":
                return "Boost Power", "LIGHT_SUN"
            case "f4":
                return "Toggle Specular", "NODE_MATERIAL"
            case "esc":
                return "Cycle Type", "LIGHT_AREA"

    elif obj.type == "FONT":
        if m == "OBJECT":
            match operator:
                case "f1":
                    return "Edit Mode", "EDITMODE_HLT"
                case "f2":
                    return "Convert to Mesh", "MESH_DATA"
                case "f3":
                    return "To Curve", "CURVE_DATA"
                case "esc":
                    return "Esc", "EVENT_ESC"
        elif m == "EDIT":
            match operator:
                case "f1":
                    return "Object Mode", "OBJECT_DATA"
                case "f2":
                    return "Duplicate", "DUPLICATE"
                case "f3":
                    return "Bold", "FONT_DATA"
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
                    return "F3", "EVENT_F3"
                case "esc":
                    return "Esc", "EVENT_ESC"
        elif m == "EDIT":
            match operator:
                case "f1":
                    return "Object Mode", "OBJECT_DATA"
                case "f2":
                    return "Duplicate", "DUPLICATE"
                case "f3":
                    return "Flip U", "ARROWLEFTRIGHT"
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
                    return "F3", "EVENT_F3"
                case "esc":
                    return "Finer Preview", "META_DATA"
        elif m == "EDIT":
            match operator:
                case "f1":
                    return "Object Mode", "OBJECT_DATA"
                case "f2":
                    return "Duplicate", "DUPLICATE"
                case "f3":
                    return "Threshold -", "META_DATA"
                case "esc":
                    return "Esc", "EVENT_ESC"

    elif obj.type == "LIGHT_PROBE":
        match operator:
            case "f1":
                return "Duplicate", "DUPLICATE"
            case "f2":
                return "+ Influence", "LIGHTPROBE_GRID"
            case "f3":
                return "- Influence", "LIGHTPROBE_GRID"
            case "f4":
                return "Clip / Parallax", "LIGHTPROBE_PLANAR"
            case "esc":
                return "Hide Viewport", "HIDE_OFF"

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


def _pie_prop(col, data, prop, **kwargs):
    if data is not None and prop in data.bl_rna.properties:
        col.prop(data, prop, **kwargs)


def _pie_ext_block(obj, block_key):
    if block_key == "object":
        return obj
    if block_key == "data":
        return getattr(obj, "data", None)
    if block_key == "dof":
        d = getattr(obj, "data", None)
        return getattr(d, "dof", None) if d else None
    return None


_PIE_GREASEPENCIL_EXT = (
    "Grease Pencil",
    "GREASEPENCIL",
    [
        ("object", "use_grease_pencil_lights", {"text": "Lights"}),
        ("object", "use_grease_pencil_on_back", {"text": "On Back"}),
    ],
)

# Object mode only: (title, icon, list of (block_key, rna_prop, prop_kwargs))
_PIE_OBJECT_MODE_DATA_SPECS = {
    "CURVE": (
        "Curve",
        "CURVE_DATA",
        [
            ("data", "bevel_depth", {"text": "Bevel"}),
            ("data", "bevel_object", {"text": "Bevel Obj"}),
            ("data", "resolution_u", {"text": "Res U"}),
            ("data", "dimensions", {"text": "Dimensions"}),
        ],
    ),
    "CURVES": (
        "Curves",
        "CURVES",
        [
            ("data", "surface_scale", {}),
            ("data", "surface_uv_map", {"text": "UV Map"}),
        ],
    ),
    "SURFACE": (
        "Surface",
        "SURFACE_DATA",
        [
            ("data", "resolution_u", {"text": "Res U"}),
            ("data", "resolution_v", {"text": "Res V"}),
        ],
    ),
    "FONT": (
        "Text",
        "FONT_DATA",
        [
            ("data", "size", {"text": "Size"}),
            ("data", "extrude", {"text": "Extrude"}),
            ("data", "body_alignment", {"text": "Align"}),
            ("data", "space_character", {"text": "Spacing"}),
        ],
    ),
    "META": (
        "Metaball",
        "META_DATA",
        [
            ("data", "threshold", {"text": "Threshold"}),
            ("data", "resolution", {"text": "Resolution"}),
            ("data", "render_resolution", {"text": "Render Res"}),
        ],
    ),
    "LATTICE": (
        "Lattice",
        "LATTICE_DATA",
        [
            ("data", "points_u", {"text": "U"}),
            ("data", "points_v", {"text": "V"}),
            ("data", "points_w", {"text": "W"}),
            ("data", "use_outside", {"text": "Outside"}),
            ("data", "interpolation_type_u", {"text": "Interp U"}),
        ],
    ),
    "ARMATURE": (
        "Armature",
        "ARMATURE_DATA",
        [
            ("data", "display_type", {"text": "Display"}),
            ("object", "show_in_front", {"text": "In Front"}),
        ],
    ),
    "CAMERA": (
        "Camera",
        "CAMERA_DATA",
        [
            ("data", "type", {"text": "Type"}),
            ("data", "lens", {"text": "Lens"}),
            ("data", "ortho_scale", {"text": "Ortho Scale"}),
            ("data", "clip_start", {"text": "Clip Near"}),
            ("data", "clip_end", {"text": "Clip Far"}),
            ("dof", "use_dof", {"text": "DOF"}),
            ("dof", "aperture_fstop", {"text": "F-Stop"}),
            ("dof", "focus_distance", {"text": "Focus Dist"}),
        ],
    ),
    "LIGHT": (
        "Light",
        "LIGHT_DATA",
        [
            ("data", "type", {"text": "Type"}),
            ("data", "energy", {"text": "Power"}),
            ("data", "color", {"text": ""}),
            ("data", "exposure", {"text": "Exposure"}),
            ("data", "diffuse_factor", {"text": "Diffuse"}),
            ("data", "use_temperature", {"text": "Use Temp"}),
            ("data", "temperature", {"text": "Temp K"}),
        ],
    ),
    "LIGHT_PROBE": (
        "Light Probe",
        "LIGHTPROBE_PLANAR",
        [
            ("data", "influence_distance", {"text": "Distance"}),
            ("data", "clip_start", {"text": "Clip Start"}),
            ("data", "clip_end", {"text": "Clip End"}),
            ("data", "show_influence", {"text": "Show Volume"}),
            ("data", "show_clip", {"text": "Show Clip"}),
            ("data", "use_data_display", {"text": "Data Viz"}),
        ],
    ),
    "SPEAKER": (
        "Speaker",
        "SPEAKER",
        [
            ("data", "volume", {"text": "Volume"}),
            ("data", "muted", {"text": "Mute"}),
        ],
    ),
    "VOLUME": (
        "Volume",
        "VOLUME_DATA",
        [
            ("data", "density", {"text": "Density"}),
            ("data", "display_density", {"text": "Display"}),
        ],
    ),
    "POINTCLOUD": (
        "Point Cloud",
        "POINTCLOUD_DATA",
        [
            ("data", "display_percentage", {"text": "Display %"}),
        ],
    ),
    "GPENCIL": _PIE_GREASEPENCIL_EXT,
    "GREASEPENCIL": _PIE_GREASEPENCIL_EXT,
}


_PIE_EXTENSION_TYPES = frozenset(_PIE_OBJECT_MODE_DATA_SPECS.keys())


def draw_edit_pie_type_extensions(pie, context):
    """Object mode: RNA props on object / object.data / camera dof (View3D)."""
    obj = context.object
    if not obj or obj.mode != "OBJECT":
        return
    spec = _PIE_OBJECT_MODE_DATA_SPECS.get(obj.type)
    if not spec:
        return
    title, icon, rows = spec
    if any(b in ("data", "dof") for b, _, _ in rows) and getattr(obj, "data", None) is None:
        return
    box = pie.box()
    col = box.column(align=True)
    col.scale_y = 0.85
    col.label(text=title, icon=icon)
    for block_key, prop, pkwargs in rows:
        block = _pie_ext_block(obj, block_key)
        _pie_prop(col, block, prop, **pkwargs)


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
                draw_empty_pie_size_display_and_image(pie, context)

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
                draw_empty_pie_size_display_and_image(pie, context)

            else:
                draw_edit_pie_cardinals(pie, context)
                draw_edit_pie_type_extensions(pie, context)
                obj = context.object
                if obj and obj.type == 'MESH' and obj.mode == 'EDIT':
                    pie.operator("iops.mesh_visual_uv", text="Visual UV", icon="UV")

            draw_open_asset_in_pie_if_poll(pie, context)

        elif context.area.type == "IMAGE_EDITOR":
            if not context.active_object:
                draw_open_asset_in_pie_if_poll(pie, context)
                return
            pie.operator("iops.function_f1", text="Vertex", icon="VERTEXSEL")
            pie.operator("iops.function_f3", text="Face", icon="FACESEL")
            pie.operator("iops.function_esc", text="Esc", icon="EVENT_ESC")
            pie.operator("iops.function_f2", text="Edge", icon="EDGESEL")
            if not context.tool_settings.use_uv_select_sync:
                pie.separator()
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
