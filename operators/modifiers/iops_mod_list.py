"""User-built modifiers grid list.

The grid in the iOps Modifiers panel is exactly the user's list stored
in addon preferences (IOPS_ModGridItem collection): item count = button
count, list order = button order. A slot is a modifier type plus an
optional label plus its own default settings, so the same type can
appear several times with different presets (e.g. two Bevels). The
prefs UI draws the list as the same icon grid (WYSIWYG preview, click =
select) with an add (grouped menu of every type) / remove / move /
reset toolbar, plus the active slot's label and editable defaults.
"""

import bpy

from . import iops_mod_defaults as defaults
from . import iops_mod_presets as presets
from .iops_mod_registry import (
    CURATED_TYPES,
    all_mod_type_items,
    type_icon,
)

_ADDON = "InteractionOps"


def _prefs(context):
    return context.preferences.addons[_ADDON].preferences


def type_label(mod_type):
    for ident, name, _icon in all_mod_type_items():
        if ident == mod_type:
            return name
    return mod_type.title().replace("_", " ")


class IOPS_ModGridItem(bpy.types.PropertyGroup):
    mod_type: bpy.props.StringProperty()
    label: bpy.props.StringProperty(
        name="Label",
        description="Optional name for this grid slot. Shown in the "
                    "button tooltip and used as the modifier name when "
                    "adding — handy to tell copies of one type apart",
    )


# One defaults group per modifier type on every slot (see
# iops_mod_defaults). Must run before the class registers.
defaults.inject_pointer_props(IOPS_ModGridItem)


_seed_attempts = 0


def seed_grid_list_if_empty():
    """Timer callback: fill an empty grid list with the curated set and
    migrate legacy presets (pre-slot per-type groups, old json) into
    the slots. Runs via bpy.app.timers because prefs can't be written
    from register() during Blender startup — and retries while the
    context is still restricted at that point (plain 0.1s delay fires
    too early)."""
    global _seed_attempts
    try:
        prefs = bpy.context.preferences.addons[_ADDON].preferences
    except (KeyError, AttributeError):
        _seed_attempts += 1
        return 0.5 if _seed_attempts < 20 else None
    if len(prefs.modifiers_grid_items) == 0:
        for mod_type in CURATED_TYPES:
            prefs.modifiers_grid_items.add().mod_type = mod_type
        prefs.modifiers_grid_index = 0
    presets.migrate_type_groups_to_slots(prefs)
    presets.migrate_legacy_json(prefs)
    return None


# Grouping mirroring Blender's Add Modifier menu (OBJECT_MT_modifier_add
# submenus). Types this Blender build doesn't have are skipped; enum
# types not listed here land in "Other".
MENU_GROUPS = (
    ("Edit", ("DATA_TRANSFER", "MESH_CACHE", "MESH_SEQUENCE_CACHE",
              "UV_PROJECT", "UV_WARP", "VERTEX_WEIGHT_EDIT",
              "VERTEX_WEIGHT_MIX", "VERTEX_WEIGHT_PROXIMITY")),
    ("Generate", ("ARRAY", "BEVEL", "BOOLEAN", "BUILD", "DECIMATE",
                  "EDGE_SPLIT", "MASK", "MIRROR", "MESH_TO_VOLUME",
                  "MULTIRES", "REMESH", "SCREW", "SKIN", "SOLIDIFY",
                  "SUBSURF", "TRIANGULATE", "VOLUME_TO_MESH", "WELD",
                  "WIREFRAME")),
    ("Deform", ("ARMATURE", "CAST", "CURVE", "DISPLACE", "HOOK",
                "LAPLACIANDEFORM", "LATTICE", "MESH_DEFORM",
                "SHRINKWRAP", "SIMPLE_DEFORM", "SMOOTH",
                "CORRECTIVE_SMOOTH", "LAPLACIANSMOOTH", "SURFACE_DEFORM",
                "WARP", "WAVE", "VOLUME_DISPLACE")),
    ("Normals", ("NORMAL_EDIT", "WEIGHTED_NORMAL")),
    ("Physics", ("CLOTH", "COLLISION", "DYNAMIC_PAINT", "EXPLODE",
                 "FLUID", "OCEAN", "PARTICLE_INSTANCE", "PARTICLE_SYSTEM",
                 "SOFT_BODY", "SURFACE")),
)


