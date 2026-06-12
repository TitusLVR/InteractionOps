"""JSON-composed widgets — the runtime behind the prefs "Widgets" tab.

A composed widget is a JSON definition built from the known block palette
(Section / Slider / Presets / FlipBox / Button) with value rows bound to
the adapter registry (adapters.ADAPTERS). One file per widget in
`bpy.utils.script_path_user()/presets/IOPS/widgets/<name>.json`:

    {
      "version": 1,
      "name": "edge_data_custom",
      "title": "Edge Data",
      "space": "VIEW_3D",
      "rows": [
        {"type": "SECTION", "label": "Bevel Weight"},
        {"type": "SLIDER",  "target": "BEVEL", "snap": 0.125},
        {"type": "PRESETS", "target": "BEVEL", "values": [0, 0.25, 0.5, 1.0]},
        {"type": "FLIPBOX", "target": "SHARP", "label": "Sharp"},
        {"type": "BUTTON",  "label": "Clear", "op": "iops.executor",
         "op_kwargs": {"script": "..."}, "role": "error"}
      ]
    }

Adjacent FLIPBOX rows merge into one panel row (matches the edge_data
look without exposing column configuration).

`validate_def()`, `sanitize_name()` and the row-merging logic are
bpy/bmesh-free and pytest-covered; everything touching bpy/bmesh defers
its import to call time.
"""
import json
import os

ROW_TYPES = ("SECTION", "SLIDER", "PRESETS", "FLIPBOX", "BUTTON")
FLOAT_TARGETS = ("BEVEL", "CREASE")
BOOL_TARGETS = ("SHARP", "SEAM", "FREESTYLE")
SCHEMA_VERSION = 1
_EXT = ".json"

# Composer-editable mirror of widgets/edge_data.py — the template behind
# "Duplicate" on the built-in entry and its JSON export.
EDGE_DATA_DEF = {
    "version": SCHEMA_VERSION,
    "name": "edge_data",
    "title": "Edge Data",
    "space": "VIEW_3D",
    "rows": [
        {"type": "SECTION", "label": "Bevel Weight"},
        {"type": "SLIDER", "target": "BEVEL", "snap": 0.125},
        {"type": "PRESETS", "target": "BEVEL", "values": [0, 0.25, 0.5, 1.0]},
        {"type": "SECTION", "label": "Crease"},
        {"type": "SLIDER", "target": "CREASE", "snap": 0.125},
        {"type": "PRESETS", "target": "CREASE", "values": [0, 0.5, 0.9, 1.0]},
        {"type": "SECTION", "label": "Flags"},
        {"type": "FLIPBOX", "target": "SHARP", "label": "Sharp"},
        {"type": "FLIPBOX", "target": "SEAM", "label": "Seam"},
        {"type": "FLIPBOX", "target": "FREESTYLE", "label": "Freestyle"},
        {"type": "BUTTON", "label": "Clear", "op": "iops.executor",
         "op_kwargs": {"script": "B:\\scripts\\iops_exec\\CLEAN_Edge_Data_Clear.py"},
         "role": "error"},
    ],
}


# ----------------------------------------------------------------------
# Pure helpers (pytest-covered, no bpy)
# ----------------------------------------------------------------------
def sanitize_name(name):
    """Registry/file-safe widget name: trimmed, lowercase-ish free-form
    but with illegal filename chars replaced (same policy as themes)."""
    clean = str(name).strip()
    for ch in '<>:"/\\|?*':
        clean = clean.replace(ch, "_")
    return clean


def parse_values(text):
    """Parse a comma-separated preset string ("0, 0.25, 0.5") into floats
    clamped to [0, 1]; bad tokens are skipped. Pure — pytest-covered."""
    vals = []
    for tok in str(text).split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            vals.append(max(0.0, min(1.0, float(tok))))
        except ValueError:
            pass
    return vals


def unique_name(base, taken):
    """`base`, or `base_2`, `base_3`, ... — first not in `taken`."""
    if base not in taken:
        return base
    i = 2
    while f"{base}_{i}" in taken:
        i += 1
    return f"{base}_{i}"


