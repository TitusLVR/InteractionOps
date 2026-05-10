"""Object Color panel.

Sidebar panel under the iOps tab with: a color picker bound to
``scene.IOPS.iops_object_color``, an Apply button that pushes the color to
``obj.color`` of every selected object, a Copy From Active button that
loads the active object's color into the picker, and 8 recent-color
swatches with per-slot apply buttons.

The panel is intentionally read-only with respect to the recent slots:
clicking a swatch's apply button assigns that color to selected objects
and loads it into the picker, but does not reorder the swatch row.
"""

import bpy

from ..operators.object_color import RECENT_SLOTS


class IOPS_PT_Object_Color_Panel(bpy.types.Panel):
    """Object Color picker + recent swatches"""

    bl_label = "IOPS Object Color"
    bl_idname = "IOPS_PT_Object_Color_Panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "iOps"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        scene_props = context.scene.IOPS
        layout = self.layout

        col = layout.column(align=True)
        col.prop(scene_props, "iops_object_color", text="")

        row = col.row(align=True)
        row.operator(
            "iops.object_color_copy_from_active",
            icon="EYEDROPPER",
            text="Copy From Active",
        )

        col.separator()
        col.scale_y = 1.1
        col.operator(
            "iops.object_color_apply",
            icon="COLOR",
            text="Apply Color",
        )

        layout.separator()
        layout.label(text="Recent")

        # Two-row palette: top row = color swatches, bottom row = Apply buttons.
        # Splitting into a per-slot column keeps each swatch aligned with its
        # button regardless of UI scale.
        recents = layout.row(align=True)
        for i in range(RECENT_SLOTS):
            slot = recents.column(align=True)
            slot.prop(scene_props, f"iops_object_color_recent_{i}", text="")
            op = slot.operator(
                "iops.object_color_apply_recent",
                text=str(i + 1),
            )
            op.index = i
