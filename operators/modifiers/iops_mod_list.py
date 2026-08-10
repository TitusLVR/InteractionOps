"""User-built modifiers grid list.

The grid in the iOps Modifiers panel is exactly the user's list stored
in addon preferences (IOPS_ModGridItem collection): item count = button
count, list order = button order. The prefs UI draws it as the same
icon grid (WYSIWYG preview, click = select) with an add (search popup) /
remove / move / reset toolbar, plus a read-only view of the active
type's saved default preset.
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


_seed_attempts = 0


def seed_grid_list_if_empty():
    """Timer callback: fill an empty grid list with the curated set and
    migrate legacy json presets into the defaults groups. Runs via
    bpy.app.timers because prefs can't be written from register()
    during Blender startup — and retries while the context is still
    restricted at that point (plain 0.1s delay fires too early)."""
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
    """Add-modifier-style menu: grouped columns of types to add"""

    bl_idname = "IOPS_MT_ModGridAdd"
    bl_label = "Add Modifier Type"

    def draw(self, context):
        existing = {it.mod_type
                    for it in _prefs(context).modifiers_grid_items}
        available = [(ident, name, icon)
                     for ident, name, icon in all_mod_type_items()
                     if ident not in existing]
        by_ident = {ident: (name, icon) for ident, name, icon in available}

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
                name, icon = by_ident[mod_type]
                op = col.operator("iops.mod_grid_list_add", text=name,
                                  icon=icon if icon != "NONE"
                                  else "MODIFIER")
                op.mod_type = mod_type
        other = [t for t, _n, _i in available if t not in shown]
        if other:
            col = row.column()
            col.label(text="Other")
            col.separator()
            for mod_type in other:
                name, icon = by_ident[mod_type]
                op = col.operator("iops.mod_grid_list_add", text=name,
                                  icon=icon if icon != "NONE"
                                  else "MODIFIER")
                op.mod_type = mod_type


class IOPS_OT_ModGridListAdd(bpy.types.Operator):
    """Add this modifier type to the grid"""

    bl_idname = "iops.mod_grid_list_add"
    bl_label = "Add Modifier Type"
    bl_options = {"REGISTER"}

    mod_type: bpy.props.StringProperty(options={"SKIP_SAVE"})

    def execute(self, context):
        prefs = _prefs(context)
        if not self.mod_type or any(
                it.mod_type == self.mod_type
                for it in prefs.modifiers_grid_items):
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
            ("REMOVE", "Remove", "Remove the active type from the grid"),
            ("UP", "Move Earlier", "Move the active type earlier in the "
             "grid order"),
            ("DOWN", "Move Later", "Move the active type later in the "
             "grid order"),
            ("RESET", "Reset", "Restore the default curated set"),
            ("CLEAR_PRESET", "Reset Defaults",
             "Reset the active type's default settings"),
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
                return (f"{type_label(prefs.modifiers_grid_items[idx].mod_type)}\n"
                        "Click: select to move / remove / inspect defaults")
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
            mod_type = items[idx].mod_type
            if presets.clear_default(mod_type):
                self.report({"INFO"},
                            f"{mod_type}: defaults reset")
            else:
                self.report({"WARNING"},
                            f"{mod_type}: no defaults group for this type")
        return {"FINISHED"}
