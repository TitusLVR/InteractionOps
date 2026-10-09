import bpy
from bpy.types import Menu

# (label, icon, snap combo idx) in Blender pie fill order: W, E, S, N, NW, NE, SW, SE
SNAP_COMBOS_PIE_SLOTS = (
    ("C - Cursor", "PIVOT_CURSOR", 3),
    ("E - Median", "PIVOT_MEDIAN", 5),
    ("A - Active", "PIVOT_ACTIVE", 1),
    ("H - Individual", "PIVOT_INDIVIDUAL", 8),
    ("G - Grid", "SNAP_GRID", 7),
    ("B - Closest", "PARTICLES", 2),
    ("F - Face Normal", "SNAP_NORMAL", 6),
    ("D - Center", "PIVOT_BOUNDBOX", 4),
)


class IOPS_MT_Pie_Snap_Combos(Menu):
    bl_label = "IOPS Snap Combos"

    def draw(self, context):
        pie = self.layout.menu_pie()
        for label, icon, idx in SNAP_COMBOS_PIE_SLOTS:
            pie.operator("iops.set_snap_combo", text=label, icon=icon).idx = idx


class IOPS_OT_Call_Pie_Snap_Combos(bpy.types.Operator):
    """IOPS Snap Combos Pie"""

    bl_idname = "iops.call_pie_snap_combos"
    is_bindable = True
    bl_label = "IOPS Pie Snap Combos"

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D"

    def execute(self, context):
        bpy.ops.wm.call_menu_pie(name="IOPS_MT_Pie_Snap_Combos")
        return {"FINISHED"}
