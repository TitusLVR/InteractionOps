"""WindowManager property registration for the ported library addon.

These are transient (SKIP_SAVE) UI-state properties: the status/busy/placement
scratch values plus the per-category "expanded" toggles used by the sidebar
panel added in a later task.
"""

import bpy
from bpy.props import BoolProperty, FloatVectorProperty, StringProperty

CATEGORY_DEFINITIONS = (
    ("GEOMETRY", "Geometry", "MESH_CUBE", "iops_library_geometry_expanded"),
    ("SHADERS", "Materials & Shaders", "MATERIAL", "iops_library_shaders_expanded"),
    ("LIGHTS", "Lights & Worlds", "LIGHT", "iops_library_lights_expanded"),
    ("MISC", "Misc", "ASSET_MANAGER", "iops_library_misc_expanded"),
)


def register_wm_properties():
    bpy.types.WindowManager.iops_library_status = StringProperty(
        name="Library Status",
        default="",
        options={"SKIP_SAVE"},
    )
    bpy.types.WindowManager.iops_library_busy = BoolProperty(
        name="Library Busy",
        default=False,
        options={"SKIP_SAVE"},
    )
    bpy.types.WindowManager.iops_library_placement = FloatVectorProperty(
        name="Library Placement",
        size=3,
        subtype="TRANSLATION",
        options={"SKIP_SAVE"},
    )
    for _category, _label, _icon, property_name in CATEGORY_DEFINITIONS:
        setattr(
            bpy.types.WindowManager,
            property_name,
            BoolProperty(default=True, options={"SKIP_SAVE"}),
        )


def unregister_wm_properties():
    for _category, _label, _icon, property_name in CATEGORY_DEFINITIONS:
        if hasattr(bpy.types.WindowManager, property_name):
            delattr(bpy.types.WindowManager, property_name)
    for property_name in (
        "iops_library_placement",
        "iops_library_busy",
        "iops_library_status",
    ):
        if hasattr(bpy.types.WindowManager, property_name):
            delattr(bpy.types.WindowManager, property_name)
