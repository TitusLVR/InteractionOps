"""JSON-composed widgets — the runtime behind the prefs "Widgets" tab.

A composed widget is a JSON definition built from the known block palette
(Section / Slider / Presets / FlipBox / Button / Swatch / Dropdown / Input /
Buttons) with value rows bound to RNA props, scene-store keys or mesh
attributes (adapters.attribute_adapter; legacy `target` ids load as
attributes, see LEGACY_TARGETS). One file per widget in
`bpy.utils.script_path_user()/presets/IOPS/widgets/<name>.json`:

    {
      "version": 1,
      "name": "edge_data_custom",
      "title": "Edge Data",
      "space": "VIEW_3D",
      "width": 150,            (optional: min content width in px)
      "rows": [
        {"type": "SECTION", "label": "Bevel Weight"},
        {"type": "SLIDER",  "attribute": "bevel_weight_edge",
         "domain": "EDGE", "snap": 0.125},
        {"type": "PRESETS", "attribute": "bevel_weight_edge",
         "domain": "EDGE", "values": [0, 0.25, 0.5, 1.0]},
        {"type": "FLIPBOX", "attribute": "sharp_edge", "domain": "EDGE",
         "label": "Sharp"},
        {"type": "BUTTON",  "label": "Clear", "op": "iops.executor",
         "op_kwargs": {"script": "..."}, "role": "error"},
        {"type": "SPACER", "height": 12},
        {"type": "ROW", "cells": [
            {"type": "BUTTON", "label": "A", "op": "a.b", "span": 8},
            {"type": "BUTTON", "label": "B", "op": "a.c", "span": 4,
             "show_if": {"mode": "OBJECT"}}]}
      ]
    }

Any row or ROW cell may carry `"span": 1..12` (12-step grid; a ROW's cell
spans are all-or-nothing, see normalize_spans). Cells may carry `show_if`.
SPACER is an empty row/cell (`height` px, top-level only).

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
             "SWATCH", "DROPDOWN", "INPUT", "BUTTONS", "SPACER")
GRID = 12
MIN_SPACER_HEIGHT = 2.0
VALUE_TYPES = ("STRING", "INT", "FLOAT", "DEGREES", "RADIANS", "ENUM")
NUMBER_VALUE_TYPES = ("INT", "FLOAT", "DEGREES", "RADIANS")
# Mesh attribute domains an `attribute` binding may target (Blender's
# domain identifiers; values apply to the selected elements of the domain).
ATTR_DOMAINS = ("POINT", "EDGE", "FACE")
# Pre-attribute `target` ids -> (attribute, domain, kind). Converted on
# load (Save writes the attribute form); legacy float targets keep their
# old 0..1 range and slider snap/format.
LEGACY_TARGETS = {
    "BEVEL": ("bevel_weight_edge", "EDGE", "float"),
    "CREASE": ("crease_edge", "EDGE", "float"),
    "SHARP": ("sharp_edge", "EDGE", "bool"),
    "SEAM": ("uv_seam", "EDGE", "bool"),
    "FREESTYLE": ("freestyle_edge", "EDGE", "bool"),
}
SCHEMA_VERSION = 1
MIN_WIDGET_WIDTH = 60.0

# Editor space types a widget panel may anchor in. Kept as a plain tuple
# (composed.py is bpy-free) — must stay in sync with ui/widgets/state.py
# SPACE_TYPES.
WIDGET_SPACES = ("VIEW_3D", "IMAGE_EDITOR")
_EXT = ".json"
# Editor drafts live next to the real file and are never listed/loaded.
DRAFT_SUFFIX = ".draft.json"

# Composer-editable mirror of widgets/edge_data.py — the template behind
# "Duplicate" on the built-in entry and its JSON export.
EDGE_DATA_DEF = {
    "version": SCHEMA_VERSION,
    "name": "edge_data",
    "title": "Edge Data",
    "space": "VIEW_3D",
    "rows": [
        {"type": "SECTION", "label": "Bevel Weight"},
        {"type": "SLIDER", "attribute": "bevel_weight_edge",
         "domain": "EDGE", "snap": 0.125, "fmt": "{:.3f}"},
        {"type": "PRESETS", "attribute": "bevel_weight_edge",
         "domain": "EDGE", "values": [0, 0.25, 0.5, 1.0]},
        {"type": "SECTION", "label": "Crease"},
        {"type": "SLIDER", "attribute": "crease_edge", "domain": "EDGE",
         "snap": 0.125, "fmt": "{:.3f}"},
        {"type": "PRESETS", "attribute": "crease_edge", "domain": "EDGE",
         "values": [0, 0.5, 0.9, 1.0]},
        {"type": "SECTION", "label": "Flags"},
        {"type": "FLIPBOX", "attribute": "sharp_edge", "domain": "EDGE",
         "label": "Sharp"},
        {"type": "FLIPBOX", "attribute": "uv_seam", "domain": "EDGE",
         "label": "Seam"},
        {"type": "FLIPBOX", "attribute": "freestyle_edge", "domain": "EDGE",
         "label": "Freestyle"},
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


def _clean_attribute(row, out):
    """Copy a valid `attribute` + `domain` pair from `row` into `out`.
    Returns an error string, or None on success."""
    name = str(row.get("attribute", "")).strip()
    if not name or name.startswith(".") or name == "position":
        return f"attribute '{name}' is reserved"
    domain = str(row.get("domain", "EDGE")).strip().upper()
    if domain not in ATTR_DOMAINS:
        return f"attribute domain '{domain}' invalid"
    out["attribute"] = name
    out["domain"] = domain
    return None


def _from_legacy_target(row, rtype):
    """(row copy with `target` rewritten as attribute keys, error)."""
    row = dict(row)
    target = str(row.pop("target", "")).strip().upper()
    if not target:
        return row, None
    if row.get("attribute"):
        return None, "legacy target and attribute both set"
    if target not in LEGACY_TARGETS:
        return None, f"{rtype.lower()} target '{target}' invalid"
    name, domain, kind = LEGACY_TARGETS[target]
    if (kind == "bool") != (rtype == "FLIPBOX"):
        return None, f"{rtype.lower()} target '{target}' invalid"
    row["attribute"], row["domain"] = name, domain
    if rtype == "FLIPBOX":
        row.setdefault("label", target.title())
    elif rtype == "SLIDER":
        try:
            row["snap"] = float(row.get("snap", 0.125))
        except (TypeError, ValueError):
            row["snap"] = 0.125
        row.setdefault("fmt", "{:.3f}")
    elif isinstance(row.get("values"), list):
        clamped = []
        for v in row["values"]:
            try:
                clamped.append(max(0.0, min(1.0, float(v))))
            except (TypeError, ValueError):
                pass
        row["values"] = clamped
    return row, None


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
    if rtype == "SPACER":
        if "height" in row:
            try:
                h = float(row["height"])
            except (TypeError, ValueError):
                h = None
            if h is not None and h >= MIN_SPACER_HEIGHT:
                out["height"] = h
        return out, None
    if rtype in ("SLIDER", "PRESETS", "FLIPBOX") and "target" in row:
        row, err = _from_legacy_target(row, rtype)
        if err:
            return None, err
    if rtype == "SLIDER":
        prop = str(row.get("prop", "")).strip()
        attr = str(row.get("attribute", "")).strip()
        if bool(prop) == bool(attr):
            return None, "slider needs exactly one of prop/attribute"
        if attr:
            err = _clean_attribute(row, out)
            if err:
                return None, err
        else:
            out["prop"] = prop
        # Arbitrary scalar, author-declared range.
        vt = str(row.get("value_type", "FLOAT")).upper()
        if vt not in NUMBER_VALUE_TYPES:
            return None, f"slider value_type '{vt}' invalid"
        out["value_type"] = vt
        try:
            vmin = float(row.get("min", 0.0))
            vmax = float(row.get("max", 1.0))
        except (TypeError, ValueError):
            return None, "slider min/max invalid"
        if not vmax > vmin:
            return None, "slider min/max invalid"
        out["min"], out["max"] = vmin, vmax
        out["fmt"] = str(row.get("fmt", "{:.2f}"))
        try:
            out["snap"] = max(0.0, float(row.get("snap", 0.0)))
        except (TypeError, ValueError):
            out["snap"] = 0.0
        return out, None
    if rtype == "PRESETS":
        prop = str(row.get("prop", "")).strip()
        data = str(row.get("data", "")).strip()
        attr = str(row.get("attribute", "")).strip()
        if len([b for b in (prop, data, attr) if b]) != 1:
            return None, ("presets needs exactly one of"
                          " prop/data/attribute")
        if attr:
            err = _clean_attribute(row, out)
            if err:
                return None, err
        elif data:
            out["data"] = data
        else:
            out["prop"] = prop
        vt = str(row.get("value_type", "FLOAT")).strip().upper()
        if vt not in NUMBER_VALUE_TYPES:
            return None, f"presets value_type '{vt}' invalid"
        out["value_type"] = vt
        vals = []
        values = row.get("values", [])
        if isinstance(values, list):
            for v in values:
                try:
                    vals.append(float(v))
                except (TypeError, ValueError):
                    pass
        if not vals:
            return None, "presets without values"
        out["values"] = vals
        if "fmt" in row:
            out["fmt"] = str(row["fmt"])
        return out, None
    if rtype == "FLIPBOX":
        prop = str(row.get("prop", "")).strip()
        attr = str(row.get("attribute", "")).strip()
        switch = str(row.get("switch", "")).strip()
        data = str(row.get("data", "")).strip()
        bound = [b for b in (prop, attr, switch, data) if b]
        if len(bound) != 1:
            return None, ("flipbox needs exactly one of"
                          " prop/attribute/switch/data")
        if data:
            out["data"] = data
            out["label"] = str(row.get("label", "")) or data
        elif switch:
            out["switch"] = switch
            out["label"] = str(row.get("label", "")) or switch
        elif prop:
            out["prop"] = prop
            out["label"] = str(row.get("label", "")) or prop.rsplit(".", 1)[-1]
        else:
            err = _clean_attribute(row, out)
            if err:
                return None, err
            out["label"] = str(row.get("label", "")) or attr
        return out, None
    if rtype == "ROW":
        cells_in = row.get("cells", [])
        if not isinstance(cells_in, list):
            return None, "row cells is not a list"
        cells = []
        cell_errs = []
        for j, cell in enumerate(cells_in):
            c, cerr = _clean_row(cell)
            if c is None:
                cell_errs.append(f"cell {j}: {cerr} — dropped")
                continue
            if c["type"] == "ROW":
                cell_errs.append(f"cell {j}: nested ROW — dropped")
                continue
            if cerr:
                cell_errs.append(f"cell {j}: {cerr}")
            cells.append(c)
        if not cells:
            return None, "row has no usable cells"
        spans = normalize_spans([c.get("span") for c in cells])
        if spans is not None:
            for c, sp in zip(cells, spans):
                c["span"] = sp
        out["cells"] = cells
        return out, ("; ".join(cell_errs) or None)
    if rtype == "DROPDOWN":
        prop = str(row.get("prop", "")).strip()
        data = str(row.get("data", "")).strip()
        if bool(prop) == bool(data):
            return None, ("dropdown needs exactly one of prop (RNA enum"
                          " path) / data (scene-store key)")
        if data:
            out["data"] = data
        else:
            out["prop"] = prop
        out["value_type"] = "ENUM"   # forced — dropdowns bind enums
        out["label"] = (str(row.get("label", ""))
                        or data or prop.rsplit(".", 1)[-1])
        labels = row.get("labels", {})
        out["labels"] = {str(k): str(v) for k, v in labels.items()} \
            if isinstance(labels, dict) else {}
        items_from = str(row.get("items_from", "")).strip()
        if items_from:
            out["items_from"] = items_from
        return out, None
    if rtype == "INPUT":
        prop = str(row.get("prop", "")).strip()
        data = str(row.get("data", "")).strip()
        if bool(prop) == bool(data):
            return None, ("input needs exactly one of prop (RNA path)"
                          " / data (scene-store key)")
        if data:
            out["data"] = data
        else:
            out["prop"] = prop
        vt = str(row.get("value_type", "STRING")).strip().upper()
        if vt not in VALUE_TYPES:
            return None, f"input value_type '{vt}' invalid"
        out["value_type"] = vt
        out["label"] = (str(row.get("label", ""))
                        or data or prop.rsplit(".", 1)[-1])
        out["fmt"] = str(row.get("fmt", "{}"))
        return out, None
    if rtype == "BUTTONS":
        prop = str(row.get("prop", "")).strip()
        data = str(row.get("data", "")).strip()
        if bool(prop) == bool(data):
            return None, ("buttons needs exactly one of prop (RNA path)"
                          " / data (scene-store key)")
        if data:
            out["data"] = data
        else:
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


def normalize_spans(spans):
    """Resolve a ROW's per-cell spans (ints or None). None when no cell
    has one; otherwise missing entries share the remaining grid steps
    (>= 1 each) and the total is clipped from the right to <= GRID,
    keeping every span >= 1. Pure."""
    if all(s is None for s in spans):
        return None
    missing = sum(1 for s in spans if s is None)
    given = sum(s for s in spans if s is not None)
    fill = max(1, (GRID - given) // missing) if missing else 0
    out = [fill if s is None else s for s in spans]
    excess = sum(out) - GRID
    for i in range(len(out) - 1, -1, -1):
        if excess <= 0:
            break
        cut = min(excess, out[i] - 1)
        out[i] -= cut
        excess -= cut
    return out


def _clean_row(row):
    """Validate one row (delegates to _clean_row_body), then parse the
    optional `span` and `show_if`. A bad span / show_if keeps the row
    (span dropped / always-visible) and reports — never drops the row for
    them. Used for top-level rows AND ROW cells."""
    out, err = _clean_row_body(row)
    if out is None:
        return None, err
    if isinstance(row, dict) and "span" in row:
        sp = row["span"]
        if (isinstance(sp, int) and not isinstance(sp, bool)
                and 1 <= sp <= GRID):
            out["span"] = sp
        else:
            serr = f"invalid span ({sp!r}); expected 1..{GRID} — ignored"
            err = f"{err}; {serr}" if err else serr
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
    # Optional minimum content width (px). Replaces the renderer's default
    # floor so a widget can be narrower (or wider) than the standard panel;
    # rows that need more room still widen the panel.
    width = data.get("width", None)
    if width is not None:
        try:
            w = float(width)
        except (TypeError, ValueError):
            errors.append("width is not a number — ignored")
        else:
            if w >= MIN_WIDGET_WIDTH:
                clean["width"] = w
            else:
                errors.append(f"width below {MIN_WIDGET_WIDTH:g} — ignored")
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


# Keys whose drop is already reported by validate_def (bad value) or is a
# pure default normalization — never reported as "dropped" again.
_REPORTED_TOP_KEYS = ("width",)
_REPORTED_ROW_KEYS = ("span", "show_if")


def _row_dropped_keys(row, out, where):
    msgs = []
    for k in row:
        if k in out or k in _REPORTED_ROW_KEYS:
            continue
        if k == "target" and "attribute" in out:
            continue                    # legacy id, converted
        if k == "show_alpha" and not row[k]:
            continue                    # False is the default
        msgs.append(f"{where}: unknown or unused key '{k}' — dropped")
    si = row.get("show_if")
    if isinstance(si, dict) and isinstance(out.get("show_if"), dict):
        for k in si:
            if k not in out["show_if"]:
                msgs.append(f"{where}: unknown show_if key '{k}' — dropped")
    if out.get("type") == "ROW" and isinstance(row.get("cells"), list):
        for j, cell in enumerate(row["cells"]):
            c, _err = _clean_row(cell)
            if c is None or c["type"] == "ROW":
                continue                # whole cell dropped (reported)
            msgs.extend(_row_dropped_keys(cell, c, f"{where} cell {j}"))
    return msgs


def dropped_keys(data):
    """One message per key of the raw definition `data` that validate_def
    silently drops (top level, rows, ROW cells, show_if clauses). Rows and
    cells dropped as a whole are skipped — validate_def reports those.
    Pure — pytest-covered."""
    if not isinstance(data, dict):
        return []
    clean, _errors = validate_def(data)
    if clean is None:
        return []
    msgs = [f"unknown key '{k}' — dropped" for k in data
            if k not in clean and k not in _REPORTED_TOP_KEYS]
    rows = data.get("rows", [])
    if isinstance(rows, list):
        for i, row in enumerate(rows):
            out, _err = _clean_row(row)
            if out is not None:
                msgs.extend(_row_dropped_keys(row, out, f"row {i}"))
    return msgs


def merge_flipbox_runs(rows):
    """Group consecutive FLIPBOX row defs: returns a list where each item
    is either a single row def or a list of >=2 flipbox defs (one panel
    row). Pure — pytest-covered."""
    merged = []
    run = []
    for row in rows:
        if (row.get("type") == "FLIPBOX" and "show_if" not in row
                and "span" not in row):
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
def build_controls(row_defs, switch_store=None, on_switch=None, widget_name=""):
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
        from ..ui.widgets.controls import button_group_options, Spacer
    except ImportError:
        from ui.widgets import (Section, Slider, PresetRow, FlipBox,
                                ActionButton, Row, Swatch, Dropdown,
                                InputField, ButtonGroup)
        from ui.widgets.controls import button_group_options, Spacer

    if switch_store is None:
        switch_store = {}
    domains = attribute_domains(row_defs)
    # Mesh-attribute widgets gate presets/buttons on a selection in the
    # bound domains; only they need the bmesh-backed adapters module, so
    # the import is deferred to here — keeps composed importable bpy-free
    # for tests.
    gate = None
    if domains:
        from .adapters import has_selected
        sel_domains = tuple(sorted(domains))

        def gate(context):
            return has_selected(context, sel_domains)

    def attr_adapter(row, kind):
        from .adapters import attribute_adapter
        return attribute_adapter(row["attribute"], row["domain"], kind,
                                 row.get("value_type", "FLOAT"))

    def one(row):
        ctrl = _one(row)
        if ctrl is not None:
            ctrl._span = row.get("span")
            ctrl._show_if = row.get("show_if")
        return ctrl

    def _one(row):
        rtype = row["type"]
        if rtype == "SECTION":
            return Section(row.get("label", ""))
        if rtype == "SPACER":
            return Spacer(span=row.get("span"), height=row.get("height"),
                          placeholder=row.get("_placeholder", ""))
        if rtype == "SLIDER":
            # Value/range in author space (degrees when DEGREES), storage
            # conversion inside the adapter. Prop sliders have no
            # snapshot/restore — cancel falls back to the pre-drag value;
            # attribute sliders restore every element exactly.
            if row.get("attribute"):
                ad = attr_adapter(row, "number")
            else:
                ad = rna_value_adapter(row["prop"], row["value_type"])
            return Slider(get=ad["get"], set=ad["set"],
                          vmin=row["min"], vmax=row["max"],
                          snap=row.get("snap", 0.0),
                          fmt=row.get("fmt", "{:.2f}"),
                          snapshot=ad.get("snapshot"),
                          restore=ad.get("restore"))
        if rtype == "PRESETS":
            fmt = row.get("fmt", "{:g}")
            if row.get("attribute"):
                ad = attr_adapter(row, "number")
            elif row.get("data"):
                from . import scene_store
                ad = scene_store.store_value_adapter(
                    widget_name, row["data"], row["value_type"])
            else:
                ad = rna_value_adapter(row["prop"], row["value_type"])
            return PresetRow(row["values"], set=ad["set"], fmt=fmt,
                             enabled_get=gate)
        if rtype == "FLIPBOX":
            if row.get("data"):
                from . import scene_store
                ad = scene_store.store_bool_adapter(widget_name, row["data"])
                return FlipBox(row["label"], get=ad["get"], set=ad["set"])
            if row.get("switch"):
                ad = switch_adapter(switch_store, row["switch"], on_switch)
                return FlipBox(row["label"], get=ad["get"], set=ad["set"])
            if row.get("prop"):
                ad = rna_bool_adapter(row["prop"])
                return FlipBox(row["label"], get=ad["get"], set=ad["set"])
            ad = attr_adapter(row, "bool")
            return FlipBox(row["label"], get=ad["get"], set=ad["set"])
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
            src = row.get("items_from")
            if row.get("data"):
                from . import scene_store
                ad = scene_store.store_value_adapter(
                    widget_name, row["data"], row["value_type"])
                path = f"{widget_name}:{row['data']}"
                # No RNA enum to introspect for a data binding — a missing
                # provider yields an empty dropdown, matching the existing
                # unknown-provider behavior.
                items_get = (DROPDOWN_ITEM_PROVIDERS.get(src) if src
                             else None) or (lambda context: [])
            else:
                ad = rna_value_adapter(row["prop"], row["value_type"])
                path = row["prop"]
                items_get = (DROPDOWN_ITEM_PROVIDERS.get(src) if src
                             else None) or rna_enum_items(row["prop"])
            return Dropdown(get=ad["get"], set=ad["set"], path=path,
                            items_get=items_get,
                            labels=row.get("labels") or {},
                            label=row.get("label", ""))
        if rtype == "INPUT":
            if row.get("data"):
                from . import scene_store
                ad = scene_store.store_value_adapter(
                    widget_name, row["data"], row["value_type"])
                path = f"{widget_name}:{row['data']}"
            else:
                ad = rna_value_adapter(row["prop"], row["value_type"])
                path = row["prop"]
            return InputField(get=ad["get"], set=ad["set"], path=path,
                              fmt=row.get("fmt", "{}"),
                              label=row.get("label", ""))
        if rtype == "BUTTONS":
            if row.get("data"):
                from . import scene_store
                ad = scene_store.store_value_adapter(
                    widget_name, row["data"], row["value_type"])
            else:
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
            ctrl._span = None
        elif isinstance(item, dict) and item.get("type") == "ROW":
            ctrl = Row([one(r) for r in item["cells"]])
            ctrl._show_if = item.get("show_if")
            ctrl._span = item.get("span")
        else:
            ctrl = one(item)
            if ctrl is None:
                continue
        controls.append(ctrl)
    return controls


def attribute_domains(row_defs):
    """Set of mesh domains bound by `attribute` rows (recurses into ROW
    cells). Empty = the widget touches no mesh attribute."""
    found = set()

    def walk(r):
        if r.get("type") == "ROW":
            for c in r.get("cells", []):
                walk(c)
        elif r.get("attribute"):
            found.add(r.get("domain", "EDGE"))

    for r in row_defs:
        walk(r)
    return found


def make_widget(wdef):
    """Create a live Widget instance from a validated definition."""
    from ..ui.widgets import Widget

    class ComposedWidget(Widget):
        pass

    inst = ComposedWidget.__new__(ComposedWidget)
    inst.name = wdef["name"]
    inst.title = wdef["title"]
    inst.space = wdef.get("space", "VIEW_3D")
    inst.min_content_w = wdef.get("width")
    inst.composed_def = wdef
    inst.switches = collect_switches(wdef)
    inst.default_switches = dict(inst.switches)

    def on_switch(_name, _value):
        # Persist the new switch state and repaint (visible rows change).
        from ..ui.widgets import state
        state.store_switches(inst.name, inst.switches)
        state.tag_redraw_all()

    mesh_bound = bool(attribute_domains(wdef["rows"]))
    inst.poll = (lambda context: context.mode == "EDIT_MESH") if mesh_bound \
        else (lambda context: True)
    inst.controls = build_controls(wdef["rows"], switch_store=inst.switches,
                                   on_switch=on_switch,
                                   widget_name=wdef["name"])
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


# Widgets shipped with the add-on. Read-only: listed and loaded next to
# the user's folder, where a same-named user file overrides the bundled
# one (saving an edited built-in writes that override; deleting it brings
# the built-in back).
BUNDLED_FOLDER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "presets", "widgets")


def widget_path(name):
    """Where `name` is (or would be) written: always the user folder."""
    return os.path.join(widgets_folder(), sanitize_name(name) + _EXT)


def bundled_path(name):
    return os.path.join(BUNDLED_FOLDER, sanitize_name(name) + _EXT)


def source_path(name):
    """The file `name` loads from: the user file, else the bundled one
    (the user path when neither exists)."""
    user = widget_path(name)
    if os.path.isfile(user):
        return user
    bundled = bundled_path(name)
    return bundled if os.path.isfile(bundled) else user


def is_builtin(name):
    """True when `name` comes from the add-on (no user override)."""
    return (not os.path.isfile(widget_path(name))
            and os.path.isfile(bundled_path(name)))


def has_bundled(name):
    return os.path.isfile(bundled_path(name))


def draft_path(name):
    return os.path.join(widgets_folder(),
                        sanitize_name(name) + DRAFT_SUFFIX)


def _json_files(folder):
    if not os.path.isdir(folder):
        return set()
    return {f for f in os.listdir(folder)
            if f.endswith(_EXT) and not f.endswith(DRAFT_SUFFIX)
            and os.path.isfile(os.path.join(folder, f))}


def list_widget_files():
    """Definition file names from the user folder and the bundled
    widgets (one entry per name; resolve with source_path)."""
    return sorted(_json_files(widgets_folder())
                  | _json_files(BUNDLED_FOLDER))


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
    """Delete the user file of `name` (bundled files are never touched)."""
    path = widget_path(name)
    if os.path.isfile(path):
        os.remove(path)
        return True
    return False


def file_name_of(fn):
    """Widget name of a definition file name."""
    return fn[:-len(_EXT)]


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
    # An active edit session on this widget follows the fresh instance.
    from ..ui.widgets import editor
    editor.on_widget_registered(inst)
    return inst, None


def drop_or_restore(name):
    """After `name`'s user file was removed (delete / rename away): show
    the bundled widget again when there is one, else unregister it."""
    if has_bundled(name):
        wdef, _errors = load_def(bundled_path(name))
        if wdef is not None:
            register_composed(wdef)
            return
    unregister_composed(name)


def unregister_composed(name):
    from ..ui import widgets as framework
    from ..ui.widgets import editor
    editor.on_widget_unregistered(name)
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
        path = source_path(file_name_of(fn))
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
    from ..ui.widgets import state
    if state.any_visible():
        state.ensure_draw_handler()
    state.tag_redraw_all()
    return problems


def unregister_all():
    for name in tuple(_live):
        unregister_composed(name)
