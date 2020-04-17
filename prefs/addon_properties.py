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
    