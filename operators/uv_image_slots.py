"""UV image slots: per-slot WindowManager StringProperty (the stored image
name, session-only) + the DROPDOWN items provider + the one-click flip
operator behind the uv_image_slots widget.

Each slot stores an image NAME in ``iops_uv_slot_N_name`` on WindowManager
(SKIP_SAVE — never written to the .blend). The widget's DROPDOWN lists its
choices via the ``"uv_images"`` items provider registered here: a dynamic
(items-callback) EnumProperty does NOT expose its items through ``bl_rna``
in script context, so the custom GPU dropdown reads them from this live
provider instead and writes the chosen image name straight into the
StringProperty.

The flip operator reads a slot's stored name and sets it as the active
image of an Image/UV editor — the invoking one if the click happened
there, otherwise the largest Image editor open in the window (so it works
when toggled from the 3D viewport).
"""
import bpy
from bpy.props import IntProperty, StringProperty

from ..widgets.uv_slots_logic import SENTINEL

SLOT_COUNT = 3
ITEMS_PROVIDER = "uv_images"


def uv_image_items(context):
    """Live DROPDOWN items: '— none —' (SENTINEL, index 0) then every image
    name in bpy.data.images. (identifier, label) pairs."""
    items = [(SENTINEL, "— none —")]
    items.extend((img.name, img.name) for img in bpy.data.images)
    return items


def register_slot_props():
    """Define the per-slot WindowManager StringProperties (session-only) and
    register the live image-items provider the widget's dropdowns read.
    Runs before the composed widgets are built (see __init__.register), so
    the dropdowns pick up the provider rather than the empty enum fallback."""
    from ..widgets import composed
    for slot in range(SLOT_COUNT):
        setattr(bpy.types.WindowManager, "iops_uv_slot_%d_name" % slot,
                StringProperty(
                    name="UV Slot %d Image" % slot,
                    description="Stored image name for UV image slot %d" % slot,
                    default="",
                    options={"SKIP_SAVE"},
                ))
    composed.register_dropdown_items(ITEMS_PROVIDER, uv_image_items)


def unregister_slot_props():
    from ..widgets import composed
    composed.unregister_dropdown_items(ITEMS_PROVIDER)
    for slot in range(SLOT_COUNT):
        attr = "iops_uv_slot_%d_name" % slot
        if hasattr(bpy.types.WindowManager, attr):
            delattr(bpy.types.WindowManager, attr)


def _target_image_space(context):
    """The SpaceImageEditor to retarget: the invoking editor when the click
    happened in one, else the largest Image editor open in the window.
    None when no Image/UV editor is open."""
    sd = context.space_data
    if sd is not None and getattr(sd, "type", None) == "IMAGE_EDITOR":
        return sd
    from ..ui.widgets import state
    area = state.find_largest_area("IMAGE_EDITOR")
    if area is None:
        return None
    return area.spaces.active


class IOPS_OT_uv_image_slot_flip(bpy.types.Operator):
    """Set the UV/Image editor's active image to the one stored in this slot"""

    bl_idname = "iops.uv_image_slot_flip"
    bl_label = "IOPS UV Image Slot Flip"
    bl_options = {"REGISTER", "UNDO"}

    slot: IntProperty(name="Slot", default=0, min=0)

    def execute(self, context):
        wm = context.window_manager
        name = getattr(wm, "iops_uv_slot_%d_name" % self.slot, "")
        if not name:
            self.report({"INFO"}, "IOPS: slot %d is empty" % self.slot)
            return {"CANCELLED"}
        img = bpy.data.images.get(name)
        if img is None:
            self.report({"INFO"}, "IOPS: slot image '%s' not found" % name)
            return {"CANCELLED"}
        space = _target_image_space(context)
        if space is None:
            self.report({"INFO"}, "IOPS: no UV/Image editor open")
            return {"CANCELLED"}
        space.image = img
        return {"FINISHED"}


classes = (IOPS_OT_uv_image_slot_flip,)
