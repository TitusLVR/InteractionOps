# Widget Scene Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generic per-.blend data storage for composed widgets: `Scene.IOPS.widget_data` store, `widgets/scene_store.py` API + adapters, `"data"` schema binding, purge operator.

**Architecture:** RNA CollectionProperty on `Scene.IOPS` holds per-widget blocks of string KV entries (keyed by RNA `.name`). A bpy-free `scene_store` module (getattr-only, like `composed.py`) provides get/set/delete/purge plus adapter bundles in the existing `{"get", "set"}` shape. `composed.py` validation accepts `data: "<key>"` as a `prop` alternative on FLIPBOX/DROPDOWN/INPUT/BUTTONS; `build_controls` routes those rows to store adapters scoped by widget name.

**Tech Stack:** Blender 5.x Python addon (`bpy`), pytest for the pure logic (repo pattern: bpy-free modules tested with fakes, see `tests/ui/widgets/test_composed.py`).

**Spec:** `docs/superpowers/specs/2026-07-09-widget-scene-store-design.md`

## Global Constraints

- NO widget migration: `operators/uv_image_slots.py` and all existing widget JSONs are untouched.
- Values stored as strings; interpretation declared by `value_type` — never introspected.
- Missing block/entry = "not set yet" → type default, control ENABLED. Missing `Scene.IOPS.widget_data` (framework unregistered) → `(None, False)` → control disabled.
- `widgets/scene_store.py` must import cleanly without bpy (getattr-only), same as `widgets/composed.py`.
- Run pure tests with `python -m pytest tests/ui/widgets/ -v` from repo root.
- Live verification: Blender 5.1 with the addon symlinked at `B:` — reload addon, then check via Blender MCP `execute_blender_code`.
- Repo is public: no CCP mentions in commits or code.

---

### Task 1: `widgets/scene_store.py` — store API (get/set/delete/purge)

**Files:**
- Create: `widgets/scene_store.py`
- Test: `tests/ui/widgets/test_scene_store.py`

**Interfaces:**
- Consumes: nothing (getattr-only walking of `context.scene.IOPS.widget_data`).
- Produces:
  - `get(context, widget, key, default=None) -> str|None` — raw stored string
  - `set_value(context, widget, key, value) -> None` — lazy creation, stores `str(value)`
  - `delete(context, widget, key) -> bool`
  - `purge(context, widget=None) -> int` — blocks removed
  - NOTE: the setter is named `set_value` (module-level `set` would shadow the builtin and reads badly at call sites: `scene_store.set_value(...)`). `get` keeps its natural name.

- [ ] **Step 1: Write the failing tests**

Create `tests/ui/widgets/test_scene_store.py`:

