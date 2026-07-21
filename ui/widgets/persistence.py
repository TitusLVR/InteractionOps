"""Pure serialization for per-file widget UI state.

The runtime states dict in ui/widgets/state.py (name -> {"visible", "x",
"y", "anchor_area_ptr", "switches"}) round-trips through a JSON string
stored per-scene in `Scene.IOPS.widgets_ui_state`. This module is
bpy-free so the round-trip is plain pytest.

`anchor_area_ptr` is runtime-only (area pointers are meaningless across
sessions): dumps strips it, parse always returns it as 0.
"""
from __future__ import annotations
import json

DEFAULT_X = 80.0
DEFAULT_Y = 400.0


def dumps_states(states):
    """Serialize runtime states to the stored JSON string. Input is the
    addon's own runtime dict — trusted; only shape normalization here."""
    data = {}
    for name, st in states.items():
        if not isinstance(st, dict):
            continue
        data[str(name)] = {
            "visible": bool(st.get("visible")),
            "x": float(st.get("x", DEFAULT_X)),
            "y": float(st.get("y", DEFAULT_Y)),
            "switches": {str(k): bool(v)
                         for k, v in st.get("switches", {}).items()},
        }
    return json.dumps(data)


def parse_states(raw):
    """Parse a stored JSON string into fresh runtime states. Hostile
    input (hand-edited .blend data, other addons): any malformed layer
    degrades — bad document to {}, bad entry skipped, bad field to its
    default. Anchors always come back 0."""
    try:
        data = json.loads(raw or "")
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    states = {}
    for name, entry in data.items():
        if not isinstance(entry, dict):
            continue
        st = {"visible": bool(entry.get("visible", False)),
              "x": DEFAULT_X, "y": DEFAULT_Y,
              "anchor_area_ptr": 0, "switches": {}}
        try:
            st["x"] = float(entry.get("x", DEFAULT_X))
            st["y"] = float(entry.get("y", DEFAULT_Y))
        except (TypeError, ValueError):
            st["x"], st["y"] = DEFAULT_X, DEFAULT_Y
        sw = entry.get("switches", {})
        if isinstance(sw, dict):
            st["switches"] = {str(k): bool(v) for k, v in sw.items()}
        states[str(name)] = st
    return states
