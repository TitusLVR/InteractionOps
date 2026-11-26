"""Functions menu of the iOps Materials panel: reassign and cleanup tools.
Every tool obeys the compatibility rule of common.skip_reason() and reports
counts."""
import bpy

from ...utils import materials_core as core
from . import common, slots, state


def _report(op, text, skipped=None):
    tail = core.format_skipped(skipped or {})
    op.report({"INFO"}, f"{text}, {tail}" if tail else text)


def _unique_data(objects):
    seen, out = set(), []
    for obj in objects:
        key = obj.data.as_pointer()
        if key not in seen:
            seen.add(key)
            out.append(obj)
    return out


# ----------------------------------------------------------------------
# Copy from active
# ----------------------------------------------------------------------
class IOPS_OT_MaterialsCopyFromActive(bpy.types.Operator):
    """Give the other selected objects the material slots of the active
    object"""

    bl_idname = "iops.materials_copy_from_active"
    bl_label = "Copy Materials from Active"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        active = context.view_layer.objects.active
        if active is None or not common.is_compatible(active):
            self.report({"WARNING"}, "The active object has no materials to "
                                     "copy")
            return {"CANCELLED"}
        mats = [slot.material for slot in active.material_slots]
        others = [o for o in common.selected_objects(context) if o != active]
        good, skipped = common.split_compatible(others)
        done = 0
        for obj in _unique_data(good):
            if obj.data == active.data:
                continue
            obj.data.materials.clear()
            for mat in mats:
                obj.data.materials.append(mat)
        for obj in good:
            if obj.data != active.data:
                done += 1
        if not good:
            self.report({"WARNING"}, "No other selected object can take "
                        "materials" + (f": {core.format_skipped(skipped)}"
                                       if skipped else ""))
            return {"CANCELLED"}
        state.invalidate_sources()
        _report(self, f"Copied {core.plural(len(mats), 'slot')} to "
                      f"{core.plural(done, 'object')}", skipped)
        return {"FINISHED"}


# ----------------------------------------------------------------------
# Select users
# ----------------------------------------------------------------------
class IOPS_OT_MaterialsSelectUsers(bpy.types.Operator):
    """Select the objects in the scene that use the panel's active
    material"""

    bl_idname = "iops.materials_select_users"
    bl_label = "Select Objects Using Material"
    bl_options = {"REGISTER", "UNDO"}

    # set by the user-count button of a list row; empty: the active material
    material: bpy.props.StringProperty(options={"SKIP_SAVE", "HIDDEN"})
    library: bpy.props.StringProperty(options={"SKIP_SAVE", "HIDDEN"})

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT"

    def execute(self, context):
        if self.material:
            mat = common.find_material(self.material, self.library)
            if mat is not None:
                state.set_active(mat, context)
        else:
            mat = state.active_material(context)
        if mat is None:
            self.report({"WARNING"}, "No active material in the panel")
            return {"CANCELLED"}
        users = []
        for obj in common.view_layer_objects(context):
            uses = any(s.material == mat for s in
                       getattr(obj, "material_slots", ()))
            selectable = obj.visible_get() and not obj.hide_select
            obj.select_set(uses and selectable)
            if uses and selectable:
                users.append(obj)
        if users and context.view_layer.objects.active not in users:
            context.view_layer.objects.active = users[0]
        self.report({"INFO"}, f"Selected {core.plural(len(users), 'object')} "
                              f"using {mat.name}")
        return {"FINISHED"}


# ----------------------------------------------------------------------
# Remove unused slots
# ----------------------------------------------------------------------
def remove_unused_slots(data):
    """Remove the slots of `data` that no face / spline uses and the empty
    slots. Faces of a removed (empty) slot go to the first remaining slot.
    Returns the number of slots removed. The caller checks
    slots.slot_skip_reason() first."""
    used = slots.used_indices(data)
    doomed = [i for i, m in enumerate(data.materials)
              if m is None or i not in used]
    return slots.remove_slots(data, doomed)


def _slot_tool(op, context, objects, work, noun):
    """Run `work(data) -> removed count` once per compatible data of
    `objects`; skip and count incompatible objects and data whose slots
    cannot be removed safely. Reports 'Removed N <noun>s on M objects'."""
    good, skipped = common.split_compatible(objects)
    if not good:
        op.report({"WARNING"}, "No object can take materials"
                  + (f": {core.format_skipped(skipped)}" if skipped else ""))
        return {"CANCELLED"}
    users = slots.data_users()
    removed, done = 0, 0
    per_data = {}
    for obj in good:
        per_data.setdefault(obj.data.as_pointer(), (obj.data, []))[1].append(obj)
    for key, (data, objs) in per_data.items():
        reason = slots.slot_skip_reason(data, users.get(key, objs))
        if reason is not None:
            skipped[reason] = skipped.get(reason, 0) + len(objs)
            continue
        n = work(data)
        removed += n
        if n:
            done += len(objs)
    state.invalidate_sources()
    common.tag_redraw(context)
    _report(op, f"Removed {core.plural(removed, noun)} on "
                f"{core.plural(done, 'object')}", skipped)
    return {"FINISHED"}