```python
"""Pure-logic tests for widgets/scene_store.py — the per-.blend widget
data store. No bpy: the module is getattr-only, so fake RNA collections
(name-keyed, add/remove/clear) stand in for the real thing."""
import importlib
import os
import sys

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__),
                                      "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

scene_store = importlib.import_module("widgets.scene_store")


# ----------------------------------------------------------------------
# Fakes emulating RNA CollectionProperty behavior
# ----------------------------------------------------------------------
class FakeCollection:
    def __init__(self, factory):
        self._items = []
        self._factory = factory

    def get(self, name):
        return next((it for it in self._items if it.name == name), None)

    def add(self):
        it = self._factory()
        self._items.append(it)
        return it

    def remove(self, index):
        self._items.pop(index)

    def clear(self):
        self._items.clear()

    def __len__(self):
        return len(self._items)

    def __iter__(self):
        return iter(self._items)


class FakeEntry:
    def __init__(self):
        self.name = ""
        self.value = ""


class FakeBlock:
    def __init__(self):
        self.name = ""
        self.entries = FakeCollection(FakeEntry)


class FakeIOPS:
    def __init__(self):
        self.widget_data = FakeCollection(FakeBlock)


class FakeScene:
    def __init__(self):
        self.IOPS = FakeIOPS()


class FakeContext:
    def __init__(self):
        self.scene = FakeScene()


class BareContext:
    """Context whose scene has no IOPS (addon half-registered)."""
    def __init__(self):
        self.scene = object()


# ----------------------------------------------------------------------
# get / set_value
# ----------------------------------------------------------------------
def test_get_missing_returns_default():
    ctx = FakeContext()
    assert scene_store.get(ctx, "w", "k") is None
    assert scene_store.get(ctx, "w", "k", default="d") == "d"


def test_set_then_get_roundtrip():
    ctx = FakeContext()
    scene_store.set_value(ctx, "w", "k", "hello")
    assert scene_store.get(ctx, "w", "k") == "hello"


def test_set_coerces_to_str():
    ctx = FakeContext()
    scene_store.set_value(ctx, "w", "n", 42)
    assert scene_store.get(ctx, "w", "n") == "42"


def test_set_overwrites_existing_entry_no_duplicates():
    ctx = FakeContext()
    scene_store.set_value(ctx, "w", "k", "a")
    scene_store.set_value(ctx, "w", "k", "b")
    assert scene_store.get(ctx, "w", "k") == "b"
    block = ctx.scene.IOPS.widget_data.get("w")
    assert len(block.entries) == 1


def test_widgets_do_not_collide():
    ctx = FakeContext()
    scene_store.set_value(ctx, "w1", "k", "a")
    scene_store.set_value(ctx, "w2", "k", "b")
    assert scene_store.get(ctx, "w1", "k") == "a"
    assert scene_store.get(ctx, "w2", "k") == "b"


def test_missing_store_degrades():
    ctx = BareContext()
    scene_store.set_value(ctx, "w", "k", "x")   # no-op, no raise
    assert scene_store.get(ctx, "w", "k", default="d") == "d"


# ----------------------------------------------------------------------
# delete / purge
# ----------------------------------------------------------------------
def test_delete_entry():
    ctx = FakeContext()
    scene_store.set_value(ctx, "w", "k", "x")
    assert scene_store.delete(ctx, "w", "k") is True
    assert scene_store.get(ctx, "w", "k") is None
    assert scene_store.delete(ctx, "w", "k") is False
    assert scene_store.delete(ctx, "nope", "k") is False


def test_purge_one_widget():
    ctx = FakeContext()
    scene_store.set_value(ctx, "w1", "k", "a")
    scene_store.set_value(ctx, "w2", "k", "b")
    assert scene_store.purge(ctx, "w1") == 1
    assert scene_store.get(ctx, "w1", "k") is None
    assert scene_store.get(ctx, "w2", "k") == "b"
    assert scene_store.purge(ctx, "w1") == 0


def test_purge_all():
    ctx = FakeContext()
    scene_store.set_value(ctx, "w1", "k", "a")
    scene_store.set_value(ctx, "w2", "k", "b")
    assert scene_store.purge(ctx) == 2
    assert len(ctx.scene.IOPS.widget_data) == 0


def test_purge_missing_store_returns_zero():
    assert scene_store.purge(BareContext()) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/ui/widgets/test_scene_store.py -v`
Expected: collection ERROR — `ModuleNotFoundError: No module named 'widgets.scene_store'`

- [ ] **Step 3: Write the implementation**

Create `widgets/scene_store.py`:

```python
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
```

