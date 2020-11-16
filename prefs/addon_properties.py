import bpy
from bpy.types import (Operator,
                       Menu,
                       Panel,
                       PropertyGroup,
                       UIList,
                       AddonPreferences)
from bpy.props import (BoolProperty,
                       EnumProperty,
                       FloatProperty,
                       FloatVectorProperty,
                       IntProperty,
                       PointerProperty,
                       CollectionProperty,
                       StringProperty)


class IOPS_AddonProperties (PropertyGroup): 
    iops_panel_mesh_info: bpy.props.BoolProperty(
        name="Show mesh info",
        description="Show mesh info panel",
        default=False
        )
    iops_vertex_color: FloatVectorProperty(
        name="VertexColor",
        description="Color picker",
        default=(1.0, 1.0, 1.0, 1.0),
        min=0.0,
        max=1.0,
        subtype='COLOR',
        size=4,
        )
    iops_rotation_angle: FloatProperty(
        name="Angle",
        description="Degrees",
        default=90,
        min = 0.0
        )
  
    