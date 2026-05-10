"""Object Color picker operators.

Drives the Object Color panel: assigns ``obj.color`` (the RGBA used by the
viewport's Solid > Object color shading mode) onto every selected object,
copies the active object's color back into the picker, and applies a recent
swatch.

Recents live on ``IOPS_SceneProperties`` as ``iops_object_color_recent_0..7``
with index 0 = most recently applied. Recents are mutated only on explicit
Apply Color (or push-on-equal during dedup) so that scrubbing the picker
does not flood the swatch row.
"""

import bpy
from bpy.props import IntProperty


# Must match the number of ``iops_object_color_recent_N`` properties declared
# on IOPS_SceneProperties.
RECENT_SLOTS = 8


def _get_recent(scene_props, index):
    return tuple(getattr(scene_props, f"iops_object_color_recent_{index}"))


def _set_recent(scene_props, index, color):
    setattr(scene_props, f"iops_object_color_recent_{index}", tuple(color))


def _colors_equal(a, b, eps=1e-5):
    return all(abs(a[i] - b[i]) < eps for i in range(4))


def push_recent_color(scene_props, color):
    """Push *color* to slot 0 with dedup; shift older entries down by one."""
    color = tuple(color)
    match = -1
    for i in range(RECENT_SLOTS):
        if _colors_equal(_get_recent(scene_props, i), color):
            match = i
            break
    end = match if match != -1 else RECENT_SLOTS - 1
    if end == 0:
        _set_recent(scene_props, 0, color)
        return
    for j in range(end, 0, -1):
        _set_recent(scene_props, j, _get_recent(scene_props, j - 1))
    _set_recent(scene_props, 0, color)


def _apply_to_selected(context, color):
    count = 0
    for obj in context.selected_objects:
        try:
            obj.color = color
            count += 1
        except (AttributeError, TypeError):
            # Some object types may reject the assign.
            continue
    return count


class IOPS_OT_ObjectColor_Apply(bpy.types.Operator):
    """Assign the picker color to obj.color of every selected object"""

    bl_idname = "iops.object_color_apply"
    bl_label = "Apply Color"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def execute(self, context):
        scene_props = context.scene.IOPS
        color = tuple(scene_props.iops_object_color)
        count = _apply_to_selected(context, color)
        if not count:
            self.report({"ERROR"}, "No selected objects accepted the color")
            return {"CANCELLED"}
        push_recent_color(scene_props, color)
        if context.area:
            context.area.tag_redraw()
        self.report({"INFO"}, f"Color applied to {count} object(s)")
        return {"FINISHED"}


class IOPS_OT_ObjectColor_CopyFromActive(bpy.types.Operator):
    """Copy the active object's color into the picker (no assign)"""

    bl_idname = "iops.object_color_copy_from_active"
    bl_label = "Copy From Active"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        obj = context.active_object
        if obj is None:
            self.report({"ERROR"}, "No active object")
            return {"CANCELLED"}
        scene_props = context.scene.IOPS
        scene_props.iops_object_color = tuple(obj.color)
        if context.area:
            context.area.tag_redraw()
        self.report({"INFO"}, f"Picker set from {obj.name}")
        return {"FINISHED"}


class IOPS_OT_ObjectColor_ApplyRecent(bpy.types.Operator):
    """Apply a recent swatch to selected objects and load it into the picker"""

    bl_idname = "iops.object_color_apply_recent"
    bl_label = "Apply Recent Color"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(
        name="Slot",
        description="Recent color slot (0 = most recent)",
        default=0,
        min=0,
        max=RECENT_SLOTS - 1,
    )

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def execute(self, context):
        scene_props = context.scene.IOPS
        color = _get_recent(scene_props, self.index)
        count = _apply_to_selected(context, color)
        if not count:
            self.report({"ERROR"}, "No selected objects accepted the color")
            return {"CANCELLED"}
        # Load into picker so subsequent Apply matches; do not reorder recents
        # so the swatch row stays stable while clicking through it.
        scene_props.iops_object_color = color
        if context.area:
            context.area.tag_redraw()
        self.report({"INFO"}, f"Recent color applied to {count} object(s)")
        return {"FINISHED"}