(`import math` is used by Task 2's adapters; keeping it now avoids touching the header twice.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/ui/widgets/test_scene_store.py -v`
Expected: all PASS

- [ ] **Step 5: Run the full pure suite (no regressions)**

Run: `python -m pytest tests/ -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add widgets/scene_store.py tests/ui/widgets/test_scene_store.py
git commit -m "feat(widgets): scene_store — per-.blend widget data API"
```

---

### Task 2: `scene_store` adapters (store_value_adapter, store_bool_adapter)

**Files:**
- Modify: `widgets/scene_store.py` (append)
- Test: `tests/ui/widgets/test_scene_store.py` (append)

**Interfaces:**
- Consumes: Task 1's `get`/`set_value`/`_store`; `composed._coerce` (author→storage conversion, `widgets/composed.py:222`).
- Produces:
  - `store_value_adapter(widget, key, value_type="STRING") -> {"get": fn, "set": fn}` — get returns `(author_space_value, False)`; missing entry → type default; missing store → `(None, False)`.
  - `store_bool_adapter(widget, key) -> {"get": fn, "set": fn}` — stores `"1"`/`"0"`; missing entry → `(False, False)`; missing store → `(None, False)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/ui/widgets/test_scene_store.py`:

```python
# ----------------------------------------------------------------------
# Adapters
# ----------------------------------------------------------------------
import math


def test_value_adapter_string_roundtrip():
    ctx = FakeContext()
    ad = scene_store.store_value_adapter("w", "note", "STRING")
    assert ad["get"](ctx) == ("", False)          # unset -> default, enabled
    ad["set"](ctx, "hello")
    assert ad["get"](ctx) == ("hello", False)


def test_value_adapter_int():
    ctx = FakeContext()
    ad = scene_store.store_value_adapter("w", "n", "INT")
    assert ad["get"](ctx) == (0, False)
    ad["set"](ctx, 3)
    assert ad["get"](ctx) == (3, False)
    assert scene_store.get(ctx, "w", "n") == "3"  # stored as string


def test_value_adapter_float():
    ctx = FakeContext()
    ad = scene_store.store_value_adapter("w", "f", "FLOAT")
    ad["set"](ctx, 1.5)
    assert ad["get"](ctx) == (1.5, False)


def test_value_adapter_degrees_stores_radians():
    ctx = FakeContext()
    ad = scene_store.store_value_adapter("w", "a", "DEGREES")
    ad["set"](ctx, 90.0)                           # author space: degrees
    stored = float(scene_store.get(ctx, "w", "a"))
    assert stored == pytest.approx(math.pi / 2)    # storage space: radians
    value, mixed = ad["get"](ctx)
    assert value == pytest.approx(90.0)            # back to degrees
    assert mixed is False


def test_value_adapter_enum_behaves_as_string():
    ctx = FakeContext()
    ad = scene_store.store_value_adapter("w", "e", "ENUM")
    ad["set"](ctx, "OPTION_A")
    assert ad["get"](ctx) == ("OPTION_A", False)


def test_value_adapter_unparseable_returns_default():
    ctx = FakeContext()
    scene_store.set_value(ctx, "w", "n", "garbage")
    ad = scene_store.store_value_adapter("w", "n", "INT")
    assert ad["get"](ctx) == (0, False)


def test_value_adapter_missing_store_disabled():
    ctx = BareContext()
    ad = scene_store.store_value_adapter("w", "k", "STRING")
    assert ad["get"](ctx) == (None, False)         # disabled
    ad["set"](ctx, "x")                            # no-op, no raise


def test_bool_adapter():
    ctx = FakeContext()
    ad = scene_store.store_bool_adapter("w", "flag")
    assert ad["get"](ctx) == (False, False)        # unset -> False, enabled
    ad["set"](ctx, True)
    assert ad["get"](ctx) == (True, False)
    assert scene_store.get(ctx, "w", "flag") == "1"
    ad["set"](ctx, False)
    assert ad["get"](ctx) == (False, False)
    assert scene_store.get(ctx, "w", "flag") == "0"


def test_bool_adapter_missing_store_disabled():
    assert scene_store.store_bool_adapter("w", "k")["get"](BareContext()) \
        == (None, False)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/ui/widgets/test_scene_store.py -v`
Expected: new tests FAIL with `AttributeError: ... has no attribute 'store_value_adapter'`; Task 1 tests still PASS.

- [ ] **Step 3: Write the implementation**

Append to `widgets/scene_store.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/ui/widgets/test_scene_store.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add widgets/scene_store.py tests/ui/widgets/test_scene_store.py
git commit -m "feat(widgets): scene_store adapters for data-bound controls"
```

---

### Task 3: Schema validation — `data` binding in `composed._clean_row_body`

**Files:**
- Modify: `widgets/composed.py` (FLIPBOX ~line 362, DROPDOWN ~line 395, INPUT ~line 409, BUTTONS ~line 421 inside `_clean_row_body`)
- Test: `tests/ui/widgets/test_composed.py` (append)

**Interfaces:**
- Consumes: existing `_clean_row_body` / `validate_def`.
- Produces: validated row dicts carry `"data": "<key>"` (mutually exclusive with `prop`/`target`/`switch`); Task 4 consumes `row.get("data")`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/ui/widgets/test_composed.py`:

```python
# ----------------------------------------------------------------------
# `data` binding (scene store)
# ----------------------------------------------------------------------
@pytest.mark.parametrize("row", [
    {"type": "FLIPBOX", "data": "flag", "label": "Flag"},
    {"type": "DROPDOWN", "data": "slot_0", "items_from": "uv_images"},
    {"type": "INPUT", "data": "note", "value_type": "STRING"},
    {"type": "BUTTONS", "data": "level", "value_type": "INT",
     "values": [1, 2, 3]},
])
def test_data_binding_accepted(row):
    out, err = composed._clean_row_body(row)
    assert err is None
    assert out["data"] == row["data"]
    assert "prop" not in out


@pytest.mark.parametrize("row", [
    {"type": "FLIPBOX", "data": "flag", "prop": "scene.x"},
    {"type": "FLIPBOX", "data": "flag", "switch": "s"},
    {"type": "FLIPBOX", "data": "flag", "target": "SHARP"},
    {"type": "DROPDOWN", "data": "slot_0", "prop": "scene.x"},
    {"type": "INPUT", "data": "note", "prop": "scene.x"},
    {"type": "BUTTONS", "data": "level", "prop": "scene.x",
     "values": [1]},
])
def test_data_plus_other_binding_rejected(row):
    out, err = composed._clean_row_body(row)
    assert out is None


@pytest.mark.parametrize("row", [
    {"type": "FLIPBOX", "data": "  "},
    {"type": "DROPDOWN", "data": ""},
    {"type": "INPUT", "data": " "},
    {"type": "BUTTONS", "data": "", "values": [1]},
])
def test_blank_data_rejected(row):
    out, err = composed._clean_row_body(row)
    assert out is None


def test_data_label_defaults_to_key():
    out, _ = composed._clean_row_body({"type": "INPUT", "data": "note"})
    assert out["label"] == "note"
    out, _ = composed._clean_row_body({"type": "FLIPBOX", "data": "flag"})
    assert out["label"] == "flag"
    out, _ = composed._clean_row_body(
        {"type": "DROPDOWN", "data": "slot_0"})
    assert out["label"] == "slot_0"


def test_data_dropdown_keeps_forced_enum_and_items_from():
    out, err = composed._clean_row_body(
        {"type": "DROPDOWN", "data": "slot_0", "items_from": "uv_images"})
    assert err is None
    assert out["value_type"] == "ENUM"
    assert out["items_from"] == "uv_images"


def test_prop_rows_unchanged():
    out, err = composed._clean_row_body(
        {"type": "INPUT", "prop": "scene.IOPS.rename.new_name"})
    assert err is None
    assert out["prop"] == "scene.IOPS.rename.new_name"
    assert "data" not in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/ui/widgets/test_composed.py -v -k data`
Expected: FAIL — `data` rows currently rejected ("dropdown needs a prop...") or `data` key absent from output.

- [ ] **Step 3: Implement validation changes**

In `widgets/composed.py` `_clean_row_body`, replace the four binding sections:

FLIPBOX (currently lines 362–380):

```python
    if rtype == "FLIPBOX":
        prop = str(row.get("prop", "")).strip()
        target = str(row.get("target", "")).strip().upper()
        switch = str(row.get("switch", "")).strip()
        data = str(row.get("data", "")).strip()
        bound = [b for b in (prop, target, switch, data) if b]
        if len(bound) != 1:
            return None, ("flipbox needs exactly one of"
                          " prop/target/switch/data")
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
            if target not in BOOL_TARGETS:
                return None, f"flipbox target '{target}' invalid"
            out["target"] = target
            out["label"] = str(row.get("label", "")) or target.title()
        return out, None
```

NOTE: `"data": "  "` strips to empty → `bound` is empty → `len != 1` → rejected. That covers the blank-data test for FLIPBOX; the other three need their own explicit check (below).

DROPDOWN (currently lines 395–408) — replace the `prop` handling:

```python
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
```

(A row with NEITHER prop nor data — including blank data — hits `bool("") == bool("")` → rejected. Same logic covers INPUT/BUTTONS.)

INPUT (currently lines 409–420) — replace the `prop` handling; the rest (value_type, fmt) is unchanged:

```python
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
```

BUTTONS (currently lines 421–475) — replace ONLY the first four lines of the branch (prop extraction and check); everything from `vt = ...` down is unchanged:

```python
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
        # ... rest of the branch unchanged ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/ui/widgets/test_composed.py -v`
Expected: all PASS (new + pre-existing)

- [ ] **Step 5: Run the full pure suite**

Run: `python -m pytest tests/ -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add widgets/composed.py tests/ui/widgets/test_composed.py
git commit -m "feat(widgets): 'data' scene-store binding in widget schema validation"
```

---

### Task 4: Control building — route `data` rows to store adapters

**Files:**
- Modify: `widgets/composed.py` (`build_controls` line 613, its `one()` closure, `make_widget` line 734)
- Test: `tests/ui/widgets/test_composed.py` (append)

**Interfaces:**
- Consumes: Task 2's `scene_store.store_value_adapter` / `store_bool_adapter`; Task 3's validated `data` rows.
- Produces: `build_controls(row_defs, switch_store=None, on_switch=None, widget_name="")`; controls whose get/set read/write the scene store scoped to `widget_name`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/ui/widgets/test_composed.py` (the FakeContext fakes mirror
`tests/ui/widgets/test_scene_store.py`; import them rather than redefining):

```python
# ----------------------------------------------------------------------
# build_controls with `data` rows (scene-store routing)
# ----------------------------------------------------------------------
from tests.ui.widgets.test_scene_store import FakeContext


def test_build_controls_data_input_roundtrip():
    rows, errors = composed.validate_def({
        "name": "demo_w",
        "rows": [{"type": "INPUT", "data": "note",
                  "value_type": "STRING"}],
    })
    assert not errors
    controls = composed.build_controls(rows["rows"], widget_name="demo_w")
    assert len(controls) == 1
    ctrl = controls[0]
    ctx = FakeContext()
    assert ctrl.get(ctx) == ("", False)            # unset -> default, enabled
    ctrl.set(ctx, "hello")
    assert ctrl.get(ctx) == ("hello", False)
    # scoped to the widget's own block
    block = ctx.scene.IOPS.widget_data.get("demo_w")
    assert block.entries.get("note").value == "hello"


def test_build_controls_data_flipbox_bool():
    rows, _ = composed.validate_def({
        "name": "demo_w",
        "rows": [{"type": "FLIPBOX", "data": "flag", "label": "Flag"}],
    })
    controls = composed.build_controls(rows["rows"], widget_name="demo_w")
    ctx = FakeContext()
    ctrl = controls[0]
    assert ctrl.get(ctx) == (False, False)
    ctrl.set(ctx, True)
    assert ctrl.get(ctx) == (True, False)
    assert ctx.scene.IOPS.widget_data.get("demo_w") \
              .entries.get("flag").value == "1"


def test_build_controls_data_dropdown_uses_provider_and_empty_fallback():
    composed.register_dropdown_items(
        "test_items", lambda context: [("A", "Option A"), ("B", "Option B")])
    try:
        rows, _ = composed.validate_def({
            "name": "demo_w",
            "rows": [
                {"type": "DROPDOWN", "data": "slot", "items_from": "test_items"},
                {"type": "DROPDOWN", "data": "bare"},   # no items_from
            ],
        })
        controls = composed.build_controls(rows["rows"],
                                           widget_name="demo_w")
        ctx = FakeContext()
        assert controls[0].items_get(ctx) == [("A", "Option A"),
                                              ("B", "Option B")]
        assert controls[1].items_get(ctx) == []        # empty fallback
        controls[0].set(ctx, "B")
        assert controls[0].get(ctx) == ("B", False)
    finally:
        composed.unregister_dropdown_items("test_items")


def test_build_controls_data_buttons():
    rows, _ = composed.validate_def({
        "name": "demo_w",
        "rows": [{"type": "BUTTONS", "data": "level", "value_type": "INT",
                  "values": [1, 2, 3]}],
    })
    controls = composed.build_controls(rows["rows"], widget_name="demo_w")
    ctx = FakeContext()
    controls[0].set(ctx, 2)
    assert controls[0].get(ctx) == (2, False)


def test_data_rows_do_not_bind_edges():
    rows, _ = composed.validate_def({
        "name": "demo_w",
        "rows": [{"type": "INPUT", "data": "note"}],
    })
    assert composed._binds_edges(rows["rows"]) is False
```

NOTE: if `Dropdown`/`InputField`/`FlipBox`/`ButtonGroup` don't expose `get`/`set`/`items_get` as attributes, adapt assertions to the controls' real attribute names (check `ui/widgets/controls.py`) — the intent is: the control's bound getter/setter round-trips through the fake scene store.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/ui/widgets/test_composed.py -v -k build_controls_data`
Expected: FAIL — `build_controls() got an unexpected keyword argument 'widget_name'` (or KeyError `'prop'`).

- [ ] **Step 3: Implement routing**

In `widgets/composed.py`:

1. Signature (line 613): `def build_controls(row_defs, switch_store=None, on_switch=None, widget_name=""):`

2. Inside the `one(row)` closure, change the four branches:

```python
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
            from .adapters import ADAPTERS
            a = ADAPTERS[row["target"]]
            return FlipBox(row["label"], get=a["get"], set=a["set"])
```

```python
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
```

```python
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
```

```python
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
```

3. `make_widget` (line 757): pass the name:

```python
    inst.controls = build_controls(wdef["rows"], switch_store=inst.switches,
                                   on_switch=on_switch,
                                   widget_name=wdef["name"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/ -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add widgets/composed.py tests/ui/widgets/test_composed.py
git commit -m "feat(widgets): build_controls routes 'data' rows to scene-store adapters"
```

---

### Task 5: Scene properties + registration

**Files:**
- Modify: `prefs/addon_properties.py` (new PropertyGroups before `IOPS_SceneProperties:249`; new property on `IOPS_SceneProperties`)
- Modify: `__init__.py` (import line 104, classes tuple line 337)

**Interfaces:**
- Consumes: nothing.
- Produces: `Scene.IOPS.widget_data` — the RNA store `scene_store._store()` finds at runtime. `IOPS_WidgetDataKV.name/.value`, `IOPS_WidgetDataBlock.name/.entries`.

- [ ] **Step 1: Add PropertyGroups**

In `prefs/addon_properties.py`, insert directly above `class IOPS_SceneProperties(PropertyGroup):` (line 249):

```python
class IOPS_WidgetDataKV(PropertyGroup):
    """One scene-stored value for a composed widget; .name is the data key."""
    value: StringProperty(name="Value", default="")


class IOPS_WidgetDataBlock(PropertyGroup):
    """Per-widget scene data block; .name is the widget name."""
    entries: CollectionProperty(
        type=IOPS_WidgetDataKV,
        name="Entries",
        description="Key/value entries stored by the widget",
    )
```

And inside `IOPS_SceneProperties`, after `widget_list` (line 265–269):

```python
    widget_data: CollectionProperty(
        type=IOPS_WidgetDataBlock,
        name="Widget data",
        description="Per-.blend data stored by composed widgets"
                    " (see widgets/scene_store.py)",
    )
```

- [ ] **Step 2: Register**

In `__init__.py`:

Line 104 becomes:

```python
from .prefs.addon_properties import IOPS_SceneProperties, IOPS_CollectionItem, IOPS_ExecutorScriptItem, IOPS_WidgetListItem, IOPS_RenameSettings, IOPS_WidgetDataKV, IOPS_WidgetDataBlock
```

Classes tuple (line 337 area) — order matters, KV before Block before SceneProperties:

```python
    IOPS_RenameSettings,  # PointerProperty target — must register before IOPS_SceneProperties
    IOPS_WidgetDataKV,     # CollectionProperty targets — same rule
    IOPS_WidgetDataBlock,
    IOPS_SceneProperties,
```

- [ ] **Step 3: Verify live in Blender**

Reload the addon (blinker reload, port 9902), then via Blender MCP `execute_blender_code`:

```python
import bpy
from InteractionOps.widgets import scene_store
ctx = bpy.context
scene_store.set_value(ctx, "smoke_test", "k", "v1")
assert scene_store.get(ctx, "smoke_test", "k") == "v1"
assert ctx.scene.IOPS.widget_data.get("smoke_test").entries.get("k").value == "v1"
assert scene_store.purge(ctx, "smoke_test") == 1
print("scene_store live: OK")
```

Expected: `scene_store live: OK`, no tracebacks in the console.

- [ ] **Step 4: Commit**

```bash
git add prefs/addon_properties.py __init__.py
git commit -m "feat(widgets): Scene.IOPS.widget_data store properties + registration"
```

---

### Task 6: Purge operator + prefs Widgets-tab button

**Files:**
- Create: `operators/purge_widget_data.py`
- Modify: `__init__.py` (import near line 215, classes tuple near line 534)
- Modify: `prefs/widget_composer.py` (`draw_widgets_tab`, after the manage-buttons column ~line 324)

**Interfaces:**
- Consumes: Task 1's `scene_store.purge`; `ui/widgets/state.py` `mark_all_dirty`/`tag_redraw_all`.
- Produces: `iops.purge_widget_data` operator (`widget: StringProperty` — empty = all). Widget authors may call it from BUTTON rows: `"op": "iops.purge_widget_data", "op_kwargs": {"widget": "my_widget"}`.

- [ ] **Step 1: Write the operator**

Create `operators/purge_widget_data.py`:

```python
"""Purge per-.blend widget data (Scene.IOPS.widget_data blocks).

One operator, two modes: `widget` empty purges EVERY widget's data in
the current scene; non-empty purges that widget's block only. Runs with
a confirm dialog (destructive, per-scene). Widget authors can expose a
per-widget purge as a BUTTON row:
    {"type": "BUTTON", "label": "Reset", "op": "iops.purge_widget_data",
     "op_kwargs": {"widget": "my_widget"}, "role": "error"}
"""
import bpy
from bpy.props import StringProperty

from ..widgets import scene_store


class IOPS_OT_purge_widget_data(bpy.types.Operator):
    """Remove widget data stored in the current scene"""

    bl_idname = "iops.purge_widget_data"
    bl_label = "Purge Widgets Data"
    bl_options = {"REGISTER", "UNDO"}

    widget: StringProperty(
        name="Widget",
        default="",
        description="Widget whose data to purge; empty purges ALL"
                    " widget data in the scene",
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        removed = scene_store.purge(context, self.widget or None)
        target = "'%s'" % self.widget if self.widget else "all widgets"
        self.report({"INFO"},
                    "IOPS: purged %d data block(s) (%s)" % (removed, target))
        # Data-bound controls cache (value, mixed) pairs — repaint.
        from ..ui.widgets import state
        state.mark_all_dirty()
        state.tag_redraw_all()
        return {"FINISHED"}


classes = (IOPS_OT_purge_widget_data,)
```

- [ ] **Step 2: Register**

In `__init__.py`, next to the uv_image_slots import (line 215):

```python
from .operators.purge_widget_data import classes as _purge_widget_data_classes
```

Classes tuple (after `*_uv_image_slots_classes,` line 534):

```python
    *_purge_widget_data_classes,
```

- [ ] **Step 3: Prefs button**

In `prefs/widget_composer.py` `draw_widgets_tab`, append at the end of the function (after the `ops.operator("iops.widgets_open_folder", ...)` line ~324):

```python
    layout.separator(type="LINE")
    row = layout.row()
    row.operator("iops.purge_widget_data",
                 text="Purge Widgets Data (this scene)", icon="TRASH")
```

- [ ] **Step 4: Verify live**

Reload the addon, then via Blender MCP `execute_blender_code`:

```python
import bpy
from InteractionOps.widgets import scene_store
scene_store.set_value(bpy.context, "purge_smoke", "k", "v")
bpy.ops.iops.purge_widget_data(widget="purge_smoke")
assert scene_store.get(bpy.context, "purge_smoke", "k") is None
print("purge operator: OK")
```

Expected: `purge operator: OK`. Also open Preferences → Add-ons → iOps → Widgets tab and confirm the "Purge Widgets Data (this scene)" button draws and pops a confirm dialog.

- [ ] **Step 5: Commit**

```bash
git add operators/purge_widget_data.py __init__.py prefs/widget_composer.py
git commit -m "feat(widgets): iops.purge_widget_data operator + prefs purge button"
```

---

### Task 7: Docs + demo JSON

**Files:**
- Modify: `ai_skills/iops-custom-widgets/schema-reference.md`
- Create: `presets/widgets_demo/scene_store_demo.json`

**Interfaces:** none (docs).

- [ ] **Step 1: Demo JSON**

Create `presets/widgets_demo/scene_store_demo.json`:

```json
{
  "version": 1,
  "name": "scene_store_demo",
  "title": "Scene Store Demo",
  "space": "VIEW_3D",
  "rows": [
    { "type": "SECTION", "label": "Per-.blend Data" },
    { "type": "INPUT", "data": "note", "value_type": "STRING", "label": "Note" },
    { "type": "BUTTONS", "data": "level", "value_type": "INT", "values": [1, 2, 3] },
    { "type": "FLIPBOX", "data": "enabled", "label": "Enabled" },
    { "type": "BUTTON", "label": "Purge This Widget", "op": "iops.purge_widget_data",
      "op_kwargs": { "widget": "scene_store_demo" }, "role": "error" }
  ]
}
```

- [ ] **Step 2: Schema reference**

In `ai_skills/iops-custom-widgets/schema-reference.md`, add a section (near the binding docs; adjust heading level to match the file) and extend each of the four control tables' binding row to mention `data`:

````markdown
### `data` — per-.blend storage binding

FLIPBOX / DROPDOWN / INPUT / BUTTONS accept `data: "<key>"` as an
alternative to `prop`. The value is stored in the scene
(`Scene.IOPS.widget_data`) and saved/loaded with the .blend file. The key
is scoped to the owning widget — two widgets using `"data": "slot_0"`
never collide.

- Exactly one binding per control: `data` is mutually exclusive with
  `prop` (and `target`/`switch` on FLIPBOX).
- Values are stored as strings; interpretation is DECLARED by
  `value_type`, same rules as `prop` bindings (DEGREES authors degrees,
  stores radians). FLIPBOX stores `"1"`/`"0"`.
- Unset key = "not set yet": the control shows the type's default
  (`""`/`0`/`0.0`/off) and stays enabled — unlike a broken `prop` path,
  which renders disabled.
- DROPDOWN with `data` has no RNA enum to introspect: give it
  `items_from` (a registered provider) or it lists nothing.
- Storage is per-SCENE (Blender's convention for per-file data);
  multi-scene files keep one store per scene.
- Purge: `iops.purge_widget_data` (`widget` kwarg: empty = all widgets).
  Useful as a BUTTON row:
  `{"type": "BUTTON", "label": "Reset", "op": "iops.purge_widget_data",
    "op_kwargs": {"widget": "my_widget"}, "role": "error"}`

Example:

```json
{ "type": "ROW", "cells": [
  { "type": "DROPDOWN", "data": "slot_0", "items_from": "uv_images", "label": "1" },
  { "type": "INPUT", "data": "note", "value_type": "STRING", "label": "Note" }
]}
```
````

- [ ] **Step 3: Commit**

```bash
git add presets/widgets_demo/scene_store_demo.json ai_skills/iops-custom-widgets/schema-reference.md
git commit -m "docs(widgets): 'data' scene-store binding schema docs + demo widget"
```

---

### Task 8: Live end-to-end verification (Blender)

**Files:** none (verification only; fix-forward if anything fails).

**Interfaces:** consumes everything above.

- [ ] **Step 1: Deploy the demo widget**

Copy `presets/widgets_demo/scene_store_demo.json` into the user widgets folder (UGC location, NOT tracked): `B:\scripts\presets\iops\widgets\scene_store_demo.json`. Reload the addon (blinker, port 9902).

- [ ] **Step 2: Interactive round-trip via MCP**

Via Blender MCP `execute_blender_code`:

```python
import bpy
from InteractionOps.widgets import scene_store
ctx = bpy.context
# simulate the widget writing values
scene_store.set_value(ctx, "scene_store_demo", "note", "hello e2e")
scene_store.set_value(ctx, "scene_store_demo", "level", "2")
scene_store.set_value(ctx, "scene_store_demo", "enabled", "1")
bpy.ops.wm.save_as_mainfile(filepath=r"B:\test\scene_store_e2e.blend")
bpy.ops.wm.open_mainfile(filepath=r"B:\test\scene_store_e2e.blend")
ctx = bpy.context
assert scene_store.get(ctx, "scene_store_demo", "note") == "hello e2e"
assert scene_store.get(ctx, "scene_store_demo", "level") == "2"
assert scene_store.get(ctx, "scene_store_demo", "enabled") == "1"
print("save/load persistence: OK")
```

Expected: `save/load persistence: OK`.

- [ ] **Step 3: Widget UI check**

Toggle the demo widget (prefs Widgets tab → hotkey or All Widgets Panel), take a viewport screenshot via MCP (`get_screenshot_of_area_as_image`), confirm: INPUT shows "hello e2e", BUTTONS highlights 2, FLIPBOX is on. Edit the INPUT in the overlay, then:

```python
import bpy
from InteractionOps.widgets import scene_store
print(scene_store.get(bpy.context, "scene_store_demo", "note"))
```

Expected: the edited text.

- [ ] **Step 4: Undo + purge behavior**

In Blender: change the FLIPBOX, press Ctrl+Z — the flip reverts (scene props are undo-tracked; the undo_post handler repaints). Then click the widget's "Purge This Widget" button, confirm — all three controls fall back to defaults, and:

```python
import bpy
print(len(bpy.context.scene.IOPS.widget_data))
```

Expected: `0` (only the demo widget had data).

- [ ] **Step 5: Full pure suite one last time**

Run: `python -m pytest tests/ -v`
Expected: all PASS

- [ ] **Step 6: Clean up**

Delete `B:\test\scene_store_e2e.blend` and (optionally) the deployed demo JSON. No commit — nothing tracked changed.
