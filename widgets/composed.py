"""JSON-composed widgets — the runtime behind the prefs "Widgets" tab.

A composed widget is a JSON definition built from the known block palette
(Section / Slider / Presets / FlipBox / Button / Swatch / Dropdown / Input /
Buttons) with value rows bound to
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
import math
import os

ROW_TYPES = ("SECTION", "SLIDER", "PRESETS", "FLIPBOX", "BUTTON", "ROW",
             "SWATCH", "DROPDOWN", "INPUT", "BUTTONS")
VALUE_TYPES = ("STRING", "INT", "FLOAT", "DEGREES", "RADIANS", "ENUM")
FLOAT_TARGETS = ("BEVEL", "CREASE")
BOOL_TARGETS = ("SHARP", "SEAM", "FREESTYLE")
SCHEMA_VERSION = 1

# Editor space types a widget panel may anchor in. Kept as a plain tuple
# (composed.py is bpy-free) — must stay in sync with ui/widgets/state.py
# SPACE_TYPES.
WIDGET_SPACES = ("VIEW_3D", "IMAGE_EDITOR")
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


def clean_spaces(raw):
    """Validate a def's `space` field -> a non-empty list of valid space
    types, order-preserving and de-duped. A string or a list is accepted;
    unknown types are dropped; empty/all-invalid falls back to
    ["VIEW_3D"]. Pure — pytest-covered."""
    items = _as_str_list(raw) if raw else []
    out = []
    for s in items:
        if s in WIDGET_SPACES and s not in out:
            out.append(s)
    return out or ["VIEW_3D"]


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


SHOW_IF_SELECTION = ("verts", "edges", "faces", "objects")


def resolve_prop(context, path):
    """Resolve a dotted RNA path against context -> (value, found).
    found=False when any segment is missing. Pure (getattr only)."""
    owner, attr = resolve_rna_owner(context, path)
    if owner is None or not hasattr(owner, attr):
        return (None, False)
    return (getattr(owner, attr), True)


def _as_str_list(value):
    """A str or list -> list of non-empty upper-cased strings."""
    if isinstance(value, (list, tuple, set)):
        items = [str(v).strip().upper() for v in value]
    else:
        items = [str(value).strip().upper()]
    return [s for s in items if s]


def _clean_show_if(raw):
    """Validate/normalize a show_if clause. Returns (clean|None, err)."""
    if not isinstance(raw, dict):
        return None, "show_if is not an object"
    out = {}
    if "mode" in raw:
        modes = _as_str_list(raw["mode"])
        if not modes:
            return None, "show_if mode is empty"
        out["mode"] = modes
    if "object_type" in raw:
        types = _as_str_list(raw["object_type"])
        if not types:
            return None, "show_if object_type is empty"
        out["object_type"] = types
    if "selection" in raw:
        sel = str(raw["selection"]).strip().lower()
        if sel not in SHOW_IF_SELECTION:
            return None, f"show_if selection '{sel}' invalid"
        out["selection"] = sel
    if "prop" in raw:
        p = str(raw["prop"]).strip()
        if not p:
            return None, "show_if prop is empty"
        out["prop"] = p
    if "switch" in raw:
        s = str(raw["switch"]).strip()
        if not s:
            return None, "show_if switch is empty"
        out["switch"] = s
    if "equals" in raw:
        out["equals"] = raw["equals"]
    if not any(k in out for k in
               ("mode", "object_type", "selection", "prop", "switch")):
        return None, "show_if has no recognized keys"
    return out, None


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


def _coerce(value_type, value):
    """Author space -> storage space, by declared type. Pure stdlib."""
    if value_type == "INT":      return int(value)
    if value_type == "FLOAT":    return float(value)
    if value_type == "DEGREES":  return math.radians(float(value))
    if value_type == "RADIANS":  return float(value)
    return str(value)            # STRING / ENUM


def _to_display(value_type, value):
    """Storage space -> author space. Only DEGREES converts."""
    return math.degrees(value) if value_type == "DEGREES" else value


def rna_value_adapter(path, value_type="STRING"):
    """get/set bundle for an arbitrary RNA scalar resolved against
    context. Absence-safe. Scalar, so is_mixed is always False. Works in
    AUTHOR/DISPLAY space: get() returns the author-space value (degrees
    when value_type is DEGREES), set() coerces back to storage space
    (radians for DEGREES) by the DECLARED value_type — no RNA
    introspection."""
    def get(context):
        owner, attr = resolve_rna_owner(context, path)
        if owner is None or not hasattr(owner, attr):
            return (None, False)
        return (_to_display(value_type, getattr(owner, attr)), False)

    def set(context, value):
        owner, attr = resolve_rna_owner(context, path)
        if owner is not None and hasattr(owner, attr):
            setattr(owner, attr, _coerce(value_type, value))

    return {"get": get, "set": set}


def rna_enum_items(path):
    """Runtime fallback list for a DROPDOWN with no declared `labels`:
    items_get(context) -> [(identifier, display), ...] by reading the live
    enum's `bl_rna.properties[attr].enum_items`. Returns [] when the path /
    owner / property is missing or not an enum. getattr-only, so plain fake
    objects (no bl_rna) yield [] under pytest — never the source of truth,
    only a convenience when items aren't declared in JSON."""
    def items_get(context):
        owner, attr = resolve_rna_owner(context, path)
        if owner is None:
            return []
        try:
            prop = owner.bl_rna.properties[attr]
            return [(it.identifier, it.name) for it in prop.enum_items]
        except (AttributeError, KeyError, TypeError):
            return []
    return items_get


