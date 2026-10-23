"""Pure (bpy-free) field helpers for the widget editor N-panel.

Which fields a selected element shows (per type, binding and value
type), how a binding switch rewrites the element, and the short text
formats the panel uses for list/dict schema fields:

    items     "ID:Label, ID2"            -> [["ID", "Label"], "ID2"]
    labels    "ID=Label; ID2=Label"      -> {"ID": "Label", "ID2": "Label"}
    switches  "name=1, other=0"          -> {"name": True, "other": False}
    numbers   "0, 0.5, 1"                -> [0.0, 0.5, 1.0]  (unclamped)
    list      "EDIT_MESH, OBJECT"        -> ["EDIT_MESH", "OBJECT"]
"""
import json

# Relative for Blender (addon loads as package InteractionOps); absolute
# fallback for pytest (same pattern as editor_model).
try:
    from ...widgets import composed
except ImportError:
    from widgets import composed

# Binding choices per element type, first = default for a fresh switch.
BINDINGS = {
    "SLIDER": ("TARGET", "PROP"),
    "PRESETS": ("TARGET",),
    "FLIPBOX": ("TARGET", "PROP", "SWITCH", "DATA"),
    "DROPDOWN": ("PROP", "DATA"),
    "INPUT": ("PROP", "DATA"),
    "BUTTONS": ("PROP", "DATA"),
    "SWATCH": ("COLOR", "PROP"),
}
BINDING_KEYS = {"TARGET": "target", "PROP": "prop", "SWITCH": "switch",
                "DATA": "data", "COLOR": "color"}

_SLIDER_VALUE_TYPES = ("INT", "FLOAT", "DEGREES", "RADIANS")
_TRUE = ("1", "true", "on", "yes")
_FALSE = ("0", "false", "off", "no")


# ----------------------------------------------------------------------
# Per-type field layout
# ----------------------------------------------------------------------
def bindings_for(rtype):
    return BINDINGS.get(str(rtype).upper(), ())


def binding_of(el):
    """The element's current binding id ("" for unbound types)."""
    choices = bindings_for(el.get("type", ""))
    for b in choices:
        key = BINDING_KEYS[b]
        if key == "color":
            if el.get("color") is not None:
                return b
        elif str(el.get(key, "")).strip():
            return b
    for b in choices:          # present but empty (fresh placeholder)
        if BINDING_KEYS[b] in el:
            return b
    return choices[0] if choices else ""


def apply_binding(el, binding, value):
    """Switch `el` to `binding` with `value`, dropping the other binding
    keys of its type. Returns True when `el` changed. Pure mutation."""
    choices = bindings_for(el.get("type", ""))
    if binding not in choices:
        return False
    before = json.dumps(el, sort_keys=True, default=str)
    for b in choices:
        if b != binding:
            el.pop(BINDING_KEYS[b], None)
    el[BINDING_KEYS[binding]] = value
    return json.dumps(el, sort_keys=True, default=str) != before


def targets_for(rtype):
    rtype = str(rtype).upper()
    if rtype in ("SLIDER", "PRESETS"):
        return composed.FLOAT_TARGETS
    if rtype == "FLIPBOX":
        return composed.BOOL_TARGETS
    return ()


def value_types_for(rtype):
    rtype = str(rtype).upper()
    if rtype == "SLIDER":
        return _SLIDER_VALUE_TYPES
    if rtype in ("INPUT", "BUTTONS"):
        return composed.VALUE_TYPES
    return ()


def fields_for(el):
    """Ordered panel field names for element `el` (binding/value-type
    aware). Excludes span and show_if (always handled by the caller)."""
    rtype = str(el.get("type", "")).upper()
    binding = binding_of(el)
    vt = str(el.get("value_type", "")).upper()
    out = []
    if rtype == "SECTION":
        out = ["label"]
    elif rtype == "SPACER":
        out = ["height"]
    elif rtype == "BUTTON":
        out = ["label", "op", "op_kwargs", "role"]
    elif rtype == "SLIDER":
        out = ["binding"]
        if binding == "PROP":
            out += ["prop", "value_type", "min", "max", "snap", "fmt"]
        else:
            out += ["target", "snap"]
    elif rtype == "PRESETS":
        out = ["target", "values"]
    elif rtype == "FLIPBOX":
        out = ["label", "binding", BINDING_KEYS.get(binding, "target")]
    elif rtype == "DROPDOWN":
        out = ["label", "binding", BINDING_KEYS.get(binding, "prop"),
               "labels", "items_from"]
    elif rtype == "INPUT":
        out = ["label", "binding", BINDING_KEYS.get(binding, "prop"),
               "value_type", "fmt"]
    elif rtype == "BUTTONS":
        out = ["binding", BINDING_KEYS.get(binding, "prop"), "value_type",
               "fmt"]
        out += ["items"] if vt == "ENUM" else ["values", "unit"]
    elif rtype == "SWATCH":
        out = ["label", "binding"]
        out += ["color", "show_alpha"] if binding == "COLOR" else ["prop"]
        out += ["op", "op_kwargs"]
    return out


def span_min(top_level, rtype):
    """Lowest span the panel offers: 0 (= unset, full width) only for a
    top-level non-FLIPBOX row; ROW cells and top-level flipboxes >= 1."""
    return 0 if top_level and str(rtype).upper() != "FLIPBOX" else 1


