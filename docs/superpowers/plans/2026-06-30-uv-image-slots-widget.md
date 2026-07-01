# UV Image Slots Widget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A GPU widget with 3 image slots that flip the UV/Image editor's active image in one click, usable from both the 3D viewport and the UV/Image editor.

**Architecture:** A pure-JSON composed widget binds 3 DROPDOWN rows to per-slot `WindowManager` enum properties (assign) plus a per-row BUTTON that runs a flip operator (activate). Slot assignments are stored as image *names* in session-only `WindowManager` StringProperties (never saved to `.blend`). The widget framework gains multi-space support so one widget panel can be anchored in either the 3D view or the Image editor.

**Tech Stack:** Blender 5.1.2 Python API (`bpy`), the existing IOPS GPU widget framework (`ui/widgets`, `widgets/composed.py`), pytest for pure-logic tests.

## Global Constraints

- Pure-logic modules (`widgets/*.py` helpers, `widgets/composed.py`) MUST stay importable without `bpy` — defer every `bpy`/`bmesh` import to call time. Tests run under plain pytest with no Blender.
- bpy-bound wiring (`ui/widgets/state.py`, `ui/widgets/events.py`, operators, property registration) is **live-verified in Blender 5.1.2**, matching the repo convention: there are no `test_state.py`/`test_events.py` — pure logic is unit-tested, bpy wiring is verified live.
- Existing single-space widgets (`space: "VIEW_3D"`) MUST keep working unchanged; a bare string `space` is normalized to a 1-element set.
- Slot assignments are **session-only** (on `WindowManager`); never written to the `.blend`.
- Image identity is tracked by **name** (`bpy.data.images[name]`), not index — survives image-list reordering. The enum sentinel for "no image" is the empty string `""` at index 0.
- Dev reload: after Python changes, purge `sys.modules` of `InteractionOps.*` before re-enabling the addon (submodule stale-cache `ImportError` otherwise). Reload infra lives on the `B:` symlink (blinker port 9902).
- Commit message trailer for every commit:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

### Task 1: Pure slot name↔index helpers

**Files:**
- Create: `widgets/uv_slots_logic.py`
- Test: `tests/ui/widgets/test_uv_slots.py`

**Interfaces:**
- Produces:
  - `SENTINEL: str` — the empty-string identifier meaning "no image" (index 0).
  - `index_of_name(idents: list[str], name: str) -> int` — index of `name` in `idents`, or `0` when absent/empty.
  - `name_at_index(idents: list[str], index: int) -> str` — identifier at `index`, or `SENTINEL` when out of range.
- Consumes: nothing.

- [ ] **Step 1: Write the failing tests**

Create `tests/ui/widgets/test_uv_slots.py`:

```python
"""Pure-logic tests for widgets/uv_slots_logic.py — the name<->index
mapping behind the UV image slot enum. No bpy needed."""
import importlib
import os
import sys

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__),
                                      "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

logic = importlib.import_module("widgets.uv_slots_logic")


def test_index_of_present_name():
    assert logic.index_of_name(["", "imgA", "imgB"], "imgB") == 2


def test_index_of_absent_name_is_sentinel():
    assert logic.index_of_name(["", "imgA"], "gone") == 0


def test_index_of_empty_name_is_sentinel():
    assert logic.index_of_name(["", "imgA"], "") == 0


def test_name_at_valid_index():
    assert logic.name_at_index(["", "imgA", "imgB"], 1) == "imgA"


def test_name_at_out_of_range_is_sentinel():
    assert logic.name_at_index(["", "imgA"], 9) == logic.SENTINEL
    assert logic.name_at_index(["", "imgA"], -1) == logic.SENTINEL
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/ui/widgets/test_uv_slots.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'widgets.uv_slots_logic'`.

- [ ] **Step 3: Write the minimal implementation**

Create `widgets/uv_slots_logic.py`:

