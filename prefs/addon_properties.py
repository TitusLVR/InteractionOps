import bpy
from bpy.types import Operator, Menu, Panel, PropertyGroup, UIList, AddonPreferences
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    CollectionProperty,
    StringProperty,
)

def update_exec_filter(self, context):    
    bpy.ops.iops.scripts_call_mt_executor()


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
        # options={'TEXTEDIT_UPDATE'},
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