# ----------------------------------------------------------------------
# Live DROPDOWN item providers. A DROPDOWN row may set "items_from": NAME
# to source its (identifier, label) items from a registered provider
# instead of an RNA enum's bl_rna.enum_items. Needed for dynamic lists
# (e.g. bpy.data.images): a dynamic, items-callback EnumProperty does NOT
# expose its items through bl_rna in script context, so rna_enum_items
# reads an empty list. provider(context) -> [(identifier, label), ...].
# ----------------------------------------------------------------------
DROPDOWN_ITEM_PROVIDERS = {}


def register_dropdown_items(name, provider):
    """Register a live items provider for a DROPDOWN `items_from`.
    `provider` is a callable(context) -> [(identifier, label), ...]."""
    DROPDOWN_ITEM_PROVIDERS[str(name)] = provider


def unregister_dropdown_items(name):
    DROPDOWN_ITEM_PROVIDERS.pop(str(name), None)


def switch_adapter(store, name, on_change=None):
    """get/set bundle for a local widget switch held in `store` (a dict
    on the live widget). set() mutates the store and fires on_change so
    the widget can persist + redraw. Scalar -> is_mixed always False."""
    def get(context):
        return (bool(store.get(name, False)), False)

    def set(context, value):
        store[name] = bool(value)
        if on_change is not None:
            on_change(name, bool(value))

    return {"get": get, "set": set}


def unique_name(base, taken):
    """`base`, or `base_2`, `base_3`, ... — first not in `taken`."""
    if base not in taken:
        return base
    i = 2
    while f"{base}_{i}" in taken:
        i += 1
    return f"{base}_{i}"