```python
"""Pure (bpy-free) name<->index helpers for the UV image slots widget.

The slot enum's items are [SENTINEL] + the current bpy.data.images names;
the durable store is a StringProperty holding the selected image name.
These helpers map between the stored name and the enum's integer index
WITHOUT bpy, so they are unit-testable. SENTINEL ("") is index 0 = "no
image", which keeps the enum non-empty even when the file has no images.
"""
SENTINEL = ""


def index_of_name(idents, name):
    """Index of `name` in `idents`, or 0 (the sentinel) when absent/empty."""
    try:
        return idents.index(name)
    except ValueError:
        return 0


def name_at_index(idents, index):
    """Identifier at `index`, or SENTINEL when out of range."""
    if 0 <= index < len(idents):
        return idents[index]
    return SENTINEL
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/ui/widgets/test_uv_slots.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add widgets/uv_slots_logic.py tests/ui/widgets/test_uv_slots.py
git commit -m "feat(widgets): pure slot name<->index helpers for UV image slots

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Multi-space support — `Widget.spaces` + list-valued `space` validation

**Files:**
- Modify: `ui/widgets/__init__.py` (add `spaces` property to `Widget`, ~after line 58)
- Modify: `widgets/composed.py` (add `WIDGET_SPACES` + `clean_spaces`; use in `validate_def` at line 504)
- Modify: `ai_skills/iops-custom-widgets/schema-reference.md:18`
- Test: `tests/ui/widgets/test_composed.py` (append cases), `tests/ui/widgets/test_widget_rows.py` (append `spaces` cases) — see note below

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `Widget.spaces -> frozenset[str]` — normalized set of the widget's space types (string `space` → 1-set; list/tuple/set → set).
  - `composed.WIDGET_SPACES: tuple[str, ...]` = `("VIEW_3D", "IMAGE_EDITOR")`.
  - `composed.clean_spaces(raw) -> list[str]` — validated, de-duped, order-preserving list of valid space types; `["VIEW_3D"]` when empty/all-invalid.
  - `validate_def(...)["space"]` is now a **list** of valid space-type strings.

- [ ] **Step 1: Write the failing tests**

Append to `tests/ui/widgets/test_composed.py`:

```python
def test_clean_spaces_defaults_to_view3d():
    assert composed.clean_spaces(None) == ["VIEW_3D"]
    assert composed.clean_spaces("") == ["VIEW_3D"]


def test_clean_spaces_accepts_string():
    assert composed.clean_spaces("IMAGE_EDITOR") == ["IMAGE_EDITOR"]


def test_clean_spaces_accepts_list():
    assert composed.clean_spaces(["VIEW_3D", "IMAGE_EDITOR"]) == \
        ["VIEW_3D", "IMAGE_EDITOR"]


def test_clean_spaces_drops_invalid_and_dedupes():
    assert composed.clean_spaces(["VIEW_3D", "BOGUS", "VIEW_3D"]) == ["VIEW_3D"]


def test_clean_spaces_all_invalid_falls_back():
    assert composed.clean_spaces(["NOPE"]) == ["VIEW_3D"]


def test_validate_def_space_list():
    clean, errors = composed.validate_def({
        "name": "x", "space": ["VIEW_3D", "IMAGE_EDITOR"],
        "rows": [],
    })
    assert clean["space"] == ["VIEW_3D", "IMAGE_EDITOR"]


def test_validate_def_space_string_normalized_to_list():
    clean, _ = composed.validate_def({"name": "x", "rows": []})
    assert clean["space"] == ["VIEW_3D"]
```

Append to `tests/ui/widgets/test_widget_rows.py` (it already imports `Widget` from `ui.widgets`; mirror its import style):

```python
def test_widget_spaces_from_string():
    class W(Widget):
        name = "w_str"
        space = "VIEW_3D"
    assert W().spaces == frozenset({"VIEW_3D"})


def test_widget_spaces_from_list():
    class W(Widget):
        name = "w_list"
        space = ["VIEW_3D", "IMAGE_EDITOR"]
    assert W().spaces == frozenset({"VIEW_3D", "IMAGE_EDITOR"})
```

> If `test_widget_rows.py` does not already import `Widget`, add
> `from ui.widgets import Widget` near its other imports (it is bpy-free
> importable). Check the file's existing import block first.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/ui/widgets/test_composed.py tests/ui/widgets/test_widget_rows.py -v`
Expected: FAIL — `AttributeError: module 'widgets.composed' has no attribute 'clean_spaces'` and `AttributeError: 'W' object has no attribute 'spaces'`.

- [ ] **Step 3a: Add `spaces` property to `Widget`**

In `ui/widgets/__init__.py`, inside class `Widget`, add this property immediately after the `poll` method (after line 58):

```python
    @property
    def spaces(self):
        """Normalized set of editor space types this widget can live in.
        `space` may be a single string or an iterable of strings."""
        sp = self.space
        if isinstance(sp, str):
            return frozenset((sp,))
        return frozenset(sp)
```

