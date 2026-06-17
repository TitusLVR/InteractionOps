# Object Color GPU Widget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent, draggable GPU viewport widget that mirrors the IOPS Object Color panel — a recents-focused grid of click-to-apply color swatches plus Apply and Copy-From-Active, reusing the existing object-color operators.

**Architecture:** Add one new framework control (`Swatch`) that draws an sRGB-encoded RGBA fill and fires an operator on click (reusing the existing button gesture path). Add a hand-coded `ObjectColorWidget` whose adapters read `scene.IOPS` color props. No operator changes.

**Tech Stack:** Blender Python addon (`bpy`), the in-repo GPU widget framework (`ui/widgets/`), pytest (bpy-free pure-logic tests).

---

## Background for the implementer

Read these before starting (do not skip — the patterns here are load-bearing):

- **Spec:** `docs/superpowers/specs/2026-06-16-object-color-gpu-widget-design.md`
- **Framework controls:** `ui/widgets/controls.py` — `Control`, `_ValueControl`,
  `ActionButton`. The data-binding contract: getters return
  `(value, is_mixed)`; `value is None` = "nothing to read" → renders disabled.
- **Existing widgets:** `widgets/edge_data.py`, `widgets/ccp_data_ops.py`
  (top-level framework import) and `widgets/composed.py` (framework import
  *deferred* into functions so the module is standalone-importable for pytest).
  `ObjectColorWidget` follows the **composed.py deferral pattern** so its pure
  adapters can be unit-tested.
- **Operators reused verbatim** (`operators/object_color.py`):
  `iops.object_color_apply`, `iops.object_color_copy_from_active`,
  `iops.object_color_apply_recent` (`index` IntProperty).
- **Color props** (`prefs/addon_properties.py`): `iops_object_color` and
  `iops_object_color_recent_0..7`, all `FloatVectorProperty(subtype="COLOR",
  size=4)` (scene-linear). Screen-space draws must encode linear→sRGB via
  `ui/draw/theme.py::_srgb_encode`.
- **Why render/events have no unit tests:** `render.py` imports `ui/draw`
  (`gpu`) and `ui/hud` (`blf`); `theme.py` imports `bpy`. None import under
  plain pytest. Swatch drawing + gesture routing are verified manually in
  Blender (Task 8).

### Test runner

All pytest commands run **from the repo root** `D:\git\InteractionOps`:

```
python -m pytest <path> -v -p no:langsmith_plugin
```

`-p no:langsmith_plugin` skips a third-party plugin that is broken in this
environment (per `tests/pytest.ini`). `tests/conftest.py` puts the repo root on
`sys.path`, so `from ui.widgets.controls import ...` resolves.

---

## File Structure

- **Modify** `ui/widgets/controls.py` — extract a shared `_invoke_operator`
  helper; add the `Swatch` control.
- **Modify** `ui/widgets/render.py` — `_draw_swatch`, layout/dispatch cases.
- **Modify** `ui/widgets/events.py` — route `swatch` through the button path.
- **Modify** `ui/widgets/__init__.py` — export `Swatch`.
- **Create** `widgets/object_color.py` — adapters + deferred widget factory.
- **Modify** `widgets/__init__.py` — register `ObjectColorWidget`.
- **Create** `tests/ui/widgets/test_controls.py` — `Swatch` + helper tests.
- **Create** `tests/ui/widgets/test_object_color.py` — adapter tests.

---

## Task 1: Extract `_invoke_operator` helper in controls.py

DRY prep: `ActionButton.execute` hard-codes the `bpy.ops` dispatch. Extract it
so `Swatch` (Task 2) reuses the exact same firing logic, and so both are
unit-testable by patching the helper.

**Files:**
- Modify: `ui/widgets/controls.py` (`ActionButton.execute`, ~lines 266-275)
- Test: `tests/ui/widgets/test_controls.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/ui/widgets/test_controls.py`:

