# Widgets Per-File UI State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each .blend remembers its own set of open GPU widgets (visibility, panel positions, switches), snapshotted at save time into `Scene.IOPS.widgets_ui_state` and restored on file load; the global prefs `widgets_state` persistence is removed.

**Architecture:** A new pure module `ui/widgets/persistence.py` serializes/parses the state JSON (pytest-covered, no bpy). `ui/widgets/state.py` swaps its prefs read/write for a `save_pre` snapshot written to every scene and a `load_post` wholesale restore from the window scene. The prefs StringProperty and its prefs-JSON round-trip are deleted.

**Tech Stack:** Python, Blender `bpy` (deferred/defensive in live paths), pytest for pure modules.

**Spec:** `docs/superpowers/specs/2026-07-21-widgets-per-file-state-design.md`

## Global Constraints

- Pure modules (`ui/widgets/persistence.py`, everything already pytest-imported) must import WITHOUT bpy.
- All bpy-side scene access is defensive: missing `Scene.IOPS` / property → silent no-op, framework degrades to session-only state.
- No writes to scene data outside `save_pre` — except `unregister()` (dev-reload survival, deliberately accepted).
- A file with no stored record opens with ALL widgets closed. No prefs fallback.
- Repo is public: commit messages name no proprietary projects.
- The working tree has unrelated WIP (`__init__.py`, `docs/ui/ui_pies.md`, `operators/object_uvmaps_add_remove.py`, `ui/iops_pie_edit.py`) — `git add` ONLY the files each task names, never `git add -A`.

---

### Task 1: Pure persistence module

**Files:**
- Create: `ui/widgets/persistence.py`
- Test: `tests/ui/widgets/test_persistence.py`

**Interfaces:**
- Consumes: nothing (stdlib json only).
- Produces: `dumps_states(states: dict) -> str` and `parse_states(raw: str) -> dict` plus constants `DEFAULT_X = 80.0`, `DEFAULT_Y = 400.0`. Task 2 imports these into `ui/widgets/state.py`. `parse_states` entries always contain keys `visible` (bool), `x`/`y` (float), `anchor_area_ptr` (always 0), `switches` (dict[str, bool]).

- [ ] **Step 1: Write the failing tests**

Create `tests/ui/widgets/test_persistence.py` (import style matches `tests/ui/widgets/test_controls.py`, which imports `ui.widgets.*` directly):

```python
"""Pure-pytest tests for ui/widgets/persistence.py — per-file widget UI
state serialization. No bpy."""
from ui.widgets.persistence import (dumps_states, parse_states,
                                    DEFAULT_X, DEFAULT_Y)
import json


def test_round_trip_preserves_visible_xy_switches():
    states = {"w1": {"visible": True, "x": 10.5, "y": 20.0,
                     "anchor_area_ptr": 12345,
                     "switches": {"a": True, "b": False}},
              "w2": {"visible": False, "x": 1.0, "y": 2.0, "switches": {}}}
    out = parse_states(dumps_states(states))
    assert out["w1"]["visible"] is True
    assert out["w1"]["x"] == 10.5 and out["w1"]["y"] == 20.0
    assert out["w1"]["switches"] == {"a": True, "b": False}
    assert out["w2"]["visible"] is False


def test_dumps_strips_runtime_only_keys():
    states = {"w1": {"visible": True, "x": 1.0, "y": 2.0,
                     "anchor_area_ptr": 999, "switches": {}}}
    data = json.loads(dumps_states(states))
    assert "anchor_area_ptr" not in data["w1"]


def test_parse_resets_anchor_to_zero():
    raw = json.dumps({"w1": {"visible": True, "x": 1, "y": 2,
                             "anchor_area_ptr": 777}})
    assert parse_states(raw)["w1"]["anchor_area_ptr"] == 0


def test_parse_malformed_json_returns_empty():
    assert parse_states("not json {") == {}
    assert parse_states("") == {}
    assert parse_states(None) == {}


def test_parse_non_dict_top_level_returns_empty():
    assert parse_states("[1, 2, 3]") == {}
    assert parse_states('"str"') == {}


def test_parse_skips_non_dict_entries():
    raw = json.dumps({"good": {"visible": True}, "bad": [1, 2]})
    out = parse_states(raw)
    assert "good" in out and "bad" not in out


def test_parse_missing_keys_get_defaults():
    out = parse_states(json.dumps({"w": {}}))["w"]
    assert out["visible"] is False
    assert out["x"] == DEFAULT_X and out["y"] == DEFAULT_Y
    assert out["switches"] == {} and out["anchor_area_ptr"] == 0


def test_parse_unparseable_xy_falls_back_to_defaults():
    raw = json.dumps({"w": {"visible": True, "x": "junk", "y": None}})
    out = parse_states(raw)["w"]
    assert out["x"] == DEFAULT_X and out["y"] == DEFAULT_Y
    assert out["visible"] is True


def test_parse_coerces_switch_values_to_bool():
    raw = json.dumps({"w": {"switches": {"s1": 1, "s2": 0, "s3": "x"}}})
    out = parse_states(raw)["w"]
    assert out["switches"] == {"s1": True, "s2": False, "s3": True}


def test_parse_non_dict_switches_ignored():
    raw = json.dumps({"w": {"switches": [1, 2]}})
    assert parse_states(raw)["w"]["switches"] == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/ui/widgets/test_persistence.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ui.widgets.persistence'`

