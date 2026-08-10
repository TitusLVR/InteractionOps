"""User-built modifiers grid list.

The grid in the iOps Modifiers panel is exactly the user's list stored
in addon preferences (IOPS_ModGridItem collection): item count = button
count, list order = button order. The prefs UI draws it as a UIList
with add (search popup) / remove / move / reset, plus a read-only view
of the active type's saved default preset.
"""

import bpy

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


class IOPS_UL_ModGridList(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname):
        layout.label(text=type_label(item.mod_type),
                     icon=type_icon(item.mod_type))


def seed_grid_list_if_empty():
    """One-shot timer callback: fill an empty grid list with the curated
    set. Runs via bpy.app.timers because prefs can't be written from
    register() during Blender startup (restricted context)."""
    try:
        prefs = bpy.context.preferences.addons[_ADDON].preferences
    except (KeyError, AttributeError):
        return None
    if len(prefs.modifiers_grid_items) == 0:
        for mod_type in CURATED_TYPES:
            prefs.modifiers_grid_items.add().mod_type = mod_type
        prefs.modifiers_grid_index = 0
    return None


# Enum-items callback results must stay referenced on the Python side
# or Blender reads freed strings — module-level cache.
_enum_cache = []


def _available_types(self, context):
    global _enum_cache
    existing = {it.mod_type for it in _prefs(context).modifiers_grid_items}
    _enum_cache = [
        (ident, name, "", icon if icon != "NONE" else "MODIFIER", i)
        for i, (ident, name, icon) in enumerate(all_mod_type_items())
        if ident not in existing
    ]
    if not _enum_cache:
        _enum_cache = [("NONE", "All types are already in the grid", "",
                        "INFO", 0)]
    return _enum_cache


class IOPS_OT_ModGridListAdd(bpy.types.Operator):
    """Add a modifier type to the grid (search by name)"""

    bl_idname = "iops.mod_grid_list_add"
    bl_label = "Add Modifier Type"
    bl_options = {"REGISTER"}
    bl_property = "mod_type"

    mod_type: bpy.props.EnumProperty(items=_available_types,
                                     options={"SKIP_SAVE"})

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {"FINISHED"}

    def execute(self, context):
        if self.mod_type == "NONE":
            return {"CANCELLED"}
        prefs = _prefs(context)
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
            ("REMOVE", "Remove", "Remove the active type from the grid"),
            ("UP", "Move Up", "Move the active type up"),
            ("DOWN", "Move Down", "Move the active type down"),
            ("RESET", "Reset", "Restore the default curated set"),
            ("CLEAR_PRESET", "Clear Preset",
             "Delete the saved default preset of the active type"),
        ],
        options={"SKIP_SAVE"},
    )

    def execute(self, context):
        prefs = _prefs(context)
        items = prefs.modifiers_grid_items
        idx = prefs.modifiers_grid_index

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
            mod_type = items[idx].mod_type
            if presets.clear_default(mod_type):
                self.report({"INFO"},
                            f"{mod_type}: default preset cleared")
            else:
                self.report({"WARNING"},
                            f"{mod_type}: no saved preset to clear")
        return {"FINISHED"}


def format_value(value):
    """Compact human-readable preset value for the prefs read-only view."""
    if isinstance(value, float):
        return f"{value:.4g}"
    if isinstance(value, (list, tuple)):
        return "(" + ", ".join(format_value(v) for v in value) + ")"
    return str(value)