```python
"""Pure-pytest tests for ui/widgets/controls.py — the Swatch control and the
shared operator-firing helper. No bpy: controls.py defers its only bpy touch
(_invoke_operator) to call time, so it is patched here."""
import ui.widgets.controls as controls
from ui.widgets.controls import ActionButton, Swatch


def test_action_button_execute_delegates_to_invoke_operator(monkeypatch):
    calls = []
    monkeypatch.setattr(controls, "_invoke_operator",
                        lambda op, kw: calls.append((op, kw)))
    btn = ActionButton("Apply", op="iops.object_color_apply", kwargs={"x": 1})
    btn.execute(context=None)
    assert calls == [("iops.object_color_apply", {"x": 1})]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/ui/widgets/test_controls.py -v -p no:langsmith_plugin`
Expected: FAIL — `AttributeError`/`ImportError` (no `Swatch` yet, no
`_invoke_operator`). The collection error itself is the expected failure.

- [ ] **Step 3: Add the helper and refactor ActionButton.execute**

In `ui/widgets/controls.py`, add this module-level function just above the
`ActionButton` class:

```python
def _invoke_operator(op_idname, kwargs):
    """Fire an operator by idname via INVOKE_DEFAULT. The ONLY bpy touch in
    this module — deferred import so the module stays importable under plain
    pytest. INVOKE_DEFAULT: invoke-only operators (e.g. CCP export ops) raise
    under EXEC_DEFAULT; operators without invoke fall through to execute, so
    this is safe for both kinds. Shared by ActionButton and Swatch."""
    import bpy
    module, _, name = op_idname.partition(".")
    op = getattr(getattr(bpy.ops, module), name)
    return op("INVOKE_DEFAULT", **kwargs)
```

Replace the body of `ActionButton.execute` with:

```python
    def execute(self, context):
        return _invoke_operator(self.op, self.kwargs)
```

