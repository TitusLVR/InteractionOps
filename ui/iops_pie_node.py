"""Contextual pie for the Geometry Nodes and Shader editors.

One tree-type-agnostic menu: it reads the active node at draw time and asks the
rule store what to offer. Slot order is Blender's pie order (W, E, S, N, NW,
NE, SW, SE) and matches the `slots` list index in the preset JSON.
"""
import json

import bpy
from bpy.types import Menu

from ..operators.node_pie import store
from ..utils import node_pie_rules as nr

SUPPORTED_TREES = store.TREE_TYPES

#: Icon ids Blender actually knows, filled on first use. `normalise_rule`
#: guarantees `icon` is a string; it cannot know whether the string names a
#: real icon. A typo, or an icon dropped in a later Blender, raises TypeError
#: inside `UILayout.operator()` — i.e. inside a draw callback, which must
#: never raise. Cached at module level because the enum has ~1000 entries.
_ICON_IDS: frozenset | None = None


def _icon_for(entry, default='NONE'):
    """The entry's icon if Blender has it, else `default` plus a one-time warning."""
    global _ICON_IDS
    icon = entry.get("icon")
    if not icon:
        return default
    if _ICON_IDS is None:
        try:
            params = bpy.types.UILayout.bl_rna.functions["operator"].parameters
            _ICON_IDS = frozenset(params["icon"].enum_items.keys())
        except (KeyError, AttributeError) as exc:
            # Probe failed: accept anything rather than strip every icon.
            store.warn_once(f"could not read the icon enum ({exc}); icons unchecked")
            _ICON_IDS = frozenset()
    if _ICON_IDS and icon not in _ICON_IDS:
        store.warn_once(f"unknown icon {icon!r} on slot for {entry['node']}")
        return default
    return icon


def _node_label(entry):
    if entry.get("text"):
        return entry["text"]
    cls = getattr(bpy.types, entry["node"], None)
    return getattr(cls, "bl_label", entry["node"])


class IOPS_MT_Pie_Node(Menu):
    bl_idname = "IOPS_MT_Pie_Node"
    bl_label = "IOPS Node Pie"

    @classmethod
    def poll(cls, context):
        space = context.space_data
        if (
            space is None
            or space.type != 'NODE_EDITOR'
            or space.edit_tree is None
            or space.edit_tree.bl_idname not in SUPPORTED_TREES
        ):
            return False
        # Material, world and line-style shader trees all report
        # bl_idname == 'ShaderNodeTree'; only `space.shader_type` tells them
        # apart. World and line style are explicit non-goals, so gate on it.
        # `getattr` because the attribute exists only on the shader path —
        # a Geometry Nodes editor must not trip over it.
        if space.edit_tree.bl_idname == "ShaderNodeTree":
            return getattr(space, "shader_type", 'OBJECT') == 'OBJECT'
        return True

    def draw(self, context):
        pie = self.layout.menu_pie()
        tree = context.space_data.edit_tree
        # Gated: `nodes.active` outlives a deselect-all, see
        # `store.active_if_selected`. Otherwise a stale active node would
        # keep showing its rule with nothing selected.
        active = store.active_if_selected(tree.nodes)

        entries = None
        if active is not None:
            entries = store.get_entries(tree.bl_idname, active.bl_idname)
        if entries is None:
            entries = store.get_entries(tree.bl_idname, nr.FALLBACK_KEY) \
                or [None] * nr.SLOT_COUNT

        for index, entry in enumerate(entries):
            if entry is None:
                pie.separator()
                continue
            if entry["node"] == "__search__":
                pie.operator("iops.node_pie_add_search",
                             text=entry.get("text") or "Add New Node",
                             icon=_icon_for(entry, 'VIEWZOOM'))
                continue
            if not hasattr(bpy.types, entry["node"]):
                store.warn_once(
                    f"slot {nr.SLOT_LABELS[index]} names unknown node "
                    f"{entry['node']}"
                )
                pie.separator()
                continue
            op = pie.operator("iops.node_spawn_connected",
                              text=_node_label(entry),
                              icon=_icon_for(entry))
            op.node_idname = entry["node"]
            op.entry_json = json.dumps(entry)


class IOPS_OT_Call_Pie_Node(bpy.types.Operator):
    """IOPS Node Pie"""

    bl_idname = "iops.call_pie_node"
    bl_label = "IOPS Node Pie"
    is_bindable = True

    @classmethod
    def poll(cls, context):
        return IOPS_MT_Pie_Node.poll(context)

    def execute(self, context):
        bpy.ops.wm.call_menu_pie(name="IOPS_MT_Pie_Node")
        return {'FINISHED'}