class IOPS_MT_ModGridAdd(bpy.types.Menu):
    """Add-modifier-style menu: grouped columns of every type. Types
    already in the grid stay listed — adding one again makes a second
    slot with its own defaults."""

    bl_idname = "IOPS_MT_ModGridAdd"
    bl_label = "Add Modifier Type"

    def draw(self, context):
        in_grid = {}
        for it in _prefs(context).modifiers_grid_items:
            in_grid[it.mod_type] = in_grid.get(it.mod_type, 0) + 1
        by_ident = {ident: (name, icon)
                    for ident, name, icon in all_mod_type_items()}

        def _entry(col, mod_type):
            name, icon = by_ident[mod_type]
            count = in_grid.get(mod_type, 0)
            if count:
                name = f"{name}  ({count} in grid)"
            op = col.operator("iops.mod_grid_list_add", text=name,
                              icon=icon if icon != "NONE" else "MODIFIER")
            op.mod_type = mod_type

        row = self.layout.row()
        shown = set()
        for group, group_types in MENU_GROUPS:
            present = [t for t in group_types if t in by_ident]
            shown.update(present)
            if not present:
                continue
            col = row.column()
            col.label(text=group)
            col.separator()
            for mod_type in present:
                _entry(col, mod_type)
        other = [t for t in by_ident if t not in shown]
        if other:
            col = row.column()
            col.label(text="Other")
            col.separator()
            for mod_type in other:
                _entry(col, mod_type)


class IOPS_OT_ModGridListAdd(bpy.types.Operator):
    """Add a grid slot of this modifier type (repeat a type to get a
    second slot with its own default settings)"""

    bl_idname = "iops.mod_grid_list_add"
    bl_label = "Add Modifier Type"
    bl_options = {"REGISTER"}

    mod_type: bpy.props.StringProperty(options={"SKIP_SAVE"})

    def execute(self, context):
        prefs = _prefs(context)
        valid = {ident for ident, _n, _i in all_mod_type_items()}
        if self.mod_type not in valid:
            return {"CANCELLED"}
        prefs.modifiers_grid_items.add().mod_type = self.mod_type
        prefs.modifiers_grid_index = len(prefs.modifiers_grid_items) - 1
        return {"FINISHED"}


class IOPS_OT_ModGridListAction(bpy.types.Operator):
    """Modifiers grid list action"""

    bl_idname = "iops.mod_grid_list_action"
    bl_label = "Grid List Action"
    bl_options = {"REGISTER"}

    action: bpy.props.EnumProperty(
        items=[
            ("SELECT", "Select", "Make this grid button the active one"),
            ("REMOVE", "Remove", "Remove the active slot from the grid"),
            ("UP", "Move Earlier", "Move the active slot earlier in the "
             "grid order"),
            ("DOWN", "Move Later", "Move the active slot later in the "
             "grid order"),
            ("RESET", "Reset", "Restore the default curated set"),
            ("CLEAR_PRESET", "Reset Defaults",
             "Reset the active slot's default settings"),
        ],
        options={"SKIP_SAVE"},
    )
    index: bpy.props.IntProperty(default=-1, options={"SKIP_SAVE"})

    @classmethod
    def description(cls, context, properties):
        if properties.action == "SELECT":
            prefs = _prefs(context)
            idx = properties.index
            if 0 <= idx < len(prefs.modifiers_grid_items):
                item = prefs.modifiers_grid_items[idx]
                head = presets.slot_label(item)
                if item.label:
                    head += f" ({type_label(item.mod_type)})"
                return (f"{head}\n"
                        "Click: select to move / remove / edit defaults")
        return None

    def execute(self, context):
        prefs = _prefs(context)
        items = prefs.modifiers_grid_items
        idx = prefs.modifiers_grid_index

        if self.action == "SELECT":
            if 0 <= self.index < len(items):
                prefs.modifiers_grid_index = self.index
                return {"FINISHED"}
            return {"CANCELLED"}

        if self.action == "RESET":
            items.clear()
            for mod_type in CURATED_TYPES:
                items.add().mod_type = mod_type
            prefs.modifiers_grid_index = 0
            return {"FINISHED"}

        if idx < 0 or idx >= len(items):
            return {"CANCELLED"}

        if self.action == "REMOVE":
            items.remove(idx)
            prefs.modifiers_grid_index = min(idx, len(items) - 1)
        elif self.action == "UP" and idx > 0:
            items.move(idx, idx - 1)
            prefs.modifiers_grid_index = idx - 1
        elif self.action == "DOWN" and idx < len(items) - 1:
            items.move(idx, idx + 1)
            prefs.modifiers_grid_index = idx + 1
        elif self.action == "CLEAR_PRESET":
            item = items[idx]
            if presets.clear_default(item):
                self.report({"INFO"},
                            f"{presets.slot_label(item)}: defaults reset")
            else:
                self.report({"WARNING"},
                            f"{item.mod_type}: no defaults group for this type")
        return {"FINISHED"}