- [ ] **Step 3: Write the implementation**

Create `ui/widgets/persistence.py`:

```python
"""Pure serialization for per-file widget UI state.

The runtime states dict in ui/widgets/state.py (name -> {"visible", "x",
"y", "anchor_area_ptr", "switches"}) round-trips through a JSON string
stored per-scene in `Scene.IOPS.widgets_ui_state`. This module is
bpy-free so the round-trip is plain pytest.

`anchor_area_ptr` is runtime-only (area pointers are meaningless across
sessions): dumps strips it, parse always returns it as 0.
"""
from __future__ import annotations
import json

DEFAULT_X = 80.0
DEFAULT_Y = 400.0


def dumps_states(states):
    """Serialize runtime states to the stored JSON string. Input is the
    addon's own runtime dict — trusted; only shape normalization here."""
    data = {}
    for name, st in states.items():
        if not isinstance(st, dict):
            continue
        data[str(name)] = {
            "visible": bool(st.get("visible")),
            "x": float(st.get("x", DEFAULT_X)),
            "y": float(st.get("y", DEFAULT_Y)),
            "switches": {str(k): bool(v)
                         for k, v in st.get("switches", {}).items()},
        }
    return json.dumps(data)


def parse_states(raw):
    """Parse a stored JSON string into fresh runtime states. Hostile
    input (hand-edited .blend data, other addons): any malformed layer
    degrades — bad document to {}, bad entry skipped, bad field to its
    default. Anchors always come back 0."""
    try:
        data = json.loads(raw or "")
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    states = {}
    for name, entry in data.items():
        if not isinstance(entry, dict):
            continue
        st = {"visible": bool(entry.get("visible", False)),
              "x": DEFAULT_X, "y": DEFAULT_Y,
              "anchor_area_ptr": 0, "switches": {}}
        try:
            st["x"] = float(entry.get("x", DEFAULT_X))
            st["y"] = float(entry.get("y", DEFAULT_Y))
        except (TypeError, ValueError):
            st["x"], st["y"] = DEFAULT_X, DEFAULT_Y
        sw = entry.get("switches", {})
        if isinstance(sw, dict):
            st["switches"] = {str(k): bool(v) for k, v in sw.items()}
        states[str(name)] = st
    return states
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/ui/widgets/test_persistence.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add ui/widgets/persistence.py tests/ui/widgets/test_persistence.py
git commit -m "feat(widgets): pure serializer for per-file UI state

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Scene property + state.py rewrite (save_pre snapshot / load_post restore)

**Files:**
- Modify: `prefs/addon_properties.py` (IOPS_SceneProperties, after `widget_data`, ~line 289)
- Modify: `ui/widgets/state.py` (docstring, persistence section, handlers, register/unregister)

**Interfaces:**
- Consumes: `dumps_states` / `parse_states` from Task 1.
- Produces: `save_states_to_scenes()` and `load_states_from_scene()` in `ui/widgets/state.py`; `Scene.IOPS.widgets_ui_state` StringProperty. `save_states()` / `load_states()` / `_prefs()` / `_PREFS_ADDON_KEY` / `_PREFS_PROP` cease to exist (Task 3 removes their prefs-side counterparts).

- [ ] **Step 1: Add the scene property**

In `prefs/addon_properties.py`, directly after the `widget_data` collection inside `IOPS_SceneProperties` (after the closing paren at ~line 289), add:

```python
    # Per-.blend GPU widget UI state (ui/widgets/state.py) — JSON with
    # each widget's visibility/position/switches, snapshotted at save_pre
    # and restored at load_post. Internal storage, not drawn anywhere.
    widgets_ui_state: StringProperty(
        name="Widgets UI State",
        description="Internal: per-file GPU widget visibility/positions (JSON)",
        default="",
        options={"HIDDEN"},
    )