def validate_def(data):
    """Validate + normalize a widget definition dict.

    Returns (clean_def, errors). `clean_def` is None when the definition
    is unusable (bad name / not a dict); row-level problems drop the row
    and report, keeping the rest of the widget alive.
    """
    errors = []
    if not isinstance(data, dict):
        return None, ["definition is not a JSON object"]
    name = sanitize_name(data.get("name", ""))
    if not name:
        return None, ["missing widget name"]
    clean = {
        "version": SCHEMA_VERSION,
        "name": name,
        "title": str(data.get("title", "")) or name,
        "space": "VIEW_3D",   # IMAGE_EDITOR widgets come later (spec)
        "rows": [],
    }
    rows = data.get("rows", [])
    if not isinstance(rows, list):
        return clean, ["rows is not a list"]
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"row {i}: not an object — dropped")
            continue
        rtype = str(row.get("type", "")).upper()
        if rtype not in ROW_TYPES:
            errors.append(f"row {i}: unknown type '{rtype}' — dropped")
            continue
        out: dict = {"type": rtype}
        if rtype == "SECTION":
            out["label"] = str(row.get("label", ""))
        elif rtype == "SLIDER":
            target = str(row.get("target", "")).upper()
            if target not in FLOAT_TARGETS:
                errors.append(f"row {i}: slider target '{target}' invalid"
                              " — dropped")
                continue
            out["target"] = target
            try:
                out["snap"] = max(0.0, float(row.get("snap", 0.125)))
            except (TypeError, ValueError):
                out["snap"] = 0.125
        elif rtype == "PRESETS":
            target = str(row.get("target", "")).upper()
            if target not in FLOAT_TARGETS:
                errors.append(f"row {i}: presets target '{target}' invalid"
                              " — dropped")
                continue
            out["target"] = target
            values = row.get("values", [])
            vals = []
            if isinstance(values, list):
                for v in values:
                    try:
                        vals.append(max(0.0, min(1.0, float(v))))
                    except (TypeError, ValueError):
                        pass
            if not vals:
                errors.append(f"row {i}: presets without values — dropped")
                continue
            out["values"] = vals
        elif rtype == "FLIPBOX":
            target = str(row.get("target", "")).upper()
            if target not in BOOL_TARGETS:
                errors.append(f"row {i}: flipbox target '{target}' invalid"
                              " — dropped")
                continue
            out["target"] = target
            out["label"] = str(row.get("label", "")) or target.title()
        elif rtype == "BUTTON":
            op = str(row.get("op", "")).strip()
            if "." not in op:
                errors.append(f"row {i}: button op '{op}' is not an"
                              " operator idname — dropped")
                continue
            out["op"] = op
            out["label"] = str(row.get("label", "")) or op
            kwargs = row.get("op_kwargs", {})
            out["op_kwargs"] = kwargs if isinstance(kwargs, dict) else {}
            role = str(row.get("role", "default"))
            out["role"] = role if role in ("default", "error") else "default"
        clean["rows"].append(out)
    return clean, errors


def merge_flipbox_runs(rows):
    """Group consecutive FLIPBOX row defs: returns a list where each item
    is either a single row def or a list of >=2 flipbox defs (one panel
    row). Pure — pytest-covered."""
    merged = []
    run = []
    for row in rows:
        if row.get("type") == "FLIPBOX":
            run.append(row)
            continue
        if run:
            merged.append(run if len(run) > 1 else run[0])
            run = []
        merged.append(row)
    if run:
        merged.append(run if len(run) > 1 else run[0])
    return merged


# ----------------------------------------------------------------------
# Control building (bpy/bmesh deferred)
# ----------------------------------------------------------------------
def build_controls(row_defs):
    """Materialize a validated `rows` list into framework controls."""
    from ..ui.widgets import (Section, Slider, PresetRow, FlipBox,
                              ActionButton, Row)
    from .adapters import ADAPTERS, has_selected_edges

    def one(row):
        rtype = row["type"]
        if rtype == "SECTION":
            return Section(row.get("label", ""))
        if rtype == "SLIDER":
            a = ADAPTERS[row["target"]]
            return Slider(get=a["get"], set=a["set"],
                          snap=row.get("snap", 0.125),
                          snapshot=a.get("snapshot"),
                          restore=a.get("restore"))
        if rtype == "PRESETS":
            a = ADAPTERS[row["target"]]
            return PresetRow(row["values"], set=a["set"],
                             enabled_get=has_selected_edges)
        if rtype == "FLIPBOX":
            a = ADAPTERS[row["target"]]
            return FlipBox(row["label"], get=a["get"], set=a["set"])
        if rtype == "BUTTON":
            return ActionButton(row["label"], op=row["op"],
                                kwargs=row.get("op_kwargs") or {},
                                role=row.get("role", "default"),
                                enabled_get=has_selected_edges)
        return None

    controls = []
    for item in merge_flipbox_runs(row_defs):
        if isinstance(item, list):
            controls.append(Row([one(r) for r in item]))
        else:
            ctrl = one(item)
            if ctrl is not None:
                controls.append(ctrl)
    return controls


