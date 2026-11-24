"""HUD cases of tests/blender/test_hud_more_options.py: UV Stripe (the reference)."""
from hud_case import HudCase

CASES = [
    HudCase(
        name="UV Stripe",
        module="operators.mesh_uv_stripe",
        cls="IOPS_OT_Mesh_UV_Stripe",
        always={"Straight Sides (E)", "Ends (A)", "Stretch Limit (Wheel)", "More Options (Tab)"},
        tab_rows={"Balance (B)", "Mode (Q)", "Orientation (W)", "Fit to Active (D)", "Split at Seams (S)",
                  "Mark Seams (X)", "Random Offset (Z)", "Offset Limit (Shift + Wheel)", "Offset Seed (R)",
                  "Merge Doubles (F)"},
        also=[({"mode": "FIT"}, "Mode (Q)"), ({"mark_seams": False}, "Mark Seams (X)"),
              ({"offset_seed": 2}, "Offset Seed (R)"), ({"balance": "LEAST_STRETCH"}, "Balance (B)")],
        keys=["E", "A", "Wheel", "LMB on a side", "G", "V", "B", "Q", "W", "D", "C", "S", "X", "Z", "Shift + Wheel",
              "R", "F", "Tab", "Enter", "Space", "Esc", "RMB"],
    ),
]
