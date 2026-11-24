"""HUD cases of tests/blender/test_hud_more_options.py, batch c: Radial Array, Vertex Paint, Falloff Move / Rotate /
Scale (one case per class: the HUD is built by the shared mixin, the amount row differs)."""
import math

import numpy as np
from types import SimpleNamespace

from hud_case import HudCase


def _vertex_paint_state():
    from InteractionOps.utils.vertex_paint_core import StrokeHistory
    return {
        "ba": SimpleNamespace(size=50, strength=0.5, preset="SMOOTH", color=(1.0, 0.0, 0.0)),
        "_muted_mods": [],
        "_hist": StrokeHistory(limit=8),
    }


def _falloff_state():
    return {
        "_ftype": "RADIAL", "_shape": "SMOOTH", "_r": 1.0, "_screen_px": 100, "_coplanar_angle": math.radians(20),
        "_coplanar_ok": True, "_connected": False, "_invert": False, "_preview": False, "_basis_mode": "LOCAL", "_pivot_moved": False,
        "_axis": None, "input_str": "", "_current_amount": None, "_S": np.zeros(3), "_E": np.array([0.0, 0.0, 1.0]),
    }


def _falloff_case(name, cls, amount):
    return HudCase(
        name=name,
        module="operators.falloff.ops",
        cls=cls,
        always={"Falloff (L / R / S / C)", "Shape (F)", "Radius (Shift + Wheel)", amount},
        state=_falloff_state(),
        also=[({"_coplanar_ok": False}, "Coplanar (C)")],
        keys=["L", "R", "S", "C", "F", "Shift + Wheel", "A", "E", "I", "V", "LMB", "X", "Y", "Z", "N", "Backspace",
              "0 - 9", ".", "-", "Shift", "Ctrl", "Enter", "Space", "Esc", "RMB"],
    )


CASES = [
    HudCase(
        name="Radial Array",
        module="operators.object_radial_array",
        cls="IOPS_OT_Object_Radial_Array",
        always={"Count (Ctrl + Wheel)", "Pivot (Q)", "Arc (W)", "Axis (X / Y / Z)", "More Options (Tab)"},
        tab_rows={"Alignment (R)", "Source (T)", "Clone Type (D)", "Start Point (S)", "End Point (F)",
                  "Rotation Step (1 to 5)", "Local Rotation (Arrows)"},
        also=[({"align_mode": "ROTATE"}, "Alignment (R)"), ({"source_mode": "POOL"}, "Source (T)"),
              ({"clone_mode": "INSTANCE"}, "Clone Type (D)"), ({"skip_first": True}, "Start Point (S)"),
              ({"arc_mode": "180°"}, "End Point (F)"),
              ({"local_rot": [0.5, 0.0, 0.0]}, "Rotation Step (1 to 5)"),
              ({"local_rot": [0.5, 0.0, 0.0]}, "Local Rotation (Arrows)")],
        state={
            "count": 6, "pivot_mode": "ACTIVE_CURSOR", "arc_mode": "360°", "axis_mode": "CZ", "align_mode": "ALIGN",
            "source_mode": "GROUP", "clone_mode": "DUPLICATE", "skip_first": False, "end_inclusive": True,
            "local_rot_step": math.radians(90.0), "local_rot": [0.0, 0.0, 0.0], "axis_offset": 0.0,
            "axis_offset_mode": False, "skip_mode": "SHOW", "locked_slots": set(), "match_active": False,
        },
        keys=["+", "-", "Ctrl + Wheel", "Ctrl + Shift + Wheel", "Q", "W", "I", "LMB on ring + drag",
              "LMB on center + drag", "X", "Y", "Z", "V", "E", "C + LMB", "R", "T", "G", "D", "S", "F", "A", "LMB",
              "N", "M", "1", "2", "3", "4", "5", "Left", "Right", "Up Arrow", "Down Arrow", "B", "Tab", "Ctrl + Z",
              "Ctrl + Shift + Z", "Enter", "Space", "Esc", "RMB"],
    ),
    HudCase(
        name="Vertex Paint",
        module="operators.mesh_vertex_paint",
        cls="IOPS_OT_MeshVertexPaint",
        always={"Tool (T / E)", "Element (1 / 2 / 3)", "Color (C)", "Radius (Ctrl + Wheel)",
                "Strength (Shift + Wheel)", "More Options (Tab)"},
        tab_rows={"Channel (A)", "Alpha (Shift + 0 / 1)", "Falloff (Alt + Wheel)", "Strokes"},
        also=[],   # Channel and Alpha read scene settings (iops_vp_channel / iops_vp_alpha), not instance state
        state=_vertex_paint_state(),
        keys=["F", "Shift + F", "Ctrl + Wheel", "Shift + Wheel", "[", "]", "Alt + Wheel", "N", "M", "P", "V",
              "1", "2", "3", "R", "G", "B", "Shift + R", "Shift + G", "Shift + B", "K", "W", "C", "A", "Shift + 0",
              "Shift + 1", "LMB", "Ctrl + LMB", "E", "T", "Ctrl + Z", "Ctrl + Shift + Z", "Tab", "Enter", "Space",
              "RMB", "Esc"],
    ),
    _falloff_case("Falloff Move", "IOPS_OT_mesh_falloff_move", "Offset"),
    _falloff_case("Falloff Rotate", "IOPS_OT_mesh_falloff_rotate", "Angle"),
    _falloff_case("Falloff Scale", "IOPS_OT_mesh_falloff_scale", "Scale"),
]