def _binds_edges(row_defs):
    return any(r.get("target") for r in row_defs)


def make_widget(wdef):
    """Create a live Widget instance from a validated definition."""
    from ..ui.widgets import Widget

    class ComposedWidget(Widget):
        pass

    inst = ComposedWidget.__new__(ComposedWidget)
    inst.name = wdef["name"]
    inst.title = wdef["title"]
    inst.space = wdef.get("space", "VIEW_3D")
    inst.composed_def = wdef
    edge_bound = _binds_edges(wdef["rows"])
    inst.poll = (lambda context: context.mode == "EDIT_MESH") if edge_bound \
        else (lambda context: True)
    inst.controls = build_controls(wdef["rows"])
    from ..ui.widgets.panel import WidgetPanel
    inst.panel = WidgetPanel(title=inst.title or inst.name)
    return inst


# ----------------------------------------------------------------------
# File IO (one JSON per widget, user presets folder)
# ----------------------------------------------------------------------
def widgets_folder():
    import bpy
    return os.path.join(bpy.utils.script_path_user(),
                        "presets", "IOPS", "widgets")


def widget_path(name):
    return os.path.join(widgets_folder(), sanitize_name(name) + _EXT)


def list_widget_files():
    folder = widgets_folder()
    if not os.path.isdir(folder):
        return []
    return sorted(f for f in os.listdir(folder)
                  if f.endswith(_EXT)
                  and os.path.isfile(os.path.join(folder, f)))


def load_def(path):
    """Read + validate one definition file. Returns (clean_def, errors);
    clean_def None = unusable file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        return None, [f"unreadable JSON: {e}"]
    return validate_def(data)


def save_def(wdef):
    """Atomic write of a validated definition to its canonical path."""
    path = widget_path(wdef["name"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(wdef, f, indent=2)
    os.replace(tmp, path)
    return path


def delete_def(name):
    path = widget_path(name)
    if os.path.isfile(path):
        os.remove(path)
        return True
    return False


# ----------------------------------------------------------------------
# Registry sync
# ----------------------------------------------------------------------
# Names of composed widgets currently live in the framework registry —
# so unregister/reload only ever touches widgets this module created.
_live = set()


def register_composed(wdef):
    """(Re)register one composed widget. A composed widget may not shadow
    a built-in (Python) widget name."""
    from ..ui import widgets as framework
    existing = framework.get_widget(wdef["name"])
    if existing is not None and wdef["name"] not in _live:
        return None, f"name '{wdef['name']}' is taken by a built-in widget"
    inst = framework.register_widget(make_widget(wdef))
    _live.add(wdef["name"])
    return inst, None


def unregister_composed(name):
    from ..ui import widgets as framework
    if name in _live:
        framework.unregister_widget(name)
        _live.discard(name)


def load_all():
    """Load every definition file, register the valid ones, drop live
    widgets whose file disappeared. Returns {filename: [errors]} for
    everything that reported problems."""
    problems = {}
    seen = set()
    for fn in list_widget_files():
        path = os.path.join(widgets_folder(), fn)
        wdef, errors = load_def(path)
        if errors:
            problems[fn] = errors
        if wdef is None:
            continue
        _, err = register_composed(wdef)
        if err:
            problems.setdefault(fn, []).append(err)
            continue
        seen.add(wdef["name"])
    for name in tuple(_live - seen):
        unregister_composed(name)
    return problems


def unregister_all():
    for name in tuple(_live):
        unregister_composed(name)