- [ ] **Step 3b: Add `WIDGET_SPACES` + `clean_spaces` to composed.py**

In `widgets/composed.py`, after the `BOOL_TARGETS` line (line 39), add:

```python
# Editor space types a widget panel may anchor in. Kept as a plain tuple
# (composed.py is bpy-free) — must stay in sync with ui/widgets/state.py
# SPACE_TYPES.
WIDGET_SPACES = ("VIEW_3D", "IMAGE_EDITOR")
```

Then add this pure helper next to the other pure helpers (e.g. after `parse_values`, around line 92):

```python
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
```

> `_as_str_list` (defined later in the file, line ~123) upper-cases and
> trims — space types are already upper-case so this is a no-op for valid
> input. It is referenced at call time, so its definition order does not
> matter.

- [ ] **Step 3c: Use `clean_spaces` in `validate_def`**

In `widgets/composed.py`, replace line 504:

```python
        "space": "VIEW_3D",   # IMAGE_EDITOR widgets come later (spec)
```

with:

```python
        "space": clean_spaces(data.get("space")),
```

- [ ] **Step 3d: Update the schema doc**

In `ai_skills/iops-custom-widgets/schema-reference.md`, replace line 18:

```
| `space` | str | no | Editor space. Only `"VIEW_3D"` is supported; always forced to it. |
```

with:

```
| `space` | str or list of str | no | Editor space(s) the panel can anchor in: `"VIEW_3D"` and/or `"IMAGE_EDITOR"`. A string or a list is accepted; unknown values are dropped; defaults to `"VIEW_3D"`. A multi-space widget anchors to whichever listed editor it is toggled from (one at a time). |
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/ui/widgets/test_composed.py tests/ui/widgets/test_widget_rows.py -v`
Expected: PASS (all, including the existing cases — confirm no regressions).

- [ ] **Step 5: Commit**

```bash
git add ui/widgets/__init__.py widgets/composed.py ai_skills/iops-custom-widgets/schema-reference.md tests/ui/widgets/test_composed.py tests/ui/widgets/test_widget_rows.py
git commit -m "feat(widgets): multi-space widgets (Widget.spaces + list-valued space)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Wire IMAGE_EDITOR into the framework (state + events)

**Files:**
- Modify: `ui/widgets/state.py` (`SPACE_TYPES`, `_area_exists`, `find_largest_area`, `_resolve_anchor`, `widgets_in_area`, `ensure_draw_handler`)
- Modify: `ui/widgets/events.py` (anchor match, cursor-summon, `register_keymap`)

**Interfaces:**
- Consumes: `Widget.spaces` (Task 2).
- Produces:
  - `state.SPACE_TYPES` includes `"IMAGE_EDITOR"`.
  - `state.find_largest_area(space)` and `state._area_exists(ptr, space)` accept a single space string OR an iterable of space strings.
  - An `"Image"` (IMAGE_EDITOR) keymap entry for `iops.widget_interact`, registered alongside the `"3D View"` one by `register_keymap()`.

> This task is bpy-bound; per Global Constraints it is **live-verified**, not unit-tested.

- [ ] **Step 1: Add IMAGE_EDITOR to `SPACE_TYPES`**

In `ui/widgets/state.py`, replace lines 45-48:

```python
# Space-type parameterization (spec: IMAGE_EDITOR widgets can come later).
SPACE_TYPES = {
    "VIEW_3D": bpy.types.SpaceView3D,
}
```

with:

```python
# Space-type parameterization. Each entry: area.type -> the bpy Space
# subclass the POST_PIXEL draw handler attaches to. Keep in sync with
# widgets/composed.py WIDGET_SPACES.
SPACE_TYPES = {
    "VIEW_3D": bpy.types.SpaceView3D,
    "IMAGE_EDITOR": bpy.types.SpaceImageEditor,
}
```

- [ ] **Step 2: Make `find_largest_area` + `_area_exists` accept a space set**

In `ui/widgets/state.py`, replace `_area_exists` (lines 126-137):

```python
def _area_exists(ptr, space):
    """True when the area with pointer `ptr` still exists AND is still of
    `space` type — the user switching the anchored area to another editor
    counts as the anchor disappearing (so the widget re-anchors instead
    of drawing nowhere)."""
    if not ptr:
        return False
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.as_pointer() == ptr:
                return area.type == space
    return False