```

No registration-order change (plain StringProperty on an already-registered PropertyGroup; `StringProperty` is already imported at the top of the file).

- [ ] **Step 2: Rewrite the persistence section of `ui/widgets/state.py`**

2a. Replace the module docstring's persistence paragraph (lines 11–16, "Persistence: visible/x/y serialize as JSON…") with:

```
Persistence: visible/x/y/switches serialize as JSON into
`Scene.IOPS.widgets_ui_state` — per .blend, written ONLY during save_pre
(open/close/drag events never dirty the file) and restored wholesale at
load_post. A file with no stored record opens with all widgets closed.
Every access is defensive so the framework degrades to session-only
state when the property is missing.
```

2b. Replace the constants (lines 31–32):

```python
_PREFS_ADDON_KEY = "InteractionOps"
_PREFS_PROP = "widgets_state"
```

with:

```python
from .persistence import dumps_states, parse_states

_SCENE_PROP = "widgets_ui_state"
```

(keep it in the import block region; `from ..draw import ...` stays above it)

2c. In `show_widget` (line ~92) and `hide_widget` (line ~105): delete the `save_states()` lines. In `store_position` and `store_switches`: delete the `save_states()` lines and update their docstrings to `"""Record a new panel position (drag finished; runtime only — persisted at next save)."""` and `"""Record a widget's local switch state (runtime only — persisted at next save)."""`.

2d. Replace the whole persistence block (comment banner line 209 through the end of `load_states()`, line 277) with:

```python
# ----------------------------------------------------------------------
# Persistence (JSON in Scene.IOPS.widgets_ui_state — per .blend)
# ----------------------------------------------------------------------
def _refresh_runtime_states():
    """Pull live panel positions and switch maps into _states so a
    snapshot reflects what's on screen."""
    from . import get_widget
    for name, st in _states.items():
        widget = get_widget(name)
        if widget is None:
            continue
        st["x"] = float(widget.panel.x)
        st["y"] = float(widget.panel.y)
        if getattr(widget, "switches", None):
            st["switches"] = {str(k): bool(v)
                              for k, v in widget.switches.items()}


def save_states_to_scenes():
    """Snapshot runtime state into EVERY scene (multi-scene files stay
    consistent regardless of the active scene at load). Called from
    save_pre — the write lands inside the save, so no dirty flag — and
    from unregister (dev reload; may dirty, accepted)."""
    _refresh_runtime_states()
    raw = dumps_states(_states)
    try:
        scenes = list(bpy.data.scenes)
    except AttributeError:
        return
    for scene in scenes:
        iops = getattr(scene, "IOPS", None)
        if iops is None or not hasattr(iops, _SCENE_PROP):
            continue
        try:
            setattr(iops, _SCENE_PROP, raw)
        except Exception as e:
            print("IOPS widgets: scene state save failed:", e)


def load_states_from_scene():
    """Replace runtime states WHOLESALE from the window scene's stored
    JSON. Missing property / empty / invalid → all widgets closed (the
    per-file record is the only source of truth). Anchors come back 0
    so the first draw re-anchors to the largest viewport."""
    from . import get_widget
    try:
        iops = getattr(bpy.context.scene, "IOPS", None)
        raw = getattr(iops, _SCENE_PROP, "") if iops is not None else ""
    except (AttributeError, RuntimeError):
        raw = ""   # restricted context during startup registration
    _states.clear()
    _states.update(parse_states(raw))
    for name, st in _states.items():
        widget = get_widget(name)
        if widget is None:
            continue
        widget.panel.x = st["x"]
        widget.panel.y = st["y"]
        if getattr(widget, "switches", None):
            for k, v in st["switches"].items():
                if k in widget.switches:
                    widget.switches[k] = bool(v)
```

2e. Replace `_on_load_post` (lines 369–381) with:

```python
@persistent
def _on_load_post(_dummy):
    # Restore this file's widget set. Area pointers are invalid after a
    # load — parse_states returns anchors as 0, so the next draw
    # re-anchors to the largest viewport.
    global _draw_guard_logged
    _draw_error_logged.clear()
    _draw_guard_logged = False
    load_states_from_scene()
    mark_all_dirty()
    if any_visible():
        ensure_draw_handler()
    else:
        remove_draw_handler()
    tag_redraw_all()
```

2f. Add the save handler next to it:

```python
@persistent
def _on_save_pre(_dummy):
    save_states_to_scenes()