def has_span(top_level, rtype):
    """ROW containers have no span of their own."""
    return not (top_level and str(rtype).upper() == "ROW")


# ----------------------------------------------------------------------
# Text formats
# ----------------------------------------------------------------------
def _fmt_num(v):
    try:
        return f"{float(v):g}"
    except (TypeError, ValueError):
        return str(v)


def format_numbers(values):
    return ", ".join(_fmt_num(v) for v in (values or []))


def parse_numbers(text):
    """Comma-separated floats, bad tokens skipped, NOT clamped."""
    out = []
    for tok in str(text).split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.append(float(tok))
        except ValueError:
            pass
    return out


def format_items(items):
    parts = []
    for it in items or []:
        if isinstance(it, (list, tuple)):
            if not it:
                continue
            ident = str(it[0])
            parts.append(f"{ident}:{it[1]}" if len(it) >= 2 else ident)
        else:
            parts.append(str(it))
    return ", ".join(parts)


def parse_items(text):
    """"ID:Label, ID2" -> [["ID", "Label"], "ID2"]; empty ids skipped."""
    out = []
    for tok in str(text).split(","):
        ident, sep, label = tok.partition(":")
        ident, label = ident.strip(), label.strip()
        if not ident:
            continue
        out.append([ident, label] if sep and label else ident)
    return out


def format_labels(labels):
    if not isinstance(labels, dict):
        return ""
    return "; ".join(f"{k}={v}" for k, v in labels.items())


def parse_labels(text):
    """"ID=Label; ID2=Label" -> dict; entries without "=" or id skipped."""
    out = {}
    for tok in str(text).split(";"):
        ident, sep, label = tok.partition("=")
        ident = ident.strip()
        if not ident or not sep:
            continue
        out[ident] = label.strip()
    return out


def format_switches(switches):
    if not isinstance(switches, dict):
        return ""
    return ", ".join(f"{k}={1 if v else 0}" for k, v in switches.items())


def parse_switches(text):
    """"name=1, other=0" -> {"name": True, "other": False}. A bare name
    means True; an unrecognized value skips the entry."""
    out = {}
    for tok in str(text).split(","):
        name, sep, val = tok.partition("=")
        name = name.strip()
        if not name:
            continue
        if not sep:
            out[name] = True
            continue
        v = val.strip().lower()
        if v in _TRUE:
            out[name] = True
        elif v in _FALSE:
            out[name] = False
    return out


def format_list(values):
    if isinstance(values, (list, tuple)):
        return ", ".join(str(v) for v in values)
    return "" if values is None else str(values)


def parse_list(text):
    """Comma-separated upper-cased identifiers (show_if mode/object_type)."""
    return [t.strip().upper() for t in str(text).split(",") if t.strip()]


def parse_kwargs(text):
    """op_kwargs JSON text -> (dict, None) or (None, error). Empty text
    is an empty dict."""
    text = str(text).strip()
    if not text:
        return {}, None
    try:
        val = json.loads(text)
    except ValueError as e:
        return None, f"invalid JSON: {e}"
    if not isinstance(val, dict):
        return None, "arguments must be a JSON object"
    return val, None


def format_kwargs(kwargs):
    if not kwargs:
        return ""
    try:
        return json.dumps(kwargs)
    except (TypeError, ValueError):
        return ""


def format_equals(value):
    """show_if `equals` -> text. Strings stay bare unless they would read
    back as JSON (e.g. "1", "true"), then they are quoted."""
    if isinstance(value, str):
        try:
            json.loads(value)
        except ValueError:
            return value
        return json.dumps(value)
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return str(value)


def parse_equals(text):
    """Text -> (present, value): JSON literal when it parses, else the
    raw string. Empty text = absent."""
    text = str(text).strip()
    if not text:
        return False, None
    try:
        return True, json.loads(text)
    except ValueError:
        return True, text


def build_show_if(mode="", object_type="", selection="", prop="",
                  switch="", equals=""):
    """Panel show_if fields -> clause dict, or None when no condition is
    set (empty fields are absent; `equals` alone is not a condition)."""
    out = {}
    modes = parse_list(mode)
    if modes:
        out["mode"] = modes
    types = parse_list(object_type)
    if types:
        out["object_type"] = types
    sel = str(selection).strip().lower()
    if sel in composed.SHOW_IF_SELECTION:
        out["selection"] = sel
    if str(prop).strip():
        out["prop"] = str(prop).strip()
    if str(switch).strip():
        out["switch"] = str(switch).strip()
    if not out:
        return None
    present, value = parse_equals(equals)
    if present and ("prop" in out or "switch" in out):
        out["equals"] = value
    return out


def show_if_fields(show_if):
    """Clause dict -> the six panel text values (inverse of build_show_if)."""
    si = show_if if isinstance(show_if, dict) else {}
    return {
        "si_mode": format_list(si.get("mode")),
        "si_object_type": format_list(si.get("object_type")),
        "si_selection": str(si.get("selection", "") or ""),
        "si_prop": str(si.get("prop", "") or ""),
        "si_switch": str(si.get("switch", "") or ""),
        "si_equals": format_equals(si["equals"]) if "equals" in si else "",
    }