```

with:

```python
def _area_exists(ptr, space):
    """True when the area with pointer `ptr` still exists AND is still one
    of `space` (a single space-type string or an iterable of them) — the
    user switching the anchored area to another editor counts as the
    anchor disappearing (so the widget re-anchors instead of drawing
    nowhere)."""
    if not ptr:
        return False
    spaces = {space} if isinstance(space, str) else set(space)
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.as_pointer() == ptr:
                return area.type in spaces
    return False
```

Then replace `find_largest_area` (lines 140-156):

```python
def find_largest_area(space="VIEW_3D"):
    """Largest open area of `space` type that has a WINDOW region, or None.
    The re-anchor fallback when a widget's summon area disappears."""
    best = None
    biggest = 0
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type != space:
                continue
            size = area.width * area.height
            if size <= biggest:
                continue
            if not any(r.type == "WINDOW" for r in area.regions):
                continue
            best = area
            biggest = size
    return best
```

with:

```python
def find_largest_area(space="VIEW_3D"):
    """Largest open area among `space` (a single space-type string or an
    iterable of them) that has a WINDOW region, or None. The re-anchor
    fallback when a widget's summon area disappears."""
    spaces = {space} if isinstance(space, str) else set(space)
    best = None
    biggest = 0
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type not in spaces:
                continue
            size = area.width * area.height
            if size <= biggest:
                continue
            if not any(r.type == "WINDOW" for r in area.regions):
                continue
            best = area
            biggest = size
    return best
```

- [ ] **Step 3: Use the widget's space set in anchor resolution + area matching**

In `ui/widgets/state.py`, in `_resolve_anchor` (lines 166-168), replace:

```python
        if _area_exists(anchor, widget.space):
            return False
        largest = find_largest_area(widget.space)
```

with:

```python
        if _area_exists(anchor, widget.spaces):
            return False
        largest = find_largest_area(widget.spaces)
```

In `widgets_in_area` (line 186), replace:

```python
        if widget is None or widget.space != area.type:
            continue
```

with:

```python
        if widget is None or area.type not in widget.spaces:
            continue
```

- [ ] **Step 4: Install a draw handler per space the widget uses**

In `ui/widgets/state.py`, replace `ensure_draw_handler`'s collection loop (lines 316-323):

```python
    from . import get_widget
    needed = set()
    for name, st in _states.items():
        if not st.get("visible"):
            continue
        widget = get_widget(name)
        if widget is not None and widget.space in SPACE_TYPES:
            needed.add(widget.space)
```

with:

```python
    from . import get_widget
    needed = set()
    for name, st in _states.items():
        if not st.get("visible"):
            continue
        widget = get_widget(name)
        if widget is None:
            continue
        for sp in widget.spaces:
            if sp in SPACE_TYPES:
                needed.add(sp)
```

- [ ] **Step 5: Multi-space anchor match + cursor-summon in events.py**

In `ui/widgets/events.py`, in `_toggle` (line 68), replace:

```python
            if area is None or area.type != widget.space:
                area = state.find_largest_area(widget.space)
```

with:

```python
            if area is None or area.type not in widget.spaces:
                area = state.find_largest_area(widget.spaces)
```

In `invoke` (line 96), replace:

```python
                and context.area.type == "VIEW_3D"):
```

with:

```python
                and context.area.type in state.SPACE_TYPES):
```

- [ ] **Step 6: Register the IMAGE_EDITOR keymap alongside the 3D View one**

In `ui/widgets/events.py`, replace `register_keymap` (lines 490-518) entirely with:

```python
def _ensure_interact_kmi(kc, keymap_name, space_type):
    """Add the LEFTMOUSE PRESS any=True -> iops.widget_interact entry to
    `keymap_name` if it isn't there already. any=True: fires with every
    modifier so Ctrl (smooth slider drag) reaches the modal; off-panel
    clicks PASS_THROUGH."""
    km = kc.keymaps.new(keymap_name, space_type=space_type)
    for kmi in km.keymap_items:
        if kmi.idname == IOPS_OT_widget_interact.bl_idname:
            return
    kmi = km.keymap_items.new(IOPS_OT_widget_interact.bl_idname,
                              "LEFTMOUSE", "PRESS", any=True)
    _keymap_items.append((km, kmi))


# Keymaps that legitimately host the interact entry (name -> space_type).
_INTERACT_KEYMAPS = (
    ("3D View", "VIEW_3D"),
    ("Image", "IMAGE_EDITOR"),
)


