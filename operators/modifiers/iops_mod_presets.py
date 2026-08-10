"""Default-preset storage for the modifiers grid.

One optional 'default preset' per modifier type, stored as JSON next to
the other IOPS presets: <user scripts>/presets/IOPS/iops_mod_presets.json
Shape: {"BEVEL": {"width": 0.05, ...}, ...} — serializable props only.
"""

import bpy
import json
import os

_SKIP_PROPS = {
    "name", "type", "show_expanded", "is_active", "show_in_editmode",
    "show_viewport", "show_render", "show_on_cage", "use_pin_to_last",
    "is_override_data", "use_apply_on_spline", "execution_time",
    "persistent_uid",
}


def _presets_path():
    return os.path.join(bpy.utils.script_path_user(),
                        "presets", "IOPS", "iops_mod_presets.json")


def _read_all():
    path = _presets_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        print(f"IOPS modifiers: preset file unreadable ({e}), ignoring")
        return {}


def _write_all(data):
    path = _presets_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def snapshot(md):
    """Serializable, writable props of a modifier as a plain dict."""
    out = {}
    for p in md.bl_rna.properties:
        pid = p.identifier
        if p.is_readonly or pid in _SKIP_PROPS or p.type == "POINTER":
            continue
        value = getattr(md, pid)
        if p.type == "ENUM":
            value = sorted(value) if p.is_enum_flag else value
        elif p.type in {"FLOAT", "INT", "BOOLEAN"} and p.is_array:
            value = list(value)
        elif p.type not in {"FLOAT", "INT", "BOOLEAN", "STRING"}:
            continue
        out[pid] = value
    return out


def load_default(mod_type):
    return _read_all().get(mod_type)


def save_default(md):
    data = _read_all()
    data[md.type] = snapshot(md)
    _write_all(data)


def clear_default(mod_type):
    data = _read_all()
    if mod_type in data:
        del data[mod_type]
        _write_all(data)
        return True
    return False