class IOPS_OT_MaterialsRemoveUnusedSlots(bpy.types.Operator):
    """Remove the material slots of the selected objects that no face uses,
    and the empty slots (their faces go to the first remaining slot)"""

    bl_idname = "iops.materials_remove_unused_slots"
    bl_label = "Remove Unused Slots"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return _slot_tool(
            self, context, common.target_objects(context), remove_unused_slots,
            "slot")


_SCOPE_ITEMS = (
    ("SELECTED", "Selected Objects", "The selected objects (in Edit Mode: "
     "the objects being edited)"),
    ("SCENE", "Scene", "Every object in the scene"),
)


def remove_empty_slots(data):
    """Remove every empty slot of `data`; their faces go to the first
    remaining slot."""
    return slots.remove_slots(
        data, [i for i, m in enumerate(data.materials) if m is None])


class IOPS_OT_MaterialsRemoveEmptySlots(bpy.types.Operator):
    """Remove every empty material slot (a slot without a material); faces
    on it go to the first remaining slot"""

    bl_idname = "iops.materials_remove_empty_slots"
    bl_label = "Remove Empty Slots"
    bl_options = {"REGISTER", "UNDO"}

    scope: bpy.props.EnumProperty(name="In", items=_SCOPE_ITEMS,
                                  default="SELECTED")

    def execute(self, context):
        objects = (list(context.scene.objects) if self.scope == "SCENE"
                   else common.target_objects(context))
        return _slot_tool(self, context, objects, remove_empty_slots,
                          "empty slot")


# ----------------------------------------------------------------------
# Clear
# ----------------------------------------------------------------------
class IOPS_OT_MaterialsClear(bpy.types.Operator):
    """Remove all material slots"""

    bl_idname = "iops.materials_clear"
    bl_label = "Clear All Materials"
    bl_options = {"REGISTER", "UNDO"}

    scope: bpy.props.EnumProperty(
        name="In",
        items=(
            ("SELECTED", "Selected Objects", "Clear the selected objects"),
            ("SCENE", "Scene", "Clear every object in the scene"),
        ),
        default="SELECTED")

    @classmethod
    def description(cls, context, properties):
        if properties.scope == "SCENE":
            return "Remove all material slots of every object in the scene"
        return "Remove all material slots of the selected objects"

    def invoke(self, context, event):
        if self.scope == "SCENE":
            good, _skipped = common.split_compatible(context.scene.objects)
            return context.window_manager.invoke_confirm(
                self, event, title="Clear All Materials",
                message=f"Remove every material slot of "
                        f"{core.plural(len(good), 'object')} in the scene?",
                confirm_text="Clear", icon="WARNING")
        return self.execute(context)

    def execute(self, context):
        objects = (list(context.scene.objects) if self.scope == "SCENE"
                   else common.target_objects(context))
        good, skipped = common.split_compatible(objects)
        if not good:
            self.report({"WARNING"}, "No object can take materials")
            return {"CANCELLED"}
        for obj in _unique_data(good):
            obj.data.materials.clear()
        state.invalidate_sources()
        where = " in the scene" if self.scope == "SCENE" else ""
        _report(self, f"Cleared materials of "
                      f"{core.plural(len(good), 'object')}{where}",
                skipped if self.scope == "SELECTED" else None)
        return {"FINISHED"}


# ----------------------------------------------------------------------
# Delete unused
# ----------------------------------------------------------------------
def unused_materials():
    """Local materials with no real user (a fake user does not count)."""
    return [m for m in bpy.data.materials
            if m.library is None and common.real_users(m) <= 0]


class IOPS_OT_MaterialsDeleteUnused(bpy.types.Operator):
    """Delete the local materials no object or other data uses (a fake user
    does not count). Linked materials are left alone"""

    bl_idname = "iops.materials_delete_unused"
    bl_label = "Delete Unused Materials"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        n = len(unused_materials())
        if not n:
            self.report({"INFO"}, "No unused materials")
            return {"CANCELLED"}
        return context.window_manager.invoke_confirm(
            self, event, title="Delete Unused Materials",
            message=f"Delete {core.plural(n, 'unused material')}?",
            confirm_text="Delete", icon="WARNING")

    def execute(self, context):
        doomed = unused_materials()
        for mat in doomed:
            bpy.data.materials.remove(mat)
        state.invalidate_sources()
        self.report({"INFO"},
                    f"Deleted {core.plural(len(doomed), 'unused material')}")
        return {"FINISHED"}