def register_keymap():
    """Single registration at addon register (guarded — re-running is a
    no-op, matching the register_ui_toggle_keymaps pattern)."""
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:
        return
    legit = {name for name, _ in _INTERACT_KEYMAPS}
    # Hotkey files saved before iops.widget_interact was excluded from
    # save_hotkeys may have re-created the entry in other addon keymaps
    # ("Window", without any=True) — sweep those strays first so the user
    # never ends up with a duplicate global LMB binding.
    for other in kc.keymaps:
        if other.name in legit:
            continue
        stray = [kmi for kmi in other.keymap_items
                 if kmi.idname == IOPS_OT_widget_interact.bl_idname]
        for kmi in stray:
            other.keymap_items.remove(kmi)
    for name, space_type in _INTERACT_KEYMAPS:
        _ensure_interact_kmi(kc, name, space_type)
    print("IOPS Widget keymap registered")
```

> `unregister_keymap()` (line 521) already removes every entry recorded in
> `_keymap_items`, so it cleans up both keymaps with no change.
> `operators/hotkeys/load_hotkeys.py:_reload_keymaps` calls
> `widget_events.register_keymap()`, so reload re-registers both keymaps
> automatically — no change needed there. (Verified.)

- [ ] **Step 7: Live-verify in Blender 5.1.2**

Reload the addon via the dev infra (purge `sys.modules` of `InteractionOps.*`, re-enable). Then, with the MCP `execute_blender_code` tool, confirm wiring is present (no widget toggled yet — this just checks registration):

```python
import bpy
from InteractionOps.ui.widgets import state
print("IMAGE_EDITOR in SPACE_TYPES:", "IMAGE_EDITOR" in state.SPACE_TYPES)
kc = bpy.context.window_manager.keyconfigs.addon
names = {km.name for km in kc.keymaps
         for kmi in km.keymap_items
         if kmi.idname == "iops.widget_interact"}
print("interact keymaps:", names)  # expect {'3D View', 'Image'}
```

Expected console: `IMAGE_EDITOR in SPACE_TYPES: True` and `interact keymaps: {'3D View', 'Image'}`.

> Full toggle/render verification happens in Task 5 once the widget exists.

- [ ] **Step 8: Commit**

```bash
git add ui/widgets/state.py ui/widgets/events.py
git commit -m "feat(widgets): IMAGE_EDITOR support — multi-space anchor, draw handler, keymap

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Slot properties + flip operator

**Files:**
- Create: `operators/uv_image_slots.py`
- Modify: `__init__.py` (import the operator class into `classes`; call register/unregister of the slot props)

**Interfaces:**
- Consumes: `widgets.uv_slots_logic.index_of_name`, `name_at_index`, `SENTINEL` (Task 1); `ui.widgets.state.find_largest_area` (Task 3).
- Produces:
  - `SLOT_COUNT = 3`.
  - WindowManager props (per slot N in 0..2): `iops_uv_slot_N` (EnumProperty, dynamic items, get/set bridged to the name string) and `iops_uv_slot_N_name` (StringProperty, the durable store).
  - Operator `iops.uv_image_slot_flip` with `slot: IntProperty`.
  - `register_slot_props()` / `unregister_slot_props()`.
  - `IOPS_OT_uv_image_slot_flip` (class, for the `classes` tuple).

- [ ] **Step 1: Write the operator + property module**

Create `operators/uv_image_slots.py`:

