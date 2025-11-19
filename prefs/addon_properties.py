import os
import bpy
from bpy.types import PropertyGroup
from bpy.props import (
    FloatProperty,
    FloatVectorProperty,
    StringProperty,
)

def fuzzy_match(search_term, target):
    """
    Fuzzy match: checks if all characters in search_term appear in order in target.
    Characters don't need to be consecutive.
    Example: "abc" matches "a_b_c", "abc", "aXbYc", etc.
    """
    if not search_term:
        return True
    
    search_term = search_term.lower()
    target = target.lower()
    
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
    if "IOPS" in bpy.context.scene and "executor_scripts" in bpy.context.scene["IOPS"]:
        scripts = bpy.context.scene["IOPS"]["executor_scripts"]
        filter_text = self.iops_exec_filter.lower()
        if filter_text:
            # Filter by script filename (not full path) using fuzzy search
            filtered_scripts = []
            for script in scripts:
                script_name = os.path.basename(script)
                if fuzzy_match(filter_text, script_name):
                    filtered_scripts.append(script)
            bpy.context.scene["IOPS"]["filtered_executor_scripts"] = filtered_scripts
        else:
            # Clear filter when empty
            if "filtered_executor_scripts" in bpy.context.scene["IOPS"]:
                del bpy.context.scene["IOPS"]["filtered_executor_scripts"]



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


class IOPS_SceneProperties(PropertyGroup):
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
