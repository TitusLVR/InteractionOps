"""iOps Modifiers micro-panel.

Single grid of modifier-type icons — the user's list from addon prefs,
order verbatim — that add / apply / remove / toggle modifiers across the
selection, a tools row, and a compact stack list for the active object. Draw-only: all logic lives
in operators/modifiers/. Per the perf rules, draw() only ever inspects the
active object's modifiers — never the selection or the scene.
"""

import bpy

from ..operators.modifiers.iops_mod_defaults import draw_props
from ..operators.modifiers.iops_mod_registry import (
    enabled_grid_types,
    type_icon,
)
from ..operators.modifiers.iops_mod_stack import (
    NO_EDITMODE_SUPPORT,
    expanded_params,
    modifier_is_disabled,
    params_key,
)

# --- universal modifier parameter reader ------------------------------
# RNA introspection: every editable prop the modifier subclass adds on
# top of the base Modifier type (name/type/show_* etc. excluded).
# Cached per modifier type; draw() only reads the cache.

_BASE_MOD_PROPS = None   # props of bpy.types.Modifier itself
_PARAMS_CACHE = {}       # md.type -> tuple of prop identifiers


def modifier_param_ids(md):
    """Identifiers of md's own editable params, in RNA order."""
    global _BASE_MOD_PROPS
    ids = _PARAMS_CACHE.get(md.type)
    if ids is not None:
        return ids
    if _BASE_MOD_PROPS is None:
        _BASE_MOD_PROPS = {
            p.identifier for p in bpy.types.Modifier.bl_rna.properties}
    ids = []
    for p in md.bl_rna.properties:
        if p.identifier in _BASE_MOD_PROPS or p.is_hidden or p.is_readonly:
            continue
        if p.type == "COLLECTION":
            continue  # no generic widget for collections
        if p.type == "POINTER":
            # only ID datablock pointers get a usable search field
            target = getattr(bpy.types, p.fixed_type.identifier, None)
            if target is None or not issubclass(target, bpy.types.ID):
                continue
        ids.append(p.identifier)
    ids = tuple(ids)
    _PARAMS_CACHE[md.type] = ids
    return ids


def _draw_nodes_items(col, md, inputs, items):
    """One level of a geometry-nodes interface tree: input sockets as
    value props, nested panels as collapsible sub-panels (recursive)."""
    for item in items:
        if item.item_type == "PANEL":
            header, body = col.panel(
                f"iops_gn_{md.persistent_uid}_{item.persistent_uid}",
                default_closed=item.default_closed)
            header.label(text=item.name)
            if body is not None:
                _draw_nodes_items(body, md, inputs, item.interface_items)
        elif item.in_out == "INPUT":
            if inputs is not None:
                sock = getattr(inputs, item.identifier, None)
                # geometry / field-only sockets carry no value prop
                if sock is not None and hasattr(sock, "value"):
                    col.prop(sock, "value", text=item.name)
            elif item.identifier in md:
                col.prop(md, f'["{item.identifier}"]', text=item.name)


def draw_nodes_params(col, md):
    """Geometry Nodes: the node-group picker plus the group's input
    sockets, like the native Properties panel — not the modifier's raw
    RNA. Blender 5.x keeps per-socket value groups on
    md.properties.inputs; older builds keep ID custom props on md."""
    col.prop(md, "node_group")
    group = md.node_group
    if group is None:
        return
    inputs = getattr(getattr(md, "properties", None), "inputs", None)
    root = [i for i in group.interface.items_tree
            if i.parent is not None and i.parent.parent is None]
    _draw_nodes_items(col, md, inputs, root)


def draw_modifier_params(layout, md):
    """Draw every own param of md as a property-split column."""
    box = layout.box()
    col = box.column()
    col.use_property_split = True
    col.use_property_decorate = False
    if md.type == "NODES":
        draw_nodes_params(col, md)
        return
    ids = modifier_param_ids(md)
    if not ids:
        box.label(text="No editable parameters", icon="INFO")
        return
    draw_props(col, md, ids)


