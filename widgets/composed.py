"""JSON-composed widgets — the runtime behind the prefs "Widgets" tab.

A composed widget is a JSON definition built from the known block palette
(Section / Slider / Presets / FlipBox / Button / Swatch) with value rows bound to
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

ROW_TYPES = ("SECTION", "SLIDER", "PRESETS", "FLIPBOX", "BUTTON", "ROW", "SWATCH")
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


def resolve_rna_owner(root, path):
    """Walk a dotted attribute path from `root`, returning
    (owner, last_attr) so callers can get/set the final attribute.
    Returns (None, None) if any intermediate segment is missing.
    Pure (getattr only) — pytest-covered with a fake object."""
    parts = [p for p in str(path).split(".") if p]
    if not parts:
        return None, None
    owner = root
    for attr in parts[:-1]:
        owner = getattr(owner, attr, None)
        if owner is None:
            return None, None
    return owner, parts[-1]


def rna_bool_adapter(path):
    """A get/set bundle for an arbitrary RNA boolean resolved against
    `context` (e.g. "scene.CCP.red_export_opaqueAreas"). Absence-safe:
    get returns (None, False) -> control renders disabled; set no-ops.
    Scalar binding, so is_mixed is always False."""
    def get(context):
        owner, attr = resolve_rna_owner(context, path)
        if owner is None or not hasattr(owner, attr):
            return (None, False)
        return (bool(getattr(owner, attr)), False)

    def set(context, value):
        owner, attr = resolve_rna_owner(context, path)
        if owner is not None and hasattr(owner, attr):
            setattr(owner, attr, bool(value))

    return {"get": get, "set": set}


def rna_color_adapter(path):
    """A read-only get bundle for an arbitrary RNA color (FloatVector
    subtype COLOR) resolved against `context` (e.g.
    "scene.IOPS.iops_object_color"). Absence-safe: get returns
    (None, False) -> the swatch renders disabled. Scalar binding, so
    is_mixed is always False."""
    def get(context):
        owner, attr = resolve_rna_owner(context, path)
        if owner is None or not hasattr(owner, attr):
            return (None, False)
        return (tuple(getattr(owner, attr)), False)

    return {"get": get}


def unique_name(base, taken):
    """`base`, or `base_2`, `base_3`, ... — first not in `taken`."""
    if base not in taken:
        return base
    i = 2
    while f"{base}_{i}" in taken:
        i += 1
    return f"{base}_{i}"


def _clean_row(row):
    """Validate + normalize ONE row def. Returns (out_dict, error_or_None).
    out_dict is None when the row is unusable. Shared by validate_def's
    top-level loop and ROW cell validation."""
    if not isinstance(row, dict):
        return None, "not an object"
    rtype = str(row.get("type", "")).upper()
    if rtype not in ROW_TYPES:
        return None, f"unknown type '{rtype}'"
    out = {"type": rtype}
    if rtype == "SECTION":
        out["label"] = str(row.get("label", ""))
        return out, None
    if rtype == "SLIDER":
        target = str(row.get("target", "")).upper()
        if target not in FLOAT_TARGETS:
            return None, f"slider target '{target}' invalid"
        out["target"] = target
        try:
            out["snap"] = max(0.0, float(row.get("snap", 0.125)))
        except (TypeError, ValueError):
            out["snap"] = 0.125
        return out, None
    if rtype == "PRESETS":
        target = str(row.get("target", "")).upper()
        if target not in FLOAT_TARGETS:
            return None, f"presets target '{target}' invalid"
        out["target"] = target
        vals = []
        values = row.get("values", [])
        if isinstance(values, list):
            for v in values:
                try:
                    vals.append(max(0.0, min(1.0, float(v))))
                except (TypeError, ValueError):
                    pass
        if not vals:
            return None, "presets without values"
        out["values"] = vals
        return out, None
    if rtype == "FLIPBOX":
        prop = str(row.get("prop", "")).strip()
        target = str(row.get("target", "")).strip().upper()
        if bool(prop) == bool(target):
            return None, "flipbox needs exactly one of prop/target"
        if prop:
            out["prop"] = prop
            out["label"] = str(row.get("label", "")) or prop.rsplit(".", 1)[-1]
        else:
            if target not in BOOL_TARGETS:
                return None, f"flipbox target '{target}' invalid"
            out["target"] = target
            out["label"] = str(row.get("label", "")) or target.title()
        return out, None
    if rtype == "ROW":
        cells_in = row.get("cells", [])
        if not isinstance(cells_in, list):
            return None, "row cells is not a list"
        cells = []
        for cell in cells_in:
            c, _err = _clean_row(cell)
            if c is None or c["type"] == "ROW":
                continue   # drop unusable / nested ROW cells silently
            cells.append(c)
        if not cells:
            return None, "row has no usable cells"
        out["cells"] = cells
        return out, None
    if rtype == "SWATCH":
        prop = str(row.get("prop", "")).strip()
        if not prop:
            return None, "swatch needs a prop (RNA color path)"
        op = str(row.get("op", "")).strip()
        if "." not in op:
            return None, f"swatch op '{op}' is not an operator idname"
        out["prop"] = prop
        out["op"] = op
        out["label"] = str(row.get("label", ""))
        kwargs = row.get("op_kwargs", {})
        out["op_kwargs"] = kwargs if isinstance(kwargs, dict) else {}
        return out, None
    # BUTTON
    op = str(row.get("op", "")).strip()
    if "." not in op:
        return None, f"button op '{op}' is not an operator idname"
    out["op"] = op
    out["label"] = str(row.get("label", "")) or op
    kwargs = row.get("op_kwargs", {})
    out["op_kwargs"] = kwargs if isinstance(kwargs, dict) else {}
    role = str(row.get("role", "default"))
    out["role"] = role if role in ("default", "error") else "default"
    return out, None


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
        out, err = _clean_row(row)
        if err:
            errors.append(f"row {i}: {err} — dropped")
        if out is not None:
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
                              ActionButton, Row, Swatch)
    from .adapters import ADAPTERS, has_selected_edges

    edge_bound = _binds_edges(row_defs)
    # Buttons/presets gray with no selection ONLY for edge widgets; a
    # scene-prop widget (e.g. ccp_data_ops) keeps them always enabled.
    gate = has_selected_edges if edge_bound else None

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
            return PresetRow(row["values"], set=a["set"], enabled_get=gate)
        if rtype == "FLIPBOX":
            if row.get("prop"):
                ad = rna_bool_adapter(row["prop"])
                return FlipBox(row["label"], get=ad["get"], set=ad["set"])
            a = ADAPTERS[row["target"]]
            return FlipBox(row["label"], get=a["get"], set=a["set"])
        if rtype == "SWATCH":
            ad = rna_color_adapter(row["prop"])
            return Swatch(get=ad["get"], op=row["op"],
                          kwargs=row.get("op_kwargs") or {},
                          label=row.get("label", ""))
        if rtype == "BUTTON":
            return ActionButton(row["label"], op=row["op"],
                                kwargs=row.get("op_kwargs") or {},
                                role=row.get("role", "default"),
                                enabled_get=gate)
        return None

    controls = []
    for item in merge_flipbox_runs(row_defs):
        if isinstance(item, list):
            controls.append(Row([one(r) for r in item]))
        elif isinstance(item, dict) and item.get("type") == "ROW":
            controls.append(Row([one(r) for r in item["cells"]]))
        else:
            ctrl = one(item)
            if ctrl is not None:
                controls.append(ctrl)
    return controls


def _binds_edges(row_defs):
    """True if any control binds an EDGE adapter (target=). Recurses into
    ROW cells. prop-bound flipboxes are NOT edge-bound."""
    def row_binds(r):
        if r.get("type") == "ROW":
            return any(row_binds(c) for c in r.get("cells", []))
        return bool(r.get("target"))
    return any(row_binds(r) for r in row_defs)


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
    base = bpy.utils.script_path_user()
    try:
        prefs = bpy.context.preferences.addons["InteractionOps"].preferences
    except (KeyError, AttributeError):
        # Early register / factory-startup: fall back to the canonical path
        return os.path.join(base, "presets", "IOPS", "widgets")
    if getattr(prefs, "widgets_use_script_path_user", True):
        sub = (prefs.widgets_subfolder or "").strip()
        return os.path.join(base, sub) if sub else base
    return prefs.widgets_folder or os.path.join(base, "presets", "IOPS",
                                                "widgets")


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
    """(Re)register one composed widget. Idempotent — keyed by name.

    Re-registration rebuilds the Widget with a FRESH panel at its default
    corner; seed it from the persisted state so a (re)register never
    drops the remembered on-screen position."""
    from ..ui import widgets as framework
    from ..ui.widgets import state
    inst = framework.register_widget(make_widget(wdef))
    st = state.get_state(inst.name)
    inst.panel.x = float(st.get("x", inst.panel.x))
    inst.panel.y = float(st.get("y", inst.panel.y))
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