def _clean_row_body(row):
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
        switch = str(row.get("switch", "")).strip()
        bound = [b for b in (prop, target, switch) if b]
        if len(bound) != 1:
            return None, "flipbox needs exactly one of prop/target/switch"
        if switch:
            out["switch"] = switch
            out["label"] = str(row.get("label", "")) or switch
        elif prop:
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
            c, _err = _clean_row_body(cell)
            if c is None or c["type"] == "ROW":
                continue   # drop unusable / nested ROW cells silently
            cells.append(c)
        if not cells:
            return None, "row has no usable cells"
        out["cells"] = cells
        return out, None
    if rtype == "DROPDOWN":
        prop = str(row.get("prop", "")).strip()
        if not prop:
            return None, "dropdown needs a prop (RNA enum path)"
        out["prop"] = prop
        out["value_type"] = "ENUM"   # forced — dropdowns bind enums
        out["label"] = str(row.get("label", "")) or prop.rsplit(".", 1)[-1]
        labels = row.get("labels", {})
        out["labels"] = {str(k): str(v) for k, v in labels.items()} \
            if isinstance(labels, dict) else {}
        items_from = str(row.get("items_from", "")).strip()
        if items_from:
            out["items_from"] = items_from
        return out, None
    if rtype == "INPUT":
        prop = str(row.get("prop", "")).strip()
        if not prop:
            return None, "input needs a prop (RNA path)"
        out["prop"] = prop
        vt = str(row.get("value_type", "STRING")).strip().upper()
        if vt not in VALUE_TYPES:
            return None, f"input value_type '{vt}' invalid"
        out["value_type"] = vt
        out["label"] = str(row.get("label", "")) or prop.rsplit(".", 1)[-1]
        out["fmt"] = str(row.get("fmt", "{}"))
        return out, None
    if rtype == "BUTTONS":
        prop = str(row.get("prop", "")).strip()
        if not prop:
            return None, "buttons needs a prop (RNA path)"
        out["prop"] = prop
        vt = str(row.get("value_type", "FLOAT")).strip().upper()
        if vt not in VALUE_TYPES:
            return None, f"buttons value_type '{vt}' invalid"
        out["value_type"] = vt
        out["fmt"] = str(row.get("fmt", "{:g}"))
        if vt == "ENUM":
            # Enum mode: declared items, identifier or [id, label] pairs.
            items_in = row.get("items", [])
            items = []
            if isinstance(items_in, list):
                for it in items_in:
                    if isinstance(it, (list, tuple)):
                        # [id, label] pair, or a 1-element [id] list — use
                        # the first element as the identifier either way
                        # (never stringify the whole list into a garbage id).
                        if not it:
                            continue
                        ident = str(it[0]).strip()
                        if ident:
                            items.append([ident, str(it[1])] if len(it) >= 2
                                         else ident)
                    else:
                        # Bare identifier kept as a plain string; the
                        # (value, label) pairing happens later in
                        # button_group_options.
                        ident = str(it).strip()
                        if ident:
                            items.append(ident)
            if not items:
                return None, "buttons (ENUM) without items"
            out["items"] = items
        else:
            # Number mode: values coerced to floats, NOT clamped.
            vals = []
            values = row.get("values", [])
            if isinstance(values, list):
                for v in values:
                    try:
                        vals.append(float(v))
                    except (TypeError, ValueError):
                        pass
            if not vals:
                return None, "buttons without values"
            out["values"] = vals
            unit = row.get("unit", None)
            if unit is None:
                out["unit"] = "°" if vt == "DEGREES" else ""
            else:
                out["unit"] = str(unit)
        return out, None
    if rtype == "SWATCH":
        prop = str(row.get("prop", "")).strip()
        color = row.get("color", None)
        has_color = color is not None
        if prop and has_color:
            return None, "swatch needs exactly one of prop or color, not both"
        if not prop and not has_color:
            return None, "swatch needs a prop (RNA color path) or a literal color"
        op = str(row.get("op", "")).strip()
        if "." not in op:
            return None, f"swatch op '{op}' is not an operator idname"
        if has_color:
            if (not isinstance(color, (list, tuple)) or len(color) != 4
                    or not all(isinstance(c, (int, float)) for c in color)):
                return None, "swatch color must be a list of 4 numbers"
            out["color"] = [float(c) for c in color]
        else:
            out["prop"] = prop
        out["op"] = op
        out["label"] = str(row.get("label", ""))
        kwargs = row.get("op_kwargs", {})
        out["op_kwargs"] = kwargs if isinstance(kwargs, dict) else {}
        if bool(row.get("show_alpha", False)):
            out["show_alpha"] = True
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


