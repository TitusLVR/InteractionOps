"""Sort Modifier Stacks + the user-editable sort order in preferences.

The order lives in two ordered lists on the addon prefs: `mod_sort_head`
(rules for the top of a stack) and `mod_sort_tail` (rules for the
bottom). A rule = a modifier type plus an optional comma-separated list
of names: empty = every modifier of that type, otherwise only those
whose name contains one of the names (case-insensitive). The first rule
that matches wins; everything unmatched stays in the middle with its
current relative order. The prefs UI draws both lists as one vertical
stack — top box, a dim "everything else" row, bottom box — each row =
type button + names field, so it reads exactly like a modifier stack.

Geometry-nodes modifiers match their names against both the modifier
name and the node group name, so the default rule NODES "Smooth by
Angle" (first in Top of Stack) catches Blender's auto smooth however
the modifier is called.
"""

import bpy

from ...utils.mod_sort_core import parse_names, sorted_names
from .iops_mod_registry import all_mod_type_items, type_icon

_ADDON = "InteractionOps"

# (type, names) — names as one comma-separated string, like the UI field
DEFAULT_HEAD = (("NODES", "Smooth by Angle"), ("MIRROR", ""), ("ARRAY", ""))
DEFAULT_TAIL = (("SIMPLE_DEFORM", ""), ("WEIGHTED_NORMAL", ""),
                ("TRIANGULATE", ""))

# Grouping for the add menu, mirroring Blender's Add Modifier submenus.
_MENU_GROUPS = (
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
    ("Nodes", ("NODES",)),
)


def _prefs(context):
    return context.preferences.addons[_ADDON].preferences


def match_text(md):
    """Text a rule's names are searched in: the modifier name, plus the
    node group name for geometry-nodes modifiers."""
    text = md.name
    if md.type == "NODES":
        ng = getattr(md, "node_group", None)
        if ng is not None:
            text = f"{text} | {ng.name}"
    return text


def sort_type_label(key):
    for ident, name, _icon in all_mod_type_items():
        if ident == key:
            return name
    return key.title().replace("_", " ")


def _band(prefs, band):
    return prefs.mod_sort_head if band == "HEAD" else prefs.mod_sort_tail


def _index_prop(band):
    return "mod_sort_head_index" if band == "HEAD" else "mod_sort_tail_index"


def rules(items):
    """Collection -> [(type, names tuple)] for the core."""
    return [(it.mod_type, parse_names(it.names)) for it in items]


def _fill(items, defaults):
    items.clear()
    for mod_type, names in defaults:
        it = items.add()
        it.mod_type = mod_type
        it.names = names


def reset_defaults(prefs):
    _fill(prefs.mod_sort_head, DEFAULT_HEAD)
    _fill(prefs.mod_sort_tail, DEFAULT_TAIL)
    prefs.mod_sort_head_index = 0
    prefs.mod_sort_tail_index = 0
    prefs.mod_sort_seeded = True


def seed_defaults_if_needed(prefs):
    """First run only (flag, not emptiness: the user may clear a list
    on purpose). Called from the grid seed timer."""
    if not prefs.mod_sort_seeded:
        reset_defaults(prefs)


class IOPS_ModSortItem(bpy.types.PropertyGroup):
    """One sort rule: a modifier type, optionally narrowed to names."""
    mod_type: bpy.props.StringProperty()
    names: bpy.props.StringProperty(
        name="Names",
        description="Comma-separated names. Empty: every modifier of this "
                    "type. Otherwise only modifiers of this type whose name "
                    "contains one of them (case-insensitive)",
    )


# --- add menus ---------------------------------------------------------

