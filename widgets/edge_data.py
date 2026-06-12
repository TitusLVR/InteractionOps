"""Edge Data widget — bevel weight, crease, sharp, seam, freestyle, clear.

First concrete widget for the GPU widget framework (ui/widgets), per
docs/superpowers/specs/2026-06-11-gpu-widget-system-design.md.

The bmesh value adapters live in adapters.py (shared with JSON-composed
widgets from the prefs Widgets tab); they are re-exported here so external
callers keep their import path.
"""
from ..ui.widgets import (Widget, Section, Slider, PresetRow, FlipBox,
                          ActionButton, Row)
from .adapters import (  # noqa: F401 — re-exported public adapter API
    BEVEL_LAYER, CREASE_LAYER, FREESTYLE_LAYER,
    has_selected_edges,
    get_bevel, set_bevel, snapshot_bevel, restore_bevel,
    get_crease, set_crease, snapshot_crease, restore_crease,
    get_sharp, set_sharp, get_seam, set_seam,
    get_freestyle, set_freestyle,
)

CLEAR_SCRIPT = "B:\\scripts\\iops_exec\\CLEAN_Edge_Data_Clear.py"


class EdgeDataWidget(Widget):
    """Persistent Edge Data panel: bevel weight + crease sliders with
    presets, sharp/seam/freestyle flip boxes and a Clear action."""

    name = "edge_data"
    title = "Edge Data"
    space = "VIEW_3D"

    def build(self):
        return [
            Section("Bevel Weight"),
            Slider(get=get_bevel, set=set_bevel, snap=0.125,
                   snapshot=snapshot_bevel, restore=restore_bevel),
            PresetRow([0, 0.25, 0.5, 1.0], set=set_bevel,
                      enabled_get=has_selected_edges),
            Section("Crease"),
            Slider(get=get_crease, set=set_crease, snap=0.125,
                   snapshot=snapshot_crease, restore=restore_crease),
            PresetRow([0, 0.5, 0.9, 1.0], set=set_crease,
                      enabled_get=has_selected_edges),
            Section("Flags"),
            Row([FlipBox("Sharp", get=get_sharp, set=set_sharp),
                 FlipBox("Seam", get=get_seam, set=set_seam),
                 FlipBox("Freestyle", get=get_freestyle, set=set_freestyle)]),
            ActionButton("Clear", op="iops.executor",
                         kwargs={"script": CLEAR_SCRIPT},
                         role="error",
                         enabled_get=has_selected_edges),
        ]

    def poll(self, context):
        return context.mode == "EDIT_MESH"
