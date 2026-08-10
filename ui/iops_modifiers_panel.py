"""iOps Modifiers micro-panel.

Single grid of modifier-type icons (ordered Generate/Deform/Utility) that
add / apply / remove / toggle modifiers across the selection, a tools row,
and a compact stack list for the active object. Draw-only: all logic lives
in operators/modifiers/. Per the perf rules, draw() only ever inspects the
active object's modifiers — never the selection or the scene.
"""

import bpy

from ..operators.modifiers.iops_mod_registry import (
    GROUP_ORDER,
    REGISTRY,
    enabled_grid_types,
    type_icon,
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


def draw_modifier_params(layout, md):
    """Draw every own param of md as a property-split column."""
    ids = modifier_param_ids(md)
    box = layout.box()
    if not ids:
        box.label(text="No editable parameters", icon="INFO")
        return
    col = box.column()
    col.use_property_split = True
    col.use_property_decorate = False
    for ident in ids:
        col.prop(md, ident)


class IOPS_PT_Modifiers_Panel(bpy.types.Panel):
    """Modifier grid + tools + active stack"""

    bl_label = "IOPS Modifiers"
    bl_idname = "IOPS_PT_Modifiers_Panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "iOps"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        prefs = context.preferences.addons["InteractionOps"].preferences
        active = context.active_object
        active_types = {md.type for md in active.modifiers} if active else set()

        enabled = enabled_grid_types(prefs)

        # --- icon grid: one flow, group order kept, no headers ---
        ordered = [t for group in GROUP_ORDER
                   for t in enabled
                   if t in REGISTRY and REGISTRY[t].group == group]
        ordered += [t for t in enabled if t not in REGISTRY]
        # Rows pref is the minimum height, columns pref the maximum
        # width: overflow grows extra rows instead of hiding buttons.
        # row_major=False makes `columns` mean a fixed number of rows,
        # filling top-to-bottom then left-to-right.
        rows = max(prefs.modifiers_grid_rows,
                   -(-len(ordered) // prefs.modifiers_grid_columns))
        grid = layout.grid_flow(row_major=False, columns=rows,
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

        # --- active object stack list ---
        if not prefs.modifiers_show_stack or active is None:
            return
        if not active.modifiers:
            return
        layout.separator(factor=0.5)
        box = layout.column(align=True)
        for i, md in enumerate(active.modifiers):
            row = box.row(align=True)
            row.prop(md, "show_expanded", text="",
                     icon="DOWNARROW_HLT" if md.show_expanded
                     else "RIGHTARROW",
                     emboss=False)
            row.label(text="", icon=type_icon(md.type))
            row.prop(md, "name", text="")
            row.prop(md, "show_viewport", text="", emboss=False)
            sub = row.row(align=True)
            sub.alert = md.show_render != md.show_viewport
            sub.prop(md, "show_render", text="", emboss=False)
            for action, icon in (
                ("MOVE_UP", "TRIA_UP"),
                ("MOVE_DOWN", "TRIA_DOWN"),
                ("APPLY", "CHECKMARK"),
                ("APPLY_UP_TO", "IMPORT"),
                ("REMOVE", "X"),
                ("SAVE_PRESET", "FILE_TICK"),
            ):
                op = row.operator("iops.mod_stack_action", text="",
                                  icon=icon, emboss=False)
                op.index = i
                op.action = action
            if md.show_expanded:
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