```python
"""UV image slots: per-slot WindowManager properties + the one-click flip
operator behind presets/IOPS/widgets/uv_image_slots.json.

Each slot stores an image NAME in a session-only StringProperty
(iops_uv_slot_N_name) on WindowManager — never written to the .blend. A
companion dynamic EnumProperty (iops_uv_slot_N) is what the DROPDOWN binds
to: its items are [SENTINEL] + the current bpy.data.images names, and its
get/set are bridged to the name string so the stored choice survives
image-list reordering (a raw dynamic enum would store a fragile index).

The flip operator reads a slot's stored name and sets it as the active
image of an Image/UV editor — the invoking one if the click happened
there, otherwise the largest Image editor open in the window (so it works
when toggled from the 3D viewport).
"""
import bpy
from bpy.props import EnumProperty, IntProperty, StringProperty

from ..widgets.uv_slots_logic import index_of_name, name_at_index, SENTINEL

SLOT_COUNT = 3

# Module-level anchor for the most recent enum-items list per slot. Blender
# can garbage-collect the strings returned by a dynamic-enum items callback
# and crash; keeping a reference alive is the standard guard.
_items_cache = {}


def _slot_idents():
    """Identifier list for the slot enums: SENTINEL first, then every image
    name in bpy.data.images order."""
    return [SENTINEL] + [img.name for img in bpy.data.images]


def _make_items(slot):
    def items(self, context):
        idents = _slot_idents()
        built = []
        for ident in idents:
            if ident == SENTINEL:
                built.append((SENTINEL, "— none —", "No image"))
            else:
                built.append((ident, ident, ident))
        _items_cache[slot] = built   # keep refs alive (anti-GC)
        return built
    return items


def _make_get(slot):
    name_attr = "iops_uv_slot_%d_name" % slot

    def get(self):
        return index_of_name(_slot_idents(), getattr(self, name_attr, ""))
    return get


def _make_set(slot):
    name_attr = "iops_uv_slot_%d_name" % slot

    def set(self, value):
        setattr(self, name_attr, name_at_index(_slot_idents(), value))
    return set


def register_slot_props():
    """Define the per-slot WindowManager properties. Idempotent-ish:
    re-assigning a bpy property just replaces it."""
    for slot in range(SLOT_COUNT):
        setattr(bpy.types.WindowManager, "iops_uv_slot_%d_name" % slot,
                StringProperty(
                    name="UV Slot %d Image" % slot,
                    description="Stored image name for UV image slot %d" % slot,
                    default="",
                    options={"SKIP_SAVE"},
                ))
        setattr(bpy.types.WindowManager, "iops_uv_slot_%d" % slot,
                EnumProperty(
                    name="UV Slot %d" % slot,
                    description="Image assigned to UV image slot %d" % slot,
                    items=_make_items(slot),
                    get=_make_get(slot),
                    set=_make_set(slot),
                    options={"SKIP_SAVE"},
                ))


def unregister_slot_props():
    for slot in range(SLOT_COUNT):
        for attr in ("iops_uv_slot_%d" % slot, "iops_uv_slot_%d_name" % slot):
            if hasattr(bpy.types.WindowManager, attr):
                delattr(bpy.types.WindowManager, attr)
    _items_cache.clear()


def _target_image_space(context):
    """The SpaceImageEditor to retarget: the invoking editor when the click
    happened in one, else the largest Image editor open in the window.
    None when no Image/UV editor is open."""
    sd = context.space_data
    if sd is not None and getattr(sd, "type", None) == "IMAGE_EDITOR":
        return sd
    from ..ui.widgets import state
    area = state.find_largest_area("IMAGE_EDITOR")
    if area is None:
        return None
    return area.spaces.active


class IOPS_OT_uv_image_slot_flip(bpy.types.Operator):
    """Set the UV/Image editor's active image to the one stored in this slot"""

    bl_idname = "iops.uv_image_slot_flip"
    bl_label = "IOPS UV Image Slot Flip"
    bl_options = {"REGISTER", "UNDO"}

    slot: IntProperty(name="Slot", default=0, min=0)

    def execute(self, context):
        wm = context.window_manager
        name = getattr(wm, "iops_uv_slot_%d_name" % self.slot, "")
        if not name:
            self.report({"INFO"}, "IOPS: slot %d is empty" % self.slot)
            return {"CANCELLED"}
        img = bpy.data.images.get(name)
        if img is None:
            self.report({"INFO"}, "IOPS: slot image '%s' not found" % name)
            return {"CANCELLED"}
        space = _target_image_space(context)
        if space is None:
            self.report({"INFO"}, "IOPS: no UV/Image editor open")
            return {"CANCELLED"}
        space.image = img
        return {"FINISHED"}


classes = (IOPS_OT_uv_image_slot_flip,)
```

- [ ] **Step 2: Register the operator class + slot props in the root `__init__.py`**

In `__init__.py`, add the import near the other operator imports (e.g. after the `widgets_panel` import at line 211):

```python
from .operators.uv_image_slots import classes as _uv_image_slots_classes
```

Add the classes to the `classes` tuple (near the widget panel entries around line 524):

```python
    *_uv_image_slots_classes,
```

In `register()`, register the slot props right after the `WindowManager.IOPS_AddonProperties` assignment (after line 600):

```python
    from .operators.uv_image_slots import register_slot_props
    register_slot_props()
```