class IOPS_PT_Modifiers_Panel(bpy.types.Panel):
    """Modifier grid + tools + active stack"""

    bl_label = "IOPS Modifiers"
    bl_idname = "IOPS_PT_Modifiers_Panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "iOps"
    bl_options = {"DEFAULT_CLOSED"}
    # popup width (wm.call_panel); the docked N-panel ignores this
    bl_ui_units_x = 16

    def draw(self, context):
        layout = self.layout
        prefs = context.preferences.addons["InteractionOps"].preferences
        active = context.active_object
        active_types = {md.type for md in active.modifiers} if active else set()

        # --- icon grid: the user's list from prefs, order verbatim ---
        ordered = enabled_grid_types(prefs)
        grid = layout.grid_flow(row_major=True,
                                columns=prefs.modifiers_grid_columns,
                                even_columns=True, align=True)
        for mod_type in ordered:
            op = grid.operator("iops.mod_grid_click", text="",
                               icon=type_icon(mod_type),
                               depress=mod_type in active_types)
            op.mod_type = mod_type

        # --- tools ---
        layout.separator(factor=0.5)
        tools = layout.column(align=True)
        row = tools.row(align=True)
        row.operator("iops.mod_sort_stack", text="Sort", icon="SORTSIZE")
        row.operator("iops.mod_cleanup", text="Cleanup", icon="BRUSH_DATA")
        row.operator("iops.mod_sync_vis", text="Sync Vis",
                     icon="RESTRICT_RENDER_OFF")
        row = tools.row(align=True)
        row.operator("iops.mod_cursor_target", text="Cursor Target",
                     icon="PIVOT_CURSOR")
        row.operator("iops.mod_active_target", text="Active Target",
                     icon="PIVOT_ACTIVE")
        row = tools.row(align=True)
        row.operator("iops.mod_select_target_users", text="Users",
                     icon="RESTRICT_SELECT_OFF")
        row.operator("iops.mod_safe_apply_transform", text="Safe Apply",
                     icon="CHECKMARK")
        row = tools.row(align=True)
        row.operator("iops.mod_adaptive_decimate", text="Adaptive Decimate",
                     icon="MOD_DECIM")
        row.operator("iops.mod_collapse_stack", text="Apply All",
                     icon="IMPORT")

        # --- active object stack list ---
        if not prefs.modifiers_show_stack or active is None:
            return
        if not active.modifiers:
            return
        layout.separator(factor=0.5)
        box = layout.column(align=True)
        for i, md in enumerate(active.modifiers):
            row = box.row(align=True)
            expanded = params_key(active, md) in expanded_params
            op = row.operator("iops.mod_stack_action", text="",
                              icon="DOWNARROW_HLT" if expanded
                              else "RIGHTARROW",
                              emboss=False)
            op.index = i
            op.action = "TOGGLE_PARAMS"
            icon_row = row.row(align=True)
            icon_row.alert = modifier_is_disabled(md)
            op = icon_row.operator("iops.mod_stack_action", text="",
                                   icon=type_icon(md.type),
                                   emboss=md.is_active, depress=md.is_active)
            op.index = i
            op.action = "SET_ACTIVE"
            row.prop(md, "name", text="")
            vis = row.row(align=True)
            vis.alert = md.show_render != md.show_viewport
            if md.type not in NO_EDITMODE_SUPPORT:
                sub = vis.row(align=True)
                sub.active = md.show_viewport
                op = sub.operator("iops.mod_stack_action", text="",
                                  icon="EDITMODE_HLT",
                                  depress=md.show_in_editmode)
                op.index = i
                op.action = "TOGGLE_EDITMODE"
            op = vis.operator("iops.mod_stack_action", text="",
                              icon="RESTRICT_VIEW_OFF" if md.show_viewport
                              else "RESTRICT_VIEW_ON",
                              depress=md.show_viewport)
            op.index = i
            op.action = "TOGGLE_VIS"
            op = vis.operator("iops.mod_stack_action", text="",
                              icon="RESTRICT_RENDER_OFF" if md.show_render
                              else "RESTRICT_RENDER_ON",
                              depress=md.show_render)
            op.index = i
            op.action = "TOGGLE_RENDER"
            for action, icon in (
                ("MOVE_UP", "TRIA_UP"),
                ("MOVE_DOWN", "TRIA_DOWN"),
                ("COPY_TO_SELECTED", "COPYDOWN"),
                ("APPLY", "IMPORT"),
                ("REMOVE", "X"),
            ):
                op = row.operator("iops.mod_stack_action", text="",
                                  icon=icon, emboss=False)
                op.index = i
                op.action = action
            if expanded:
                draw_modifier_params(box, md)


class IOPS_OT_Call_Modifiers_Panel(bpy.types.Operator):
    """Call IOPS Modifiers panel"""

    bl_idname = "iops.call_panel_modifiers"
    is_bindable = True
    bl_label = "IOPS Modifiers panel"

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D"

    def execute(self, context):
        bpy.ops.wm.call_panel(name="IOPS_PT_Modifiers_Panel", keep_open=True)
        return {"FINISHED"}
