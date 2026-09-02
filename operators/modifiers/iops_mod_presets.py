"""Default-preset storage for the modifiers grid.

Defaults live per grid SLOT: every IOPS_ModGridItem carries one
editable PropertyGroup per modifier type (iops_mod_defaults.py), and
the group matching the slot's mod_type holds that slot's settings. So
two slots of the same type (e.g. two Bevels) keep independent
defaults. Blender persists them in userpref.blend.

Legacy storage, migrated once by the grid seed timer:
  * one group per type on the addon preferences (pre-slot layout) —
    poured into the first slot of that type, then reset;
  * a JSON file (<user scripts>/presets/IOPS/iops_mod_presets.json) —
    poured into the first slot of that type, renamed *.migrated.
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


def _prefs():
    return bpy.context.preferences.addons["InteractionOps"].preferences


# --- slot lookup -------------------------------------------------------

def slots_of_type(prefs, mod_type):
    """[(index, item)] for every grid slot of this modifier type."""
    return [(i, it) for i, it in enumerate(prefs.modifiers_grid_items)
            if it.mod_type == mod_type]


def first_slot_of_type(prefs, mod_type):
    slots = slots_of_type(prefs, mod_type)
    return slots[0][1] if slots else None


def slot_group(item):
    """The slot's defaults group (the one matching its mod_type), or
    None when the type has no editable params."""
    from . import iops_mod_defaults as defaults
    return defaults.get_group(item, item.mod_type)


def slot_settings(item):
    """The slot's default settings as a dict, or None (no group —
    Blender defaults apply)."""
    from . import iops_mod_defaults as defaults
    group = slot_group(item)
    return defaults.group_values(group) if group is not None else None


def slot_label(item):
    """User label if set, else the type's display name."""
    if item.label:
        return item.label
    from .iops_mod_registry import all_mod_type_items
    for ident, name, _icon in all_mod_type_items():
        if ident == item.mod_type:
            return name
    return item.mod_type.title().replace("_", " ")


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


# --- stable API ---------------------------------------------------------

def load_default(mod_type):
    """Settings of the FIRST grid slot of this type, or None. Callers
    that know their slot should use slot_settings(item) instead."""
    item = first_slot_of_type(_prefs(), mod_type)
    return slot_settings(item) if item is not None else None


def save_default(md, item):
    """Copy md's current settings into the given slot's defaults."""
    from . import iops_mod_defaults as defaults
    if item.mod_type != md.type:
        return False
    group = slot_group(item)
    if group is None:
        return False
    defaults.set_group_values(group, snapshot(md))
    return True


def clear_default(item):
    """Reset the slot's defaults group to its definition defaults
    (Blender defaults + baked-in smart defaults)."""
    from . import iops_mod_defaults as defaults
    group = slot_group(item)
    if group is None:
        return False
    defaults.reset_group(group)
    return True


# --- migrations ----------------------------------------------------------

def migrate_type_groups_to_slots(prefs):
    """One-shot: pour the pre-slot per-type groups living on the addon
    preferences into the first slot of each type, then reset them so
    the migration is a no-op afterwards. Called from the grid seed
    timer (after the list is seeded)."""
    from . import iops_mod_defaults as defaults
    moved = 0
    for ident in defaults.GROUPS_BY_TYPE:
        legacy = defaults.get_group(prefs, ident)
        if legacy is None:
            continue
        keys = [k for k in type(legacy).__annotations__
                if legacy.is_property_set(k)]
        if not keys:
            continue
        item = first_slot_of_type(prefs, ident)
        if item is not None:
            group = slot_group(item)
            if group is not None:
                defaults.set_group_values(
                    group, {k: defaults.group_values(legacy)[k]
                            for k in keys})
                moved += 1
        defaults.reset_group(legacy)
    if moved:
        print(f"IOPS modifiers: {moved} per-type default group(s) "
              "migrated to grid slots")


def migrate_legacy_json(prefs):
    """One-shot: pour the legacy JSON preset file into the first slot
    of each type and rename the file. Called from the grid seed timer."""
    from . import iops_mod_defaults as defaults
    legacy = _read_legacy()
    if not legacy:
        return
    for mod_type, settings in legacy.items():
        item = first_slot_of_type(prefs, mod_type)
        group = slot_group(item) if item is not None else None
        if group is not None and isinstance(settings, dict):
            defaults.set_group_values(group, settings)
    path = _presets_path()
    try:
        os.replace(path, path + ".migrated")
        print("IOPS modifiers: legacy preset json migrated to prefs")
    except OSError as e:
        print(f"IOPS modifiers: could not rename legacy preset json ({e})")