In `unregister()`, unregister them just before `del bpy.types.WindowManager.IOPS_AddonProperties` (before line 695):

```python
    try:
        from .operators.uv_image_slots import unregister_slot_props
        unregister_slot_props()
    except Exception as e:
        print("IOPS: UV image slot props unregister failed:", e)
```

- [ ] **Step 3: Live-verify the operator + props**

Reload the addon (purge `sys.modules` of `InteractionOps.*`, re-enable). With `execute_blender_code`:

```python
import bpy
wm = bpy.context.window_manager
# Props exist
print("has slot0 enum:", hasattr(wm, "iops_uv_slot_0"))
print("has slot0 name:", hasattr(wm, "iops_uv_slot_0_name"))
# Make a couple of test images so the enum has items
for n in ("slotTestA", "slotTestB"):
    if n not in bpy.data.images:
        bpy.data.images.new(n, 8, 8)
# Assign by NAME (the path the DROPDOWN uses: setattr identifier)
wm.iops_uv_slot_0 = "slotTestA"
print("slot0 name stored:", wm.iops_uv_slot_0_name)      # expect slotTestA
print("slot0 enum reads:", wm.iops_uv_slot_0)            # expect slotTestA
# Empty slot flip -> CANCELLED/INFO (slot 2 untouched)
print("flip empty:", bpy.ops.iops.uv_image_slot_flip(slot=2))
```

Expected: both `has...` True; `slot0 name stored: slotTestA`; `slot0 enum reads: slotTestA`; `flip empty: {'CANCELLED'}`.

Then verify a real flip into an Image editor. Ensure an Image/UV editor area is open (split the viewport if needed), then run via the MCP CLI helper or override context:

```python
import bpy
wm = bpy.context.window_manager
area = next((a for w in wm.windows for a in w.screen.areas
             if a.type == "IMAGE_EDITOR"), None)
assert area is not None, "open an Image/UV editor first"
region = next(r for r in area.regions if r.type == "WINDOW")
with bpy.context.temp_override(area=area, region=region,
                               space_data=area.spaces.active):
    print("flip:", bpy.ops.iops.uv_image_slot_flip(slot=0))
print("active image now:", area.spaces.active.image and area.spaces.active.image.name)
```

Expected: `flip: {'FINISHED'}` and `active image now: slotTestA`.

Clean up test images:

```python
import bpy
for n in ("slotTestA", "slotTestB"):
    img = bpy.data.images.get(n)
    if img:
        bpy.data.images.remove(img)
```

- [ ] **Step 4: Commit**