(Delete the old inline `import bpy` / `partition` / `getattr` lines and their
comment — they now live in `_invoke_operator`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/ui/widgets/test_controls.py -v -p no:langsmith_plugin`
Expected: `test_action_button_execute_delegates_to_invoke_operator` PASS.
(`from ... import Swatch` still fails collection — that is fixed in Task 2.)

- [ ] **Step 5: Commit**

```bash
git add ui/widgets/controls.py tests/ui/widgets/test_controls.py
git commit -m "refactor: extract _invoke_operator helper in widget controls"
```

---

## Task 2: Add the `Swatch` control

**Files:**
- Modify: `ui/widgets/controls.py` (add `Swatch` after `ActionButton`)
- Modify: `ui/widgets/__init__.py` (export `Swatch`)
- Test: `tests/ui/widgets/test_controls.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/ui/widgets/test_controls.py`:

```python
def test_swatch_value_caches_and_refreshes_on_dirty():
    src = {"c": ((1.0, 0.0, 0.0, 1.0), False)}
    sw = Swatch(get=lambda ctx: src["c"], op="iops.x")
    assert sw.value(None) == ((1.0, 0.0, 0.0, 1.0), False)
    src["c"] = ((0.0, 1.0, 0.0, 1.0), False)
    assert sw.value(None) == ((1.0, 0.0, 0.0, 1.0), False)   # still cached
    sw.mark_dirty()
    assert sw.value(None) == ((0.0, 1.0, 0.0, 1.0), False)   # re-read


def test_swatch_disabled_sentinel_when_color_none():
    sw = Swatch(get=lambda ctx: (None, False), op="iops.x")
    assert sw.value(None) == (None, False)


def test_swatch_execute_delegates_with_kwargs(monkeypatch):
    calls = []
    monkeypatch.setattr(controls, "_invoke_operator",
                        lambda op, kw: calls.append((op, kw)))
    sw = Swatch(get=lambda ctx: ((1, 1, 1, 1), False),
                op="iops.object_color_apply_recent", kwargs={"index": 3})
    sw.execute(None)
    assert calls == [("iops.object_color_apply_recent", {"index": 3})]


def test_swatch_enabled_get_is_dirty_cached():
    flags = {"on": True}
    sw = Swatch(get=lambda ctx: ((1, 1, 1, 1), False), op="iops.x",
                enabled_get=lambda ctx: flags["on"])
    assert sw.update_enabled(None) is True
    flags["on"] = False
    assert sw.update_enabled(None) is True    # cached until mark_dirty
    sw.mark_dirty()
    assert sw.update_enabled(None) is False


def test_swatch_is_interactive_and_kind():
    sw = Swatch(get=lambda ctx: ((1, 1, 1, 1), False), op="iops.x")
    assert sw.kind == "swatch"
    assert sw.interactive is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/ui/widgets/test_controls.py -v -p no:langsmith_plugin`
Expected: collection/`ImportError` for `Swatch` (not yet defined).

- [ ] **Step 3: Add the `Swatch` class**

In `ui/widgets/controls.py`, add after the `ActionButton` class (and before
`Row`):

```python
class Swatch(_ValueControl):
    """Color swatch bound to an RGBA getter, firing an operator on click.

    Read-only binding: `set` is None and `write()` is never called — the
    swatch only displays its color and fires `op` (release-inside, exactly
    like ActionButton). The getter returns (rgba, is_mixed); a None color is
    the disabled sentinel (renders faded, no operator fires). Scalar binding,
    so is_mixed is always False."""

    kind = "swatch"
    interactive = True

    def __init__(self, get, op, kwargs=None, label="", enabled_get=None):
        super().__init__(get, None)
        self.op = op            # operator idname, e.g. "iops.object_color_apply"
        self.kwargs = dict(kwargs) if kwargs else {}
        self.label = label      # optional centered glyph/text on the fill
        self.enabled_get = enabled_get

    def execute(self, context):
        return _invoke_operator(self.op, self.kwargs)
```

- [ ] **Step 4: Export `Swatch` from the package**

In `ui/widgets/__init__.py`:

Change the controls import (currently around lines 23-24):

```python
from .controls import (Control, Section, Slider, PresetRow, FlipBox,
                       ActionButton, Row, Swatch)
```

Add `"Swatch"` to `__all__` (in the control names group):

```python
    "Control", "Section", "Slider", "PresetRow", "FlipBox",
    "ActionButton", "Row", "Swatch",
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/ui/widgets/test_controls.py -v -p no:langsmith_plugin`
Expected: all `test_swatch_*` and the Task 1 test PASS.

- [ ] **Step 6: Commit**

```bash
git add ui/widgets/controls.py ui/widgets/__init__.py tests/ui/widgets/test_controls.py
git commit -m "feat: add Swatch color control to widget framework"
```

---

## Task 3: Render the swatch

No unit test (render.py requires `gpu`/`blf`). Verified in Blender (Task 8).

**Files:**
- Modify: `ui/widgets/render.py`

- [ ] **Step 1: Import the sRGB encoder**

Change the theme import (currently line 20) to:

```python
from ..draw.theme import Role, get_theme, _srgb_encode
```

- [ ] **Step 2: Add `_draw_swatch`**

Add after `_draw_button` (~line 284):

```python
def _draw_swatch(control, rect, theme, dim, context, live):
    value, _ = control.value(context) if live else control.cached()
    disabled = (value is None) or not control.enabled
    eff = dim * (DISABLED_ALPHA if disabled else 1.0)
    inset = 2.0
    if value is not None:
        # subtype=COLOR props are scene-linear; encode to sRGB to match the
        # native color field. Force opaque fill so a low-alpha stored color
        # is still visible (alpha is not part of the swatch's job here).
        enc = _srgb_encode(value)
        primitives.rect_2d(rect.x + inset, rect.y + inset,
                           rect.w - inset * 2.0, rect.h - inset * 2.0,
                           color=(enc[0], enc[1], enc[2], 1.0), theme=theme)
    # Outline/label carry the disabled fade; the fill stays readable.
    _outline(rect, _col(theme, Role.LINE, eff), theme)
    if control.label:
        _text_centered(control.label, rect, theme=theme,
                       color=_col(theme, Role.HUD_LABEL, eff))
```

- [ ] **Step 3: Add the layout + dispatch cases**

In `_row_height` (~line 82), add a swatch branch (taller for a chunky,
clickable target):

```python
def _row_height(control, theme):
    label_h = theme.text_size("hud_label")
    if control.kind == "section":
        return label_h + ROW_PAD_SECTION
    if control.kind == "swatch":
        return label_h * 1.8 + ROW_PAD_CONTROL
    return label_h + ROW_PAD_CONTROL
```

In `_control_min_width` (~line 89), add before the `if control.kind == "row":`
branch:

```python
    if control.kind == "swatch":
        return 28.0
```

In `_draw_control` (~line 287), add the dispatch branch (after the `button`
branch):

```python
    elif kind == "swatch":
        _draw_swatch(control, rect, theme, dim, context, live)
```

- [ ] **Step 4: Sanity-check the module still parses**

Run: `python -c "import ast; ast.parse(open('ui/widgets/render.py').read())"`
Expected: no output (exit 0). Full import needs bpy — checked in Blender at
Task 8.

- [ ] **Step 5: Commit**

```bash
git add ui/widgets/render.py
git commit -m "feat: render Swatch control (sRGB fill, outline, label)"
```

---

## Task 4: Route swatch clicks through the button gesture

No unit test (events.py requires bpy). Verified in Blender (Task 8).

**Files:**
- Modify: `ui/widgets/events.py` (`_begin_gesture`, ~lines 203-206)

- [ ] **Step 1: Extend the button branch to accept swatches**

In `IOPS_OT_widget_interact._begin_gesture`, change:

```python
        if control.kind == "button":
            self._control = control
            self._mode = "button"
            return self._begin_modal(context)
        return None
```

to:

```python
        if control.kind in ("button", "swatch"):
            # Swatch fires its operator on release-inside, exactly like a
            # button (one ed.undo_push, mark_dirty afterwards).
            self._control = control
            self._mode = "button"
            return self._begin_modal(context)
        return None
```

(`_finish_gesture`'s `"button"` mode already calls `self._control.execute()` +
`mark_dirty()` + `_undo_push()`; `Swatch.execute` matches that interface, so no
other change is needed.)

- [ ] **Step 2: Sanity-check the module still parses**

Run: `python -c "import ast; ast.parse(open('ui/widgets/events.py').read())"`
Expected: no output (exit 0).

- [ ] **Step 3: Commit**

```bash
git add ui/widgets/events.py
git commit -m "feat: route swatch clicks through the widget button gesture"
```

---

## Task 5: Create `widgets/object_color.py` (adapters + factory)

**Files:**
- Create: `widgets/object_color.py`
- Test: `tests/ui/widgets/test_object_color.py` (create)

- [ ] **Step 1: Write the failing adapter tests**

Create `tests/ui/widgets/test_object_color.py`:

```python
"""Pure-logic tests for widgets/object_color.py adapters. Loaded standalone
(like test_composed.py) so the package __init__ — which imports bpy — is never
touched; the widget's framework import is deferred into functions, so only the
pure adapters execute here."""
import importlib.util
import os
import sys

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__),
                                      "..", "..", ".."))