def _draw_add_menu(menu, context, band):
    by_key = {ident: (name, icon if icon != "NONE" else "MODIFIER")
              for ident, name, icon in all_mod_type_items()}

    def _entry(col, key):
        name, icon = by_key[key]
        op = col.operator("iops.mod_sort_list_add", text=name, icon=icon)
        op.band = band
        op.mod_type = key

    row = menu.layout.row()
    shown = set()
    for group, group_types in _MENU_GROUPS:
        present = [t for t in group_types if t in by_key]
        shown.update(present)
        if not present:
            continue
        col = row.column()
        col.label(text=group)
        col.separator()
        for key in present:
            _entry(col, key)
    other = [t for t in by_key if t not in shown]
    if other:
        col = row.column()
        col.label(text="Other")
        col.separator()
        for key in other:
            _entry(col, key)


class IOPS_MT_ModSortAddHead(bpy.types.Menu):
    """Add a rule to the top of the sort order"""

    bl_idname = "IOPS_MT_ModSortAddHead"
    bl_label = "Add to Top of Stack"

    def draw(self, context):
        _draw_add_menu(self, context, "HEAD")


class IOPS_MT_ModSortAddTail(bpy.types.Menu):
    """Add a rule to the bottom of the sort order"""

    bl_idname = "IOPS_MT_ModSortAddTail"
    bl_label = "Add to Bottom of Stack"

    def draw(self, context):
        _draw_add_menu(self, context, "TAIL")


_BAND_ITEMS = [
    ("HEAD", "Top of Stack", "Rules sorted to the top of the stack"),
    ("TAIL", "Bottom of Stack", "Rules sorted to the bottom of the stack"),
]


class IOPS_OT_ModSortListAdd(bpy.types.Operator):
    """Add a rule for this modifier type (repeat a type with different
    names to place its modifiers differently)"""

    bl_idname = "iops.mod_sort_list_add"
    bl_label = "Add Sort Rule"
    bl_options = {"REGISTER"}

    band: bpy.props.EnumProperty(items=_BAND_ITEMS, options={"SKIP_SAVE"})
    mod_type: bpy.props.StringProperty(options={"SKIP_SAVE"})

    def execute(self, context):
        prefs = _prefs(context)
        valid = {ident for ident, _n, _i in all_mod_type_items()}
        if self.mod_type not in valid:
            return {"CANCELLED"}
        items = _band(prefs, self.band)
        items.add().mod_type = self.mod_type
        setattr(prefs, _index_prop(self.band), len(items) - 1)
        return {"FINISHED"}


class IOPS_OT_ModSortListAction(bpy.types.Operator):
    """Sort order list action"""

    bl_idname = "iops.mod_sort_list_action"
    bl_label = "Sort Order Action"
    bl_options = {"REGISTER"}

    band: bpy.props.EnumProperty(items=_BAND_ITEMS, options={"SKIP_SAVE"})
    action: bpy.props.EnumProperty(
        items=[
            ("SELECT", "Select", "Make this rule the active one"),
            ("REMOVE", "Remove", "Remove the active rule (its modifiers "
             "will keep their current position when sorting)"),
            ("UP", "Move Up", "Move the active rule up in the stack"),
            ("DOWN", "Move Down", "Move the active rule down in the stack"),
            ("RESET", "Reset", "Restore the default sort order"),
        ],
        options={"SKIP_SAVE"},
    )
    index: bpy.props.IntProperty(default=-1, options={"SKIP_SAVE"})

    @classmethod
    def description(cls, context, properties):
        if properties.action == "SELECT":
            items = _band(_prefs(context), properties.band)
            idx = properties.index
            if 0 <= idx < len(items):
                it = items[idx]
                head = sort_type_label(it.mod_type)
                if it.names.strip():
                    head += f" named like: {it.names}"
                return f"{head}\nClick: select to move / remove"
        return None

    def execute(self, context):
        prefs = _prefs(context)
        if self.action == "RESET":
            reset_defaults(prefs)
            return {"FINISHED"}

        items = _band(prefs, self.band)
        idx_prop = _index_prop(self.band)
        idx = getattr(prefs, idx_prop)

        if self.action == "SELECT":
            if 0 <= self.index < len(items):
                setattr(prefs, idx_prop, self.index)
                return {"FINISHED"}
            return {"CANCELLED"}

        if idx < 0 or idx >= len(items):
            return {"CANCELLED"}

        if self.action == "REMOVE":
            items.remove(idx)
            setattr(prefs, idx_prop, min(idx, len(items) - 1))
        elif self.action == "UP" and idx > 0:
            items.move(idx, idx - 1)
            setattr(prefs, idx_prop, idx - 1)
        elif self.action == "DOWN" and idx < len(items) - 1:
            items.move(idx, idx + 1)
            setattr(prefs, idx_prop, idx + 1)
        return {"FINISHED"}