class IOPS_MT_ModSaveDefaultSlot(bpy.types.Menu):
    """Pick which grid slot receives the modifier's settings when the
    grid holds several slots of that type."""

    bl_idname = "IOPS_MT_ModSaveDefaultSlot"
    bl_label = "Save as Default for Slot"

    def draw(self, context):
        obj = context.active_object
        md = obj.modifiers.active if obj is not None else None
        layout = self.layout
        if md is None:
            layout.label(text="No active modifier", icon="ERROR")
            return
        for idx, item in presets.slots_of_type(_prefs(context), md.type):
            op = layout.operator("iops.mod_save_slot_default",
                                 text=f"{idx + 1}: {presets.slot_label(item)}",
                                 icon=type_icon(md.type))
            op.index = idx
            op.modifier_name = md.name


class IOPS_OT_ModSaveSlotDefault(bpy.types.Operator):
    """Save the active object's modifier settings as the default
    preset of one grid slot"""

    bl_idname = "iops.mod_save_slot_default"
    bl_label = "Save as Slot Default"
    bl_options = {"REGISTER"}

    index: bpy.props.IntProperty(default=-1, options={"SKIP_SAVE"})
    modifier_name: bpy.props.StringProperty(options={"SKIP_SAVE"})

    def execute(self, context):
        obj = context.active_object
        md = obj.modifiers.get(self.modifier_name) if obj else None
        if md is None:
            self.report({"WARNING"}, "Modifier not found")
            return {"CANCELLED"}
        items = _prefs(context).modifiers_grid_items
        if not (0 <= self.index < len(items)):
            self.report({"WARNING"}, "Grid slot out of range")
            return {"CANCELLED"}
        item = items[self.index]
        if presets.save_default(md, item):
            self.report({"INFO"},
                        f"{md.name}: saved as default for grid slot "
                        f"'{presets.slot_label(item)}'")
            return {"FINISHED"}
        self.report({"WARNING"},
                    f"{md.type}: slot type mismatch or no editable params")
        return {"CANCELLED"}


def save_default_from_stack(op, context, md):
    """Route a 'save as default' from the stack list: one slot of the
    type → save there; several → popup to pick; none → warn."""
    slots = presets.slots_of_type(_prefs(context), md.type)
    if not slots:
        op.report({"WARNING"},
                  f"{type_label(md.type)}: not in the grid — add it in "
                  "the addon preferences first")
        return
    if len(slots) == 1:
        idx, item = slots[0]
        if presets.save_default(md, item):
            op.report({"INFO"},
                      f"{md.name}: saved as default for grid slot "
                      f"'{presets.slot_label(item)}'")
        else:
            op.report({"WARNING"},
                      f"{md.type}: no editable params to save")
        return
    bpy.ops.wm.call_menu(name=IOPS_MT_ModSaveDefaultSlot.bl_idname)
