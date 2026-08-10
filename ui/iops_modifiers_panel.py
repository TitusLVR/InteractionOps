"""iOps Modifiers micro-panel.

Grid of modifier-type icons (grouped Generate/Deform/Utility) that add /
apply / remove / toggle modifiers across the selection, a tools row, and
a compact stack list for the active object. Draw-only: all logic lives in
operators/modifiers/. Per the perf rules, draw() only ever inspects the
active object's modifiers — never the selection or the scene.
"""

import bpy

from ..operators.modifiers.iops_mod_registry import (
    GROUP_ORDER,
    REGISTRY,
    enabled_grid_types,
    type_icon,
)

_GROUP_LABELS = {
    "GENERATE": "Generate",
    "DEFORM": "Deform",
    "UTILITY": "Utility",
}


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
        columns = prefs.modifiers_grid_columns

        # --- icon grid, grouped ---
        col = layout.column(align=True)
        extras = [t for t in enabled if t not in REGISTRY]
        for group in GROUP_ORDER:
            group_types = [t for t in enabled
                           if t in REGISTRY and REGISTRY[t].group == group]
            if not group_types:
                continue
            col.label(text=_GROUP_LABELS[group])
            grid = col.grid_flow(columns=columns, even_columns=True,
                                 align=True)
            for mod_type in group_types:
                op = grid.operator("iops.mod_grid_click", text="",
                                   icon=type_icon(mod_type),
                                   depress=mod_type in active_types)
                op.mod_type = mod_type
            col.separator(factor=0.5)
        if extras:
            col.label(text="Other")
            grid = col.grid_flow(columns=columns, even_columns=True,
                                 align=True)
            for mod_type in extras:
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
