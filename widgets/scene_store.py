"""Per-.blend widget data store — composed widgets' scene-persisted values.

Storage lives at ``Scene.IOPS.widget_data``: a CollectionProperty of
per-widget blocks keyed (RNA ``.name``) by widget name, each holding
``entries`` — KV items keyed by data key with a string ``value``
(properties defined in prefs/addon_properties.py). Values are strings;
interpretation is DECLARED by the bound control's value_type — see the
adapters below and composed._coerce/_to_display.

getattr-only + RNA-collection get/add/remove/clear — no bpy import, so
the module stays pytest-importable with fake collections (same policy
as widgets/composed.py). Every access is defensive: a missing
Scene.IOPS / widget_data (addon half-registered) degrades to
default/no-op.
"""
import math


def _store(context):
    """The scene's widget_data collection, or None when unavailable."""
    iops = getattr(getattr(context, "scene", None), "IOPS", None)
    return getattr(iops, "widget_data", None)


def get(context, widget, key, default=None):
    """Raw stored string for (widget, key); `default` when the block or
    entry does not exist (or the store itself is missing)."""
    store = _store(context)
    if store is None:
        return default
    block = store.get(str(widget))
    if block is None:
        return default
    entry = block.entries.get(str(key))
    if entry is None:
        return default
    return entry.value


def set_value(context, widget, key, value):
    """Store str(value) under (widget, key), creating the block/entry
    lazily. No-op when the store is missing."""
    store = _store(context)
    if store is None:
        return
    widget, key = str(widget), str(key)
    block = store.get(widget)
    if block is None:
        block = store.add()
        block.name = widget
    entry = block.entries.get(key)
    if entry is None:
        entry = block.entries.add()
        entry.name = key
    entry.value = str(value)


def delete(context, widget, key):
    """Remove one entry. True if it existed."""
    store = _store(context)
    if store is None:
        return False
    block = store.get(str(widget))
    if block is None:
        return False
    key = str(key)
    for i, entry in enumerate(block.entries):
        if entry.name == key:
            block.entries.remove(i)
            return True
    return False


def purge(context, widget=None):
    """Remove one widget's block (`widget` given) or every block
    (`widget` None). Returns the number of blocks removed."""
    store = _store(context)
    if store is None:
        return 0
    if widget is None:
        count = len(store)
        store.clear()
        return count
    widget = str(widget)
    for i, block in enumerate(store):
        if block.name == widget:
            store.remove(i)
            return 1
    return 0


# ----------------------------------------------------------------------
# Control adapters — the {"get", "set"} bundles composed.build_controls
# wires into Dropdown/InputField/ButtonGroup/FlipBox for `data` rows.
# get(context) -> (value, is_mixed); scalar binding, is_mixed always
# False. Author/display space per the DECLARED value_type, exactly like
# composed.rna_value_adapter (DEGREES authors degrees, stores radians).
# ----------------------------------------------------------------------
_TYPE_DEFAULTS = {"STRING": "", "ENUM": "", "INT": 0,
                  "FLOAT": 0.0, "DEGREES": 0.0, "RADIANS": 0.0}


def store_value_adapter(widget, key, value_type="STRING"):
    """get/set bundle for a scene-stored scalar. Missing block/entry
    means "not set yet" -> the type's default with the control ENABLED
    (unlike a broken RNA prop path); only a missing store itself returns
    (None, False) -> disabled."""
    from .composed import _coerce
    default = _TYPE_DEFAULTS.get(value_type, "")

    def _get(context):
        if _store(context) is None:
            return (None, False)
        raw = get(context, widget, key)
        if raw is None:
            return (default, False)
        try:
            if value_type == "INT":
                return (int(float(raw)), False)
            if value_type in ("FLOAT", "RADIANS"):
                return (float(raw), False)
            if value_type == "DEGREES":
                return (math.degrees(float(raw)), False)
        except (TypeError, ValueError):
            return (default, False)
        return (raw, False)                      # STRING / ENUM

    def _set(context, value):
        try:
            stored = _coerce(value_type, value)
        except (TypeError, ValueError):
            return
        set_value(context, widget, key, stored)

    return {"get": _get, "set": _set}


def store_bool_adapter(widget, key):
    """get/set bundle for a scene-stored bool (FLIPBOX `data` binding).
    Stored as "1"/"0"; unset -> False, enabled."""
    def _get(context):
        if _store(context) is None:
            return (None, False)
        raw = get(context, widget, key)
        if raw is None:
            return (False, False)
        return (raw == "1", False)

    def _set(context, value):
        set_value(context, widget, key, "1" if value else "0")

    return {"get": _get, "set": _set}
