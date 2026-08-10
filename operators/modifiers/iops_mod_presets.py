"""Default-preset storage for the modifiers grid.

Defaults live in editable PropertyGroups on the addon preferences
(iops_mod_defaults.py) — one group per modifier type, persisted by
Blender in userpref.blend. This module keeps the stable API
(load_default / save_default / clear_default) plus snapshot().

Legacy storage was a JSON file
(<user scripts>/presets/IOPS/iops_mod_presets.json); it is migrated
into the groups once by the grid seed timer and renamed *.migrated.
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

# Per-type skips: RNA aliases sharing one internal value — applying the
# second alias clobbers the first (Bevel width/width_pct in 5.2).
_TYPE_SKIP_PROPS = {
    "BEVEL": {"width_pct"},
}


def _presets_path():
    return os.path.join(bpy.utils.script_path_user(),
                        "presets", "IOPS", "iops_mod_presets.json")


def _read_legacy():
    """Read the legacy JSON preset file (migration only)."""
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


def _group(mod_type):
    from . import iops_mod_defaults as defaults
    prefs = bpy.context.preferences.addons["InteractionOps"].preferences
    return defaults.get_group(prefs, mod_type)


def snapshot(md):
    """Serializable, writable props of a modifier as a plain dict."""
    out = {}
    type_skip = _TYPE_SKIP_PROPS.get(md.type, ())
    for p in md.bl_rna.properties:
        pid = p.identifier
        if (p.is_readonly or pid in _SKIP_PROPS or pid in type_skip
                or p.type == "POINTER"):
            continue
        value = getattr(md, pid)
        if p.type == "ENUM":
            value = sorted(value) if p.is_enum_flag else value
        elif p.type in {"FLOAT", "INT", "BOOLEAN"} and p.is_array:
            value = list(value)
        elif p.type not in {"FLOAT", "INT", "BOOLEAN", "STRING"}:
            continue
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            continue  # exotic/non-round-trippable value (e.g. matrix-typed
                      # float arrays on some modifiers) — skip it
        out[pid] = value
    return out


def load_default(mod_type):
    """The type's default settings as a dict, or None (no group —
    Blender defaults apply)."""
    from . import iops_mod_defaults as defaults
    group = _group(mod_type)
    return defaults.group_values(group) if group is not None else None


def save_default(md):
    """Copy md's current settings into its type's defaults group."""
    from . import iops_mod_defaults as defaults
    group = _group(md.type)
    if group is None:
        return False
    defaults.set_group_values(group, snapshot(md))
    return True


def clear_default(mod_type):
    """Reset the type's defaults group to its definition defaults
    (Blender defaults + baked-in smart defaults)."""
    from . import iops_mod_defaults as defaults
    group = _group(mod_type)
    if group is None:
        return False
    defaults.reset_group(group)
    return True


def migrate_legacy_json(prefs):
    """One-shot: pour the legacy JSON preset file into the defaults
    groups and rename the file. Called from the grid seed timer."""
    from . import iops_mod_defaults as defaults
    legacy = _read_legacy()
    if not legacy:
        return
    for mod_type, settings in legacy.items():
        group = defaults.get_group(prefs, mod_type)
        if group is not None and isinstance(settings, dict):
            defaults.set_group_values(group, settings)
    path = _presets_path()
    try:
        os.replace(path, path + ".migrated")
        print("IOPS modifiers: legacy preset json migrated to prefs")
    except OSError as e:
        print(f"IOPS modifiers: could not rename legacy preset json ({e})")