```

2g. Extend `_APP_HANDLER_SLOTS`:

```python
_APP_HANDLER_SLOTS = (
    ("load_post", _on_load_post),
    ("save_pre", _on_save_pre),
    ("depsgraph_update_post", _on_depsgraph_update),
    ("undo_post", _on_undo_redo),
    ("redo_post", _on_undo_redo),
)
```

2h. In `register()`: replace `load_states()` with `load_states_from_scene()` and update the docstring to `"""Install app handlers, restore this file's widget state, start drawing if any widget is stored visible. (Startup registration sees a restricted context — restore degrades to all-closed and the load_post that follows does the real restore.)"""`. In `unregister()`: replace `save_states()` with `save_states_to_scenes()`.

- [ ] **Step 3: Run the pure sweep (import breakage check)**

Run: `python -m pytest tests -q`
Expected: all PASS (state.py itself isn't pytest-imported, but the sweep catches accidental breakage in modules that are).

- [ ] **Step 4: Commit**

```bash
git add prefs/addon_properties.py ui/widgets/state.py
git commit -m "feat(widgets): per-file UI state via save_pre scene snapshot

Visibility/positions/switches now live in Scene.IOPS.widgets_ui_state,
written only during save (no dirtying on open/close) and restored at
load_post. No stored record means all widgets closed.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Remove the prefs `widgets_state` property and round-trip

**Files:**
- Modify: `prefs/addon_preferences.py:178-186` (delete property)
- Modify: `prefs/iops_prefs.py:183-188` (delete WIDGETS section)
- Modify: `operators/preferences/io_addon_preferences.py:289-296` (legacy-ignore case)

**Interfaces:**
- Consumes: Task 2 must land first (state.py no longer references the prefs property; removing it before Task 2 breaks `save_states`).
- Produces: nothing new — deletions only.

- [ ] **Step 1: Delete the prefs property**

In `prefs/addon_preferences.py`, delete lines 178–186 (the comment block and the `widgets_state: StringProperty(...)` declaration) entirely.

- [ ] **Step 2: Delete the WIDGETS export section**

In `prefs/iops_prefs.py`, delete the whole `"WIDGETS": {...}` entry (lines 183–188 including its comment).

- [ ] **Step 3: Turn the import case into a legacy no-op**

In `operators/preferences/io_addon_preferences.py`, replace the `case "WIDGETS":` block (lines 289–296) with:

```python
                    case "WIDGETS":
                        # Legacy section (widget UI state moved into the
                        # .blend, Scene.IOPS.widgets_ui_state) — ignored
                        # so old exported prefs JSONs load without noise.
                        pass
```

(Keeping the case prevents old prefs files from hitting the `case _` "No entry" print.)

- [ ] **Step 4: Sanity check — no references left**

Run: `grep -rn "widgets_state" --include="*.py" .`
Expected: zero matches outside `docs/` plan/spec files. (`widgets_ui_state` matches are fine — different name.)

- [ ] **Step 5: Run the pure sweep**

Run: `python -m pytest tests -q`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add prefs/addon_preferences.py prefs/iops_prefs.py operators/preferences/io_addon_preferences.py
git commit -m "refactor(prefs): drop global widgets_state storage

Superseded by per-file Scene.IOPS.widgets_ui_state. Old exported prefs
JSONs with a WIDGETS section load silently.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Documentation updates

**Files:**
- Modify: `ai_skills/iops-custom-widgets/schema-reference.md:308-309`
- Modify: `ai_skills/iops-custom-widgets/SKILL.md:75-78, 134-138, 347`

**Interfaces:** none — prose only.

- [ ] **Step 1: schema-reference.md**

Replace lines 308–309:

```
- State **persists** per-widget in the `widgets_state` prefs JSON (same file
  as panel position) and survives addon reload.
```

with:

```
- State **persists** per-widget in the .blend file (`Scene.IOPS.
  widgets_ui_state`, snapshotted at save alongside visibility and panel
  position). Each .blend keeps its own widget state; unsaved changes are
  session-only.
```

- [ ] **Step 2: SKILL.md — flipbox switch paragraph (lines 75–78)**

Replace:

```
- **`FLIPBOX` `switch`** binds a *local panel switch* — lightweight boolean
  state stored per-widget in `widgets_state` JSON (like position). The top-level
  `"switches"` map sets non-false defaults; any switch referenced but absent
  there defaults to `false`. A FLIPBOX needs EXACTLY ONE of `target`/`prop`/`switch`.
```

with:

```
- **`FLIPBOX` `switch`** binds a *local panel switch* — lightweight boolean
  state stored per-widget in the .blend (`widgets_ui_state`, like position).
  The top-level `"switches"` map sets non-false defaults; any switch
  referenced but absent there defaults to `false`. A FLIPBOX needs EXACTLY
  ONE of `target`/`prop`/`switch`.
```