# --- prefs UI ---------------------------------------------------------

def _draw_band(parent, prefs, band, title, add_menu):
    items = _band(prefs, band)
    active = getattr(prefs, _index_prop(band))
    box = parent.box()
    box.label(text=title, icon="TRIA_UP_BAR" if band == "HEAD"
              else "TRIA_DOWN_BAR")
    row = box.row()
    rows = row.column(align=True)
    if not items:
        sub = rows.row()
        sub.enabled = False
        sub.label(text="(empty)")
    for i, it in enumerate(items):
        line = rows.row(align=True)
        split = line.split(factor=0.4, align=True)
        op = split.operator("iops.mod_sort_list_action",
                            text=sort_type_label(it.mod_type),
                            icon=type_icon(it.mod_type),
                            depress=(i == active))
        op.band = band
        op.action = "SELECT"
        op.index = i
        split.prop(it, "names", text="",
                   placeholder="Any name  (or: name, name, ...)")
    side = row.column(align=True)
    side.menu(add_menu, text="", icon="ADD")
    op = side.operator("iops.mod_sort_list_action", text="", icon="REMOVE")
    op.band = band
    op.action = "REMOVE"
    side.separator()
    op = side.operator("iops.mod_sort_list_action", text="", icon="TRIA_UP")
    op.band = band
    op.action = "UP"
    op = side.operator("iops.mod_sort_list_action", text="", icon="TRIA_DOWN")
    op.band = band
    op.action = "DOWN"


def draw_sort_order(layout, prefs):
    """The sort order as one vertical stack: top list, "everything else"
    row, bottom list."""
    header = layout.row()
    header.label(text="Sort Order", icon="SORTSIZE")
    op = header.operator("iops.mod_sort_list_action", text="Reset",
                         icon="FILE_REFRESH")
    op.action = "RESET"
    col = layout.column(align=True)
    _draw_band(col, prefs, "HEAD", "Top of Stack", "IOPS_MT_ModSortAddHead")
    mid = col.box().row()
    mid.enabled = False
    mid.label(text="Everything else — keeps its current order",
              icon="THREE_DOTS")
    _draw_band(col, prefs, "TAIL", "Bottom of Stack", "IOPS_MT_ModSortAddTail")


# --- the operator -----------------------------------------------------

class IOPS_OT_ModSortStack(bpy.types.Operator):
    """Sort modifier stacks across the selection by the order set in
    preferences (Top of Stack rules first, Bottom of Stack rules last,
    everything else keeps its relative order; a rule is a modifier type
    optionally narrowed to names)"""

    bl_idname = "iops.mod_sort_stack"
    bl_label = "Sort Modifier Stacks"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def execute(self, context):
        prefs = _prefs(context)
        head = rules(prefs.mod_sort_head)
        tail = rules(prefs.mod_sort_tail)
        changed = 0
        for obj in context.selected_objects:
            if len(obj.modifiers) < 2:
                continue
            current = [m.name for m in obj.modifiers]
            desired = sorted_names(
                [(m.name, m.type, match_text(m)) for m in obj.modifiers],
                head, tail)
            if desired == current:
                continue
            for target_idx, name in enumerate(desired):
                current_idx = obj.modifiers.find(name)
                if current_idx != target_idx:
                    obj.modifiers.move(current_idx, target_idx)
            changed += 1
        self.report({"INFO"}, f"Sorted stacks on {changed} object(s)")
        return {"FINISHED"}