def _clean_row(row):
    """Validate one row (delegates to _clean_row_body), then parse an
    optional show_if. Invalid show_if keeps the row always-visible and
    reports — never drops the row for a bad predicate."""
    out, err = _clean_row_body(row)
    if out is None:
        return None, err
    if isinstance(row, dict) and "show_if" in row:
        si, si_err = _clean_show_if(row["show_if"])
        if si_err:
            return out, f"invalid show_if ({si_err}); row kept always-visible"
        out["show_if"] = si
    return out, err


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
        "space": clean_spaces(data.get("space")),
        "rows": [],
    }
    clean["switches"] = {}
    raw_switches = data.get("switches", {})
    if isinstance(raw_switches, dict):
        for k, v in raw_switches.items():
            clean["switches"][str(k)] = bool(v)
    rows = data.get("rows", [])
    if not isinstance(rows, list):
        return clean, ["rows is not a list"]
    for i, row in enumerate(rows):
        out, err = _clean_row(row)
        if err:
            suffix = "" if out is not None else " — dropped"
            errors.append(f"row {i}: {err}{suffix}")
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
        if row.get("type") == "FLIPBOX" and "show_if" not in row:
            run.append(row)
            continue
        if run:
            merged.append(run if len(run) > 1 else run[0])
            run = []
        merged.append(row)
    if run:
        merged.append(run if len(run) > 1 else run[0])
    return merged


def collect_switches(wdef):
    """Every switch name referenced by the def -> its default bool.
    Default False; overridden by the validated `switches` map. Recurses
    into ROW cells for switch flipboxes (show_if only on top-level rows)."""
    names = set()

    def scan(row):
        if not isinstance(row, dict):
            return
        if row.get("type") == "FLIPBOX" and row.get("switch"):
            names.add(row["switch"])
        if row.get("type") == "ROW":
            for cell in row.get("cells", []):
                scan(cell)
        si = row.get("show_if")
        if isinstance(si, dict) and si.get("switch"):
            names.add(si["switch"])

    for row in wdef.get("rows", []):
        scan(row)
    defaults = wdef.get("switches", {})
    return {name: bool(defaults.get(name, False)) for name in names}


