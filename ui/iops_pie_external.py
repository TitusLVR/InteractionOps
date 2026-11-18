import bpy
from bpy.types import Menu
from ..utils.functions import get_addon
from .iops_pie_menu import op_if_poll, op_polls


def _box(pie, title):
    box = pie.column().box().column(align=True)
    box.label(text=title)
    return box


def _draw_bmax(pie, context):
    addon = context.preferences.addons.get("BMAX_Connector")
    prefs = getattr(addon, "preferences", None)
    if prefs is None:
        pie.separator()
        return
    box = _box(pie, "BMax")
    file_format = getattr(prefs, "file_format", "FBX")
    if file_format == "USD":
        op_if_poll(box, "bmax.export_usd", icon="EXPORT", text="Send to Maya/3dsmax")
        op_if_poll(box, "bmax.import_usd", icon="IMPORT", text="Get from Maya/3dsmax")
    else:
        op_if_poll(box, "bmax.export", icon="EXPORT", text="Send to Maya/3dsmax")
        op_if_poll(box, "bmax.import", icon="IMPORT", text="Get from Maya/3dsmax")
    row = box.row(align=True)
    for prop, icon in (("export_reset_location", "EVENT_L"),
                       ("export_reset_rotation", "EVENT_R"),
                       ("export_reset_scale", "EVENT_S")):
        if hasattr(prefs, prop):
            row.prop(prefs, prop, icon=icon, text="  ")


def _draw_bmoi(pie, context):
    if not (op_polls("bmoi3d.export") or op_polls("bmoi3d.import")):
        pie.separator()
        return
    box = _box(pie, "BMoI")
    op_if_poll(box, "bmoi3d.export", icon="EXPORT", text="Send to MoI3D")
    op_if_poll(box, "bmoi3d.import", icon="IMPORT", text="Get from MoI3D")


def _draw_b2ruvl(pie, context):
    addon = context.preferences.addons.get("B2RUVL")
    prefs = getattr(addon, "preferences", None)
    panel_props = getattr(context.window_manager, "B2RUVL_PanelProperties", None)
    if prefs is None or panel_props is None:
        pie.separator()
        return
    uvl = getattr(prefs, "uvlayout_enable", False)
    ruv = getattr(prefs, "rizomuv_enable", False)
    uvl_path = getattr(prefs, "uvlayout_app_path", "")
    ruv_path = getattr(prefs, "rizomuv_app_path", "")

    box = _box(pie, "B2RUVL")
    box.prop(panel_props, "uvMap")
    col_uvl = box.column(align=True)
    col_uvl.enabled = bool(uvl) and len(uvl_path) != 0
    col_uvl.operator("b2ruvl.send_to_uvlayout")
    col_ruv = box.column(align=True)
    col_ruv.enabled = bool(ruv) and len(ruv_path) != 0
    col_ruv.operator("b2ruvl.send_to_rizomuv")
    col_ruv.operator("b2ruvl.get_from_rizomuv")


_FORGOTTEN_TOOLS_OPS = (
    "mesh.connect_spread",
    "mesh.grid_fill_all",
    "mesh.dice_faces",
    "mesh.hinge",
    "mesh.forgotten_separate_duplicate",
)


def _draw_forgotten_tools(pie, context):
    visible = [idname for idname in _FORGOTTEN_TOOLS_OPS if op_polls(idname)]
    selection_sets = context.mode == "EDIT_MESH"
    if not visible and not selection_sets:
        pie.separator()
        return
    box = _box(pie, "ForgottenTools")
    for idname in visible:
        op_if_poll(box, idname)
    if selection_sets:
        box.operator(
            "wm.call_panel", text="Selection Sets", icon="SELECT_SET"
        ).name = "MESH_PT_selection_sets_panel_frgttn"


def _draw_optiloops(pie, context):
    if not op_polls("mesh.optiloops"):
        pie.separator()
        return
    box = _box(pie, "Optiloops")
    op_if_poll(box, "mesh.optiloops")


class IOPS_MT_Pie_External(Menu):
    bl_label = "IOPS External"

    def draw(self, context):
        pie = self.layout.menu_pie()
        bmax = get_addon("BMAX Connector")[0]
        bmoi = get_addon("BMOI Connector")[0]
        b2ruvl = context.preferences.addons.get("B2RUVL") is not None
        forgotten_tools = get_addon("Forgotten Tools")[0]
        optiloops = get_addon("Optiloops")[0]

        if not (bmax or bmoi or b2ruvl or forgotten_tools or optiloops):
            pie.label(text="No external addons installed")
            return

        # Blender pie fill order: LEFT, RIGHT, BOTTOM, TOP,
        # TOP_LEFT, TOP_RIGHT, BOTTOM_LEFT, BOTTOM_RIGHT.
        slots = (
            (bmax, _draw_bmax),
            (bmoi, _draw_bmoi),
            (b2ruvl, _draw_b2ruvl),
            (forgotten_tools, _draw_forgotten_tools),
            (False, None),
            (optiloops, _draw_optiloops),
            (False, None),
            (False, None),
        )
        for present, draw in slots:
            if present:
                draw(pie, context)
            else:
                pie.separator()


class IOPS_OT_Call_Pie_External(bpy.types.Operator):
    """IOPS External Pie: third-party addon tools"""

    bl_idname = "iops.call_pie_external"
    is_bindable = True
    bl_label = "IOPS Pie External"

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D"

    def execute(self, context):
        bpy.ops.wm.call_menu_pie(name="IOPS_MT_Pie_External")
        return {"FINISHED"}
