import os
import bpy
from bpy.types import PropertyGroup
from bpy.props import (
    FloatProperty,
    FloatVectorProperty,
    StringProperty,
    CollectionProperty,
    IntProperty,
    BoolProperty,
    EnumProperty,
)

def fuzzy_match(search_term, target):
    """
    Fuzzy match: checks if all characters in search_term appear in order in target.
    Characters don't need to be consecutive.
    Spaces are ignored in both search_term and target.
    Example: "abc" matches "a_b_c", "abc", "aXbYc", etc.
    """
    if not search_term:
        return True
    
    # Remove spaces from both search_term and target
    search_term = search_term.lower().replace(" ", "")
    target = target.lower().replace(" ", "")
    
    if not search_term:
        return True
    
    # First check for exact substring match (highest priority)
    if search_term in target:
        return True
    
    # Then check for fuzzy match (characters in order)
    search_idx = 0
    for char in target:
        if search_idx < len(search_term) and char == search_term[search_idx]:
            search_idx += 1
            if search_idx == len(search_term):
                return True
    
    return False

def update_exec_filter(self, context):
    scene = bpy.context.scene
    iops = getattr(scene, "IOPS", None)
    if iops is None:
        return
    scripts = [item.path for item in iops.executor_scripts]
    if not scripts:
        return
    filter_text = self.iops_exec_filter.lower()
    iops.filtered_executor_scripts.clear()
    if filter_text:
        for script in scripts:
            script_name = os.path.basename(script)
            if fuzzy_match(filter_text, script_name):
                item = iops.filtered_executor_scripts.add()
                item.path = script



class IOPS_CollectionItem(PropertyGroup):
    """Property group for collection list items"""
    name: StringProperty(
        name="Collection Name",
        description="Name of the collection in the source file",
        default=""
    )
    is_selected: BoolProperty(
        name="Select",
        description="Select this collection for appending",
        default=False
    )


class IOPS_ExecutorScriptItem(PropertyGroup):
    """Single script path for the executor list"""
    path: StringProperty(name="Script path", default="")


class IOPS_AddonProperties(PropertyGroup):
    iops_panel_mesh_info: bpy.props.BoolProperty(
        name="Show mesh info", description="Show mesh info panel", default=False
    )

    iops_rotation_angle: FloatProperty(
        name="Angle", description="Degrees", default=90, min=0.0
    )
    iops_split_previous: StringProperty(
        name="iops_split_previous",
        default="VIEW_3D",
    )
    iops_exec_filter: StringProperty(
        name="Filter",
        default="",
        options={'TEXTEDIT_UPDATE'},
        update=update_exec_filter,
    )
    iops_append_collection_name: StringProperty(
        name="Collection Name",
        description="Name of the collection to append from linked asset source",
        default="",
    )
    iops_source_collections: CollectionProperty(
        type=IOPS_CollectionItem,
        name="Source Collections",
        description="Collections available in the source file"
    )
    iops_source_collections_index: IntProperty(
        name="Active Collection Index",
        default=0
    )
    iops_active_asset_library: StringProperty(
        name="Active Asset Library",
        description="Library path selected in the asset management pie (empty = Current File)",
        default="",
    )


class IOPS_SceneProperties(PropertyGroup):
    executor_scripts: CollectionProperty(
        type=IOPS_ExecutorScriptItem,
        name="Executor scripts",
        description="Script paths for the executor panel",
    )
    filtered_executor_scripts: CollectionProperty(
        type=IOPS_ExecutorScriptItem,
        name="Filtered executor scripts",
        description="Filtered script paths when search is active",
    )
    dragsnap_point_a: FloatVectorProperty(
        name="DragSnap Point A",
        description="DragSnap Point A",
        default=(0.0, 0.0, 0.0),
        size=3,
        subtype="COORDINATES",
    )

    dragsnap_point_b: FloatVectorProperty(
        name="DragSnap Point B",
        description="DragSnap Point B",
        default=(0.0, 0.0, 0.0),
        size=3,
        subtype="COORDINATES",
    )

    iops_vertex_color: FloatVectorProperty(
        name="VertexColor",
        description="Color picker",
        default=(1.0, 1.0, 1.0, 1.0),
        min=0.0,
        max=1.0,
        subtype="COLOR",
        size=4,
    )

    # Cursor Bisect persistent properties
    cursor_bisect_snapping: BoolProperty(name="Snapping", default=True)
    cursor_bisect_normal_axis: EnumProperty(
        name="Normal Axis",
        items=[('X', "X", ""), ('Y', "Y", "")],
        default='X',
    )
    cursor_bisect_preview_mode: EnumProperty(
        name="Preview Mode",
        items=[('LINES', "Lines", ""), ('PLANE', "Plane", "")],
        default='LINES',
    )
    cursor_bisect_fill_cut: BoolProperty(name="Fill Cut", default=False)
    cursor_bisect_show_distance: BoolProperty(name="Show Distance", default=True)
    cursor_bisect_edge_subdivisions: IntProperty(name="Edge Subdivisions", default=0, min=0, max=100)
    cursor_bisect_inset_active: BoolProperty(name="Inset Active", default=False)
    cursor_bisect_inset_distance: FloatProperty(name="Inset Distance (BU)", default=0.1, min=0.0)
    cursor_bisect_inset_input: StringProperty(name="Inset Input", default="")

    # Shortest Path Mark persistent properties
    shortest_mark_barrier_idx: IntProperty(name="Barrier Type Index", default=0, min=0, max=3)
    shortest_mark_mark_idx: IntProperty(name="Mark Type Index", default=0, min=0, max=3)
    shortest_mark_algorithm_idx: IntProperty(name="Algorithm Index", default=0, min=0, max=2)
    shortest_mark_flow_angle: IntProperty(name="Flow Angle", default=180, min=0, max=180)
    shortest_mark_sharp_angle: IntProperty(name="Sharp Angle", default=30, min=0, max=180)