def _load_object_color():
    path = os.path.join(_ROOT, "widgets", "object_color.py")
    spec = importlib.util.spec_from_file_location("iops_test_object_color",
                                                  path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


oc = _load_object_color()


class _Props:
    pass


class _Scene:
    def __init__(self, props):
        self.IOPS = props


class _Ctx:
    def __init__(self, scene=None, selected=None, active=None):
        self.scene = scene
        self.selected_objects = list(selected) if selected else []
        self.active_object = active


def test_get_current_reads_scene_prop():
    p = _Props()
    p.iops_object_color = (0.2, 0.4, 0.6, 1.0)
    assert oc.get_current(_Ctx(scene=_Scene(p))) == ((0.2, 0.4, 0.6, 1.0),
                                                      False)


def test_get_current_absent_scene_is_disabled_sentinel():
    assert oc.get_current(_Ctx(scene=None)) == (None, False)


def test_get_current_absent_prop_is_disabled_sentinel():
    assert oc.get_current(_Ctx(scene=_Scene(_Props()))) == (None, False)


def test_get_recent_reads_indexed_slot():
    p = _Props()
    setattr(p, "iops_object_color_recent_3", (1.0, 0.0, 0.0, 1.0))
    assert oc.get_recent(3)(_Ctx(scene=_Scene(p))) == ((1.0, 0.0, 0.0, 1.0),
                                                        False)


def test_get_recent_absent_slot_is_disabled_sentinel():
    assert oc.get_recent(3)(_Ctx(scene=_Scene(_Props()))) == (None, False)


def test_has_selected_objects():
    assert oc.has_selected_objects(_Ctx(selected=["a"])) is True
    assert oc.has_selected_objects(_Ctx(selected=[])) is False


def test_has_active_object():
    assert oc.has_active_object(_Ctx(active=object())) is True
    assert oc.has_active_object(_Ctx(active=None)) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/ui/widgets/test_object_color.py -v -p no:langsmith_plugin`
Expected: FAIL — `FileNotFoundError` for `widgets/object_color.py`.

- [ ] **Step 3: Create the module**

Create `widgets/object_color.py`:

```python
"""Object Color widget — recents-focused GPU panel mirroring the IOPS Object
Color sidebar panel (ui/iops_object_color_panel.py).

Eight recent-color swatches (click to apply), a current-color swatch (click =
Apply current), and Copy From Active / Apply buttons. Reuses the object-color
operators verbatim (operators/object_color.py). No in-panel color editing — a
GPU panel cannot host Blender's native color wheel.

The framework import is DEFERRED into _build_controls()/make_widget() (the
widgets/composed.py pattern) so the pure adapters below can be unit-tested by
loading this module standalone, without pulling the addon root (bpy)."""

# Mirrors the iops_object_color_recent_N property count on IOPS_SceneProperties
# (see prefs/addon_properties.py and operators/object_color.py RECENT_SLOTS).
RECENT_SLOTS = 8

OBJECT_COLOR_NAME = "object_color"
OBJECT_COLOR_TITLE = "IOPS Object Color"


# ----------------------------------------------------------------------
# Adapters (read scene.IOPS; bpy-free, pytest-covered)
# ----------------------------------------------------------------------
def _scene_props(context):
    """The IOPS scene property group, or None when unavailable."""
    scene = getattr(context, "scene", None)
    return getattr(scene, "IOPS", None) if scene is not None else None


def get_current(context):
    """Current picker color -> (rgba, False); (None, False) when absent."""
    props = _scene_props(context)
    if props is None or not hasattr(props, "iops_object_color"):
        return (None, False)
    return (tuple(props.iops_object_color), False)


def get_recent(index):
    """A get(context) closure for recent slot `index` (0 = most recent)."""
    attr = f"iops_object_color_recent_{index}"

    def get(context):
        props = _scene_props(context)
        if props is None or not hasattr(props, attr):
            return (None, False)
        return (tuple(getattr(props, attr)), False)

    return get


def has_selected_objects(context):
    """enabled_get for Apply / recents (inert with nothing selected)."""
    return bool(getattr(context, "selected_objects", None))


def has_active_object(context):
    """enabled_get for Copy From Active."""
    return getattr(context, "active_object", None) is not None


# ----------------------------------------------------------------------
# Control building + widget factory (framework import deferred)
# ----------------------------------------------------------------------
def _build_controls():
    from ..ui.widgets import Section, Row, ActionButton, Swatch

    recents = [
        Swatch(get=get_recent(i), op="iops.object_color_apply_recent",
               kwargs={"index": i}, enabled_get=has_selected_objects)
        for i in range(RECENT_SLOTS)
    ]
    return [
        Section("Current"),
        # Click the current swatch = Apply current color to selected objects.
        Swatch(get=get_current, op="iops.object_color_apply",
               enabled_get=has_selected_objects),
        Row([ActionButton("Copy From Active",
                          op="iops.object_color_copy_from_active",
                          enabled_get=has_active_object),
             ActionButton("Apply", op="iops.object_color_apply",
                          enabled_get=has_selected_objects)]),
        Section("Recent"),
        Row(recents[0:4]),
        Row(recents[4:8]),
    ]


def make_widget():
    """Build the live ObjectColorWidget instance (framework import deferred so
    this module stays standalone-importable for pytest)."""
    from ..ui.widgets import Widget

    class ObjectColorWidget(Widget):
        name = OBJECT_COLOR_NAME
        title = OBJECT_COLOR_TITLE
        space = "VIEW_3D"

        def build(self):
            return _build_controls()

        def poll(self, context):
            # No mode gating: object color applies in any mode. Selection /
            # active-object state grays controls via enabled_get instead of
            # collapsing the panel (same as CCPDataOpsWidget).
            return True

    return ObjectColorWidget()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/ui/widgets/test_object_color.py -v -p no:langsmith_plugin`
Expected: all 8 adapter tests PASS.

- [ ] **Step 5: Commit**

```bash
git add widgets/object_color.py tests/ui/widgets/test_object_color.py
git commit -m "feat: object color widget adapters + factory"
```

---

## Task 6: Register the widget

**Files:**
- Modify: `widgets/__init__.py`

- [ ] **Step 1: Wire registration**

In `widgets/__init__.py`, inside the `if _HAS_BPY:` block, change the imports
and registration. Replace lines 18-27 (the `from .edge_data ...` /
`from .ccp_data_ops ...` imports and the two `register_widget(...)` calls):

```python
    from ..ui.widgets import register_widget, unregister_widget
    from .edge_data import EdgeDataWidget
    from .ccp_data_ops import CCPDataOpsWidget
    from .object_color import make_widget as make_object_color_widget
    from .object_color import OBJECT_COLOR_NAME

    # ccp_data_ops registers unconditionally even though it targets the
    # CCP Tools addon: a register-time presence probe would miss CCP Tools
    # enabling AFTER iOps (addon load order is not ours to control). The
    # widget renders disabled while scene.CCP is absent instead.
    register_widget(EdgeDataWidget)
    register_widget(CCPDataOpsWidget)
    register_widget(make_object_color_widget())
```

In the nested `register()` function, add the object-color line:

```python
    def register():
        # Idempotent — re-registering replaces the live instance by name
        register_widget(EdgeDataWidget)
        register_widget(CCPDataOpsWidget)
        register_widget(make_object_color_widget())
```

In the nested `unregister()` function, add its teardown (after the existing
two `unregister_widget(...)` lines):

```python
        unregister_widget(CCPDataOpsWidget.name)
        unregister_widget(EdgeDataWidget.name)
        unregister_widget(OBJECT_COLOR_NAME)
```

- [ ] **Step 2: Sanity-check the module still parses**

Run: `python -c "import ast; ast.parse(open('widgets/__init__.py').read())"`
Expected: no output (exit 0).

- [ ] **Step 3: Full pytest run (no regressions)**

Run: `python -m pytest tests/ -v -p no:langsmith_plugin`
Expected: all tests PASS (the new `test_controls.py` + `test_object_color.py`
plus the existing suite).

- [ ] **Step 4: Commit**

```bash
git add widgets/__init__.py
git commit -m "feat: register ObjectColorWidget"
```

---

## Task 7: Reload in Blender and confirm it loads clean

**Files:** none (verification).

- [ ] **Step 1: Reload the addon**

Reload the InteractionOps addon in the connected Blender (dev reload infra:
disable/enable the addon, or the project's reload trigger). Watch the system
console.

Expected: no tracebacks; console prints `IOPS Widget keymap registered`
(unchanged from before).

- [ ] **Step 2: Confirm the widget is registered**

In Blender's Python console:

```python
from InteractionOps.ui.widgets import get_widget
w = get_widget("object_color")
print(w, w.title, [c.kind for c in w.controls])
```

Expected: a live widget, title `IOPS Object Color`, and control kinds
`['section', 'swatch', 'row', 'section', 'row', 'row']`.

- [ ] **Step 3: Confirm it appears in prefs + has a toggle entry**

Open Preferences → Add-ons → InteractionOps → the **Widgets** tab. Expected:
`IOPS Object Color` is listed with an (unbound) toggle key field, alongside
Edge Data and CCP Data OPS.

---

## Task 8: Manual functional verification

**Files:** none (verification). Covers what pytest cannot (`gpu`/`blf`).

- [ ] **Step 1: Toggle the widget on**

Assign a key to the Object Color widget toggle in the Widgets prefs tab (or
call `bpy.ops.iops.widget_toggle(name="object_color")` from the console with
the cursor over a 3D viewport). Expected: the panel appears at the cursor.

- [ ] **Step 2: Verify swatch colors**

With several objects given distinct `obj.color` values, apply a few via the
sidebar Object Color panel so recents populate. Expected: the widget's recent
swatches show the **same colors** as the sidebar panel's recent fields (sRGB
match — not too dark), and the current swatch matches the picker.

- [ ] **Step 3: Verify click actions**

- Select 2+ objects, click a **recent swatch** → those objects take that color
  (check Solid → Object viewport shading); the picker loads it; recents do
  **not** reorder.
- Click the **current swatch** → selected objects take the current color
  (and recents push/dedup, slot 0 updates).
- Click **Copy From Active** → the current swatch updates to the active
  object's color.
- Click **Apply** → same as the current swatch click.

- [ ] **Step 4: Verify disabled states**

Deselect all objects. Expected: current swatch, recents, and Apply gray out
(faded outline; recent fills still visible) and clicking them does nothing.
With no active object, Copy From Active grays out.

- [ ] **Step 5: Verify chrome**

Drag the title bar → panel moves and the position persists across a toggle
off/on. Click the `×` → panel hides. Undo (Ctrl+Z) after an Apply → reverts the
color in one step.

- [ ] **Step 6: Final commit (if any tweaks were needed)**

If manual testing required render/layout tweaks, commit them:

```bash
git add -A
git commit -m "fix: object color widget render/layout adjustments from manual testing"
```

---

## Self-review notes (for the implementer)

- **Spec coverage:** `Swatch` (Tasks 1-3), gesture routing (Task 4), widget +
  adapters (Task 5), registration/prefs/hotkey (Task 6-7), refresh + disabled
  states + sRGB (Tasks 3, 8). All spec sections map to a task.
- **Out of scope (do not implement):** JSON composer (`composed.py`) swatch
  support; color-picker popup; IMAGE_EDITOR placement.
- **Naming consistency:** `_invoke_operator(op_idname, kwargs)`,
  `Swatch(get, op, kwargs, label, enabled_get)`, `get_current(context)`,
  `get_recent(index) -> get(context)`, `has_selected_objects`,
  `has_active_object`, `make_widget()`, `OBJECT_COLOR_NAME == "object_color"`
  are used identically across all tasks.