```bash
git add operators/uv_image_slots.py __init__.py
git commit -m "feat(widgets): UV image slot props + iops.uv_image_slot_flip operator

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: The widget JSON + end-to-end verification

**Files:**
- Create: `presets/IOPS/widgets/uv_image_slots.json`
  - (dev source path on the symlink: `B:\scripts\presets\iops\widgets\uv_image_slots.json` — the same file; create it at the repo path and it is served via the `B:` symlink)

**Interfaces:**
- Consumes: the DROPDOWN/BUTTON composer (`widgets/composed.py`), list-valued `space` (Task 2), the slot props + flip operator (Task 4).
- Produces: a registered composed widget named `uv_image_slots`.

- [ ] **Step 1: Create the widget definition**

Create `presets/IOPS/widgets/uv_image_slots.json`:

```json
{
  "version": 1,
  "name": "uv_image_slots",
  "title": "UV Image Slots",
  "space": ["VIEW_3D", "IMAGE_EDITOR"],
  "rows": [
    { "type": "SECTION", "label": "UV Image Slots" },
    { "type": "ROW", "cells": [
      { "type": "DROPDOWN", "prop": "window_manager.iops_uv_slot_0", "label": "1" },
      { "type": "BUTTON", "label": "Set", "op": "iops.uv_image_slot_flip", "op_kwargs": { "slot": 0 } }
    ]},
    { "type": "ROW", "cells": [
      { "type": "DROPDOWN", "prop": "window_manager.iops_uv_slot_1", "label": "2" },
      { "type": "BUTTON", "label": "Set", "op": "iops.uv_image_slot_flip", "op_kwargs": { "slot": 1 } }
    ]},
    { "type": "ROW", "cells": [
      { "type": "DROPDOWN", "prop": "window_manager.iops_uv_slot_2", "label": "3" },
      { "type": "BUTTON", "label": "Set", "op": "iops.uv_image_slot_flip", "op_kwargs": { "slot": 2 } }
    ]}
  ]
}
```

> The DROPDOWN `prop` resolves against `context` (`resolve_rna_owner`), so
> `window_manager.iops_uv_slot_N` reaches `context.window_manager.iops_uv_slot_N`.
> DROPDOWN forces `value_type=ENUM`; with no `labels`, items come live from
> the enum (`rna_enum_items` → our items callback). Selecting writes the
> identifier via `rna_value_adapter` (ENUM → `setattr(wm, attr, name)`),
> which routes through the enum `set` and stores the name. The BUTTON runs
> the flip operator with the slot index.

- [ ] **Step 2: Live-verify load + validation**

Reload the addon (purge `sys.modules` of `InteractionOps.*`, re-enable so the new JSON is picked up by `composed.load_all()` + `widget_composer.sync_from_files()` in `register()`). With `execute_blender_code`:

```python
import bpy
from InteractionOps.ui.widgets import get_widget
w = get_widget("uv_image_slots")
print("registered:", w is not None)
print("spaces:", None if w is None else set(w.spaces))
```

Expected: `registered: True` and `spaces: {'VIEW_3D', 'IMAGE_EDITOR'}`.

If `w is None`, re-run `sync_from_files()` and inspect printed validation errors:

```python
from InteractionOps.widgets import composed
from InteractionOps.prefs import widget_composer
print(composed.load_all())     # {filename: [errors]} — should be {} or no entry for ours
widget_composer.sync_from_files()
```

- [ ] **Step 3: Manual end-to-end check (human, in Blender)**

Perform and confirm each (this is the gesture path the MCP cannot inject):

1. Create/append 3 images in the file.
2. In the **3D viewport**, toggle the `uv_image_slots` widget (assign its toggle hotkey in the Widgets prefs tab, or call `bpy.ops.iops.widget_toggle(name="uv_image_slots")`). Panel appears in the 3D view.
3. Open a UV/Image editor area. Toggle the widget there — panel appears in the Image editor too (one at a time, anchored where toggled).
4. In each slot's dropdown pick a different image; the dropdown shows the chosen name.
5. Click **Set** on slot 1, then slot 2, then slot 3 — the Image editor's active image flips each time, in one click. Verify it works both when the panel is in the 3D view (targets the open Image editor) and when it's in the Image editor (targets itself).
6. Delete an image assigned to a slot; click its Set — graceful no-op (status bar INFO "slot image '…' not found"), no error, the dropdown falls back to "— none —".
7. Reload the addon via dev infra; confirm both the `"3D View"` and `"Image"` interact keymaps re-register and the widget still toggles in both editors.

Record the outcome (pass/fail per step) in the PR description.

- [ ] **Step 4: Commit**

```bash
git add presets/IOPS/widgets/uv_image_slots.json
git commit -m "feat(widgets): UV Image Slots widget JSON (3 slots, dual-space)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Framework multi-space support → Tasks 2 (Widget.spaces, validation) + 3 (state/events/keymap). ✓
- Session-only WM state (StringProperty + dynamic enum bridge) → Task 4, `options={"SKIP_SAVE"}`. ✓
- Flip operator targeting current-or-remote Image editor → Task 4 (`_target_image_space`). ✓
- Pure-JSON 3-slot widget, DROPDOWN + flip BUTTON, list-valued `space` → Task 5. ✓
- Enum/string bridge rationale + anti-GC items reference → Task 4. ✓
- INFO no-op on empty/deleted/no-editor → Task 4 operator. ✓
- Schema doc update for list-valued `space` → Task 2. ✓
- Tests mirror `tests/ui/widgets` pure-logic convention; bpy wiring live-verified → Tasks 1-2 unit, 3-5 live. ✓
- Out-of-scope items (generic ref system, cross-file persistence, configurable count) → not implemented. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every command has expected output. ✓

**Type consistency:** `index_of_name`/`name_at_index`/`SENTINEL` defined in Task 1, consumed by Task 4 with matching signatures. `Widget.spaces` defined in Task 2, consumed in Task 3 (`widget.spaces`). `find_largest_area(space)` accepts str or iterable (Task 3), called with a string `"IMAGE_EDITOR"` in Task 4 and with `widget.spaces` in Task 3 — both valid. `iops.uv_image_slot_flip(slot=...)` defined Task 4, referenced in Task 5 JSON. ✓
