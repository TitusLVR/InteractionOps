"""Purge per-.blend widget data (Scene.IOPS.widget_data blocks).

One operator, two modes: `widget` empty purges EVERY widget's data in
the current scene; non-empty purges that widget's block only. Runs with
a confirm dialog (destructive, per-scene). Widget authors can expose a
per-widget purge as a BUTTON row:
    {"type": "BUTTON", "label": "Reset", "op": "iops.purge_widget_data",
     "op_kwargs": {"widget": "my_widget"}, "role": "error"}
"""
import bpy
from bpy.props import StringProperty

from ..widgets import scene_store


class IOPS_OT_purge_widget_data(bpy.types.Operator):
    """Remove widget data stored in the current scene"""

    bl_idname = "iops.purge_widget_data"
    bl_label = "Purge Widgets Data"
    bl_options = {"REGISTER", "UNDO"}

    widget: StringProperty(
        name="Widget",
        default="",
        description="Widget whose data to purge; empty purges ALL"
                    " widget data in the scene",
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        removed = scene_store.purge(context, self.widget or None)
        target = "'%s'" % self.widget if self.widget else "all widgets"
        self.report({"INFO"},
                    "IOPS: purged %d data block(s) (%s)" % (removed, target))
        # Data-bound controls cache (value, mixed) pairs — repaint.
        from ..ui.widgets import state
        state.mark_all_dirty()
        state.tag_redraw_all()
        return {"FINISHED"}


classes = (IOPS_OT_purge_widget_data,)