- [ ] **Step 3: SKILL.md — switches section (lines 134–138)**

Replace:

```
Any switch name referenced by a `FLIPBOX` `switch` binding or a `show_if`
`switch` key defaults to `false` unless listed here. Switch state persists
per-widget in `widgets_state` JSON (same file as position) and survives
addon reload. A switch with no defining `FLIPBOX` (used only in `show_if`)
is valid — it stays at its default until changed programmatically.
```

with:

```
Any switch name referenced by a `FLIPBOX` `switch` binding or a `show_if`
`switch` key defaults to `false` unless listed here. Switch state persists
per-widget in the .blend (`Scene.IOPS.widgets_ui_state`, snapshotted at
save with position/visibility) — each file keeps its own. A switch with no
defining `FLIPBOX` (used only in `show_if`) is valid — it stays at its
default until changed programmatically.
```

- [ ] **Step 4: SKILL.md — troubleshooting row (line 347)**

Replace:

```
| Switch state lost on reload | Switches persist in `widgets_state` like position; a switch with no defining FLIPBOX stays at its default |
```

with:

```
| Switch state lost on reload | Switches persist in the .blend (`widgets_ui_state`) at save time; an unsaved file restores nothing — save first. A switch with no defining FLIPBOX stays at its default |
```

- [ ] **Step 5: Commit**

```bash
git add ai_skills/iops-custom-widgets/schema-reference.md ai_skills/iops-custom-widgets/SKILL.md
git commit -m "docs(widgets): persistence moved to per-file scene state

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Live verification in Blender

**Files:** none (verification only; fixes loop back into the task that owns the file).

**Interfaces:**
- Consumes: everything above, deployed to the running Blender via the reload infra (blinker reload on port 9902; addon runs from the `B:` symlink — see `memory/reference_dev_reload_infra.md`).

- [ ] **Step 1: Reload the addon in the running Blender**

Trigger the blinker reload (port 9902). If Blender isn't running or MCP (port 9999) is unreachable, STOP and report — do not fake this pass.

- [ ] **Step 2: Scripted round-trip check via MCP**

Via `mcp__blender__execute_blender_code`, run in order and capture printed output:

```python
import bpy, json, tempfile, os
from InteractionOps.ui.widgets import state as wstate

# 1. open a widget programmatically
names = list(wstate._states.keys()) or ["<pick any registered widget name>"]
# use a real registered widget:
from InteractionOps.ui import widgets as W
name = next(iter(n for n in W._registry), None) if hasattr(W, "_registry") else None
print("widget under test:", name)
wstate.show_widget(name)
print("dirty after open:", bpy.data.is_dirty)           # expect False if file was clean

# 2. save to temp file → snapshot written
path = os.path.join(tempfile.gettempdir(), "iops_widget_state_test.blend")
bpy.ops.wm.save_as_mainfile(filepath=path)
print("stored:", bpy.context.scene.IOPS.widgets_ui_state)  # expect JSON with widget visible

# 3. fresh file → all closed
bpy.ops.wm.read_homefile(use_empty=True)
print("after new file, any visible:", wstate.any_visible())  # expect False

# 4. reopen → restored
bpy.ops.wm.open_mainfile(filepath=path)
print("after reopen, visible:", wstate.get_state(name)["visible"])  # expect True
```

(Adapt the widget-name lookup to the actual registry accessor in `ui/widgets/__init__.py` — `get_widget`/`iter_widgets` exist; pick the first from `iter_widgets()`.)

Expected: `dirty after open: False`, stored JSON non-empty with `"visible": true`, `False` after File > New, `True` after reopen.

- [ ] **Step 3: Manual spot-check items (report, don't skip)**

- Open a widget, drag it, flip a switch, save, reopen → position and switch restored.
- Open a widget, do NOT save, reopen the file → widget closed (accepted semantics).
- Undo (Ctrl+Z) right after opening a widget → no state weirdness, no console errors.

- [ ] **Step 4: Full pure sweep one more time**

Run: `python -m pytest tests -q`
Expected: all PASS

- [ ] **Step 5: Fix anything found, commit fixes to the owning file, re-run**

---

## Self-Review (done at plan time)

- Spec coverage: storage property (T2), save_pre writer (T2), load_post restore (T2), register/unregister (T2), pure helpers + tests (T1), prefs removals (T3), docs (T4 — real locations are `ai_skills/`, spec's `docs/ui/` row corrected), live tests (T5). No gaps.
- Placeholders: none; every code step carries full code.
- Type consistency: `dumps_states`/`parse_states` names and shapes match between T1 and T2; `_SCENE_PROP` matches the property name added in T2 Step 1.