# ----------------------------------------------------------------------
# Control building (bpy/bmesh deferred)
# ----------------------------------------------------------------------
def build_controls(row_defs, switch_store=None, on_switch=None):
    """Materialize a validated `rows` list into framework controls.
    `switch_store` (a dict) backs switch flipboxes; `on_switch(name, value)`
    fires on a switch write (persist + redraw). Each produced top-level
    control carries its `_show_if` predicate (None = always visible)."""
    # Relative for Blender (addon loads as package InteractionOps, so
    # ..ui.widgets -> InteractionOps.ui.widgets); absolute fallback for
    # pytest (composed is loaded top-level as widgets.composed, where ..
    # is beyond the package boundary but `ui` is on sys.path via _ROOT).
    try:
        from ..ui.widgets import (Section, Slider, PresetRow, FlipBox,
                                  ActionButton, Row, Swatch, Dropdown,
                                  InputField, ButtonGroup)
        from ..ui.widgets.controls import button_group_options
    except ImportError:
        from ui.widgets import (Section, Slider, PresetRow, FlipBox,
                                ActionButton, Row, Swatch, Dropdown,
                                InputField, ButtonGroup)
        from ui.widgets.controls import button_group_options

    if switch_store is None:
        switch_store = {}
    edge_bound = _binds_edges(row_defs)
    # has_selected_edges gates presets/buttons for edge widgets; only edge
    # widgets need it (and the bmesh-backed adapters module), so the import
    # is deferred to here — keeps composed importable bpy-free for tests.
    gate = None
    if edge_bound:
        from .adapters import has_selected_edges
        gate = has_selected_edges

    def one(row):
        rtype = row["type"]
        if rtype == "SECTION":
            return Section(row.get("label", ""))
        if rtype == "SLIDER":
            from .adapters import ADAPTERS
            a = ADAPTERS[row["target"]]
            return Slider(get=a["get"], set=a["set"],
                          snap=row.get("snap", 0.125),
                          snapshot=a.get("snapshot"),
                          restore=a.get("restore"))
        if rtype == "PRESETS":
            from .adapters import ADAPTERS
            a = ADAPTERS[row["target"]]
            return PresetRow(row["values"], set=a["set"], enabled_get=gate)
        if rtype == "FLIPBOX":
            if row.get("switch"):
                ad = switch_adapter(switch_store, row["switch"], on_switch)
                return FlipBox(row["label"], get=ad["get"], set=ad["set"])
            if row.get("prop"):
                ad = rna_bool_adapter(row["prop"])
                return FlipBox(row["label"], get=ad["get"], set=ad["set"])
            from .adapters import ADAPTERS
            a = ADAPTERS[row["target"]]
            return FlipBox(row["label"], get=a["get"], set=a["set"])
        if rtype == "SWATCH":
            if "color" in row:
                const = tuple(row["color"])
                get = lambda context, _c=const: (_c, False)
            else:
                get = rna_color_adapter(row["prop"])["get"]
            return Swatch(get=get, op=row["op"],
                          kwargs=row.get("op_kwargs") or {},
                          label=row.get("label", ""),
                          show_alpha=bool(row.get("show_alpha", False)))
        if rtype == "DROPDOWN":
            ad = rna_value_adapter(row["prop"], row["value_type"])
            src = row.get("items_from")
            items_get = (DROPDOWN_ITEM_PROVIDERS.get(src) if src else None) \
                or rna_enum_items(row["prop"])
            return Dropdown(get=ad["get"], set=ad["set"], path=row["prop"],
                            items_get=items_get,
                            labels=row.get("labels") or {},
                            label=row.get("label", ""))
        if rtype == "INPUT":
            ad = rna_value_adapter(row["prop"], row["value_type"])
            return InputField(get=ad["get"], set=ad["set"], path=row["prop"],
                              fmt=row.get("fmt", "{}"),
                              label=row.get("label", ""))
        if rtype == "BUTTONS":
            ad = rna_value_adapter(row["prop"], row["value_type"])
            options = button_group_options(row.get("values"),
                                           row.get("items"),
                                           row.get("fmt", "{:g}"),
                                           row.get("unit", ""))
            return ButtonGroup(get=ad["get"], set=ad["set"], options=options)
        if rtype == "BUTTON":
            return ActionButton(row["label"], op=row["op"],
                                kwargs=row.get("op_kwargs") or {},
                                role=row.get("role", "default"),
                                enabled_get=gate)
        return None

    controls = []
    for item in merge_flipbox_runs(row_defs):
        if isinstance(item, list):
            ctrl = Row([one(r) for r in item])
            ctrl._show_if = None
        elif isinstance(item, dict) and item.get("type") == "ROW":
            ctrl = Row([one(r) for r in item["cells"]])
            ctrl._show_if = item.get("show_if")
        else:
            ctrl = one(item)
            if ctrl is None:
                continue
            ctrl._show_if = item.get("show_if")
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
    inst.switches = collect_switches(wdef)

    def on_switch(_name, _value):
        # Persist the new switch state and repaint (visible rows change).
        from ..ui.widgets import state
        state.store_switches(inst.name, inst.switches)
        state.tag_redraw_all()

    edge_bound = _binds_edges(wdef["rows"])
    inst.poll = (lambda context: context.mode == "EDIT_MESH") if edge_bound \
        else (lambda context: True)
    inst.controls = build_controls(wdef["rows"], switch_store=inst.switches,
                                   on_switch=on_switch)
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
    saved = st.get("switches", {})
    if isinstance(saved, dict):
        for k, v in saved.items():
            if k in inst.switches:
                inst.switches[k] = bool(v)
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
