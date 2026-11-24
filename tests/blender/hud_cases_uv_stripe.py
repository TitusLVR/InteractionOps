"""HUD cases of tests/blender/test_hud_more_options.py: UV Stripe (the reference)."""
from hud_case import HudCase

CASES = [
    HudCase(
        name="UV Stripe",
        module="operators.mesh_uv_stripe",
        cls="IOPS_OT_Mesh_UV_Stripe",
        always={"Straight Sides (Q)", "Ends (W)", "Balance (Ctrl + Wheel)", "More Options (Tab)"},
        tab_rows={"Mode (E)", "Orientation (A)", "Fit to Active (D)", "Split at Seams (S)", "Mark Seams (X)",
                  "Random Offset (Z)", "Offset Limit (Shift + Wheel)", "Offset Seed (R)", "Merge Doubles (F)"},
        also=[({"mode": "FIT"}, "Mode (E)"), ({"mark_seams": False}, "Mark Seams (X)"),
              ({"offset_seed": 2}, "Offset Seed (R)"), ({"orientation": "VERTICAL"}, "Orientation (A)"),
              ({"manual_cuts": '{"a": [1]}'}, "Manual Cuts"),
              ({"straight_lines": '{"a": [[0, 1]]}'}, "Straightened Lines"),
              ({"seed_faces": '{"a": [1]}'}, "Seed and Guide Faces")],
        keys=["Q", "W", "Ctrl + Wheel", "Ctrl + Shift + Wheel", "B", "Alt + Wheel", "G", "LMB on a side", "C", "LMB",
              "Alt + LMB", "V", "LMB on its boundary", "Alt + LMB on a face", "Shift + Alt + LMB", "E", "A", "D", "S",
              "X", "Z", "Shift + Wheel", "R", "F", "Tab", "Enter", "Space", "Esc", "RMB"],
    ),
]
