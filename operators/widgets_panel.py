"""Scan-to-popup for JSON widgets — mirrors the script executor.

`iops.scripts_call_widgets_panel` scans the configured widgets folder,
registers every valid definition (idempotent), stores (name, title) on
the scene, and pops a list panel. Each row toggles that widget's GPU
panel via iops.widget_toggle.

It deliberately does NOT touch keymaps or the prefs-tab list: this
operator is bindable, and mutating keymaps (sync_toggle_kmis ->
keyconfigs.update()) from inside a keymap-invoked operator dismisses the
call_panel popup before it can show (it works only when run from a UI
button, where no keymap event is in flight). Toggle hotkeys + prefs rows
are synced at addon load and on Widgets-tab edits instead.
"""
import os

import bpy

from ..widgets import composed


class IOPS_OT_Call_Widgets_Panel(bpy.types.Operator):
    """Scan the widgets folder and open a list of all widgets"""

    bl_idname = "iops.scripts_call_widgets_panel"
    is_bindable = True
    bl_label = "IOPS Widgets Panel"

    def execute(self, context):
        iops = getattr(context.scene, "IOPS", None)
        if iops is None:
            self.report({"ERROR"}, "IOPS scene data not available")
            return {"CANCELLED"}
        from ..ui.widgets import get_widget
        folder = composed.widgets_folder()
        found = []
        if os.path.isdir(folder):
            for fn in composed.list_widget_files():
                wdef, _err = composed.load_def(os.path.join(folder, fn))
                if wdef is None:
                    continue
                # Only register widgets that aren't already live — never
                # re-register an existing one here. Re-registration
                # rebuilds the Widget with a fresh panel at the default
                # corner, which would wipe the on-screen position of every
                # already-placed widget each time the popup opens.
                if get_widget(wdef["name"]) is None:
                    composed.register_composed(wdef)
                found.append((wdef["name"], wdef.get("title") or wdef["name"]))
        iops.widget_list.clear()
        for name, title in sorted(found, key=lambda t: t[1].lower()):
            item = iops.widget_list.add()
            item.name = name
            item.title = title
        bpy.ops.wm.call_panel(name="IOPS_PT_WidgetList")
        return {"FINISHED"}


class IOPS_PT_WidgetList(bpy.types.Panel):
    bl_idname = "IOPS_PT_WidgetList"
    bl_label = "Widgets"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"

    def draw(self, context):
        layout = self.layout
        iops = getattr(context.scene, "IOPS", None)
        items = list(iops.widget_list) if iops is not None else []
        if not items:
            layout.label(text="No widgets in folder")
            return
        col = layout.column(align=True)
        letter = ""
        for item in items:
            head = (item.title or item.name)[:1].upper()
            if head != letter:
                col.label(text=head)
                letter = head
            op = col.operator("iops.widget_toggle", text=item.title,
                              icon="MESH_PLANE")
            op.name = item.name
            op.use_cursor = False   # re-open at the widget's saved spot


classes = (IOPS_OT_Call_Widgets_Panel, IOPS_PT_WidgetList)
