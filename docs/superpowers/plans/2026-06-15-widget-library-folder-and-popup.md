# Widget Library Folder + Scan-to-Popup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the JSON widget system a user-managed library — configurable folder (executor-parity), a scan-to-popup operator listing widgets, and the two hardcoded Python widgets extracted to JSON via an extended schema (RNA bool toggles + explicit rows).

**Architecture:** `widgets/composed.py` gains a pure RNA-path resolver + `rna_bool_adapter`, a refactored `validate_def` (per-row `_clean_row` helper) that accepts `FLIPBOX.prop` and a `ROW` grouping type, and a prefs-driven `widgets_folder()`. The two Python widget classes are deleted; `edge_data.json` + `ccp_data_ops.json` are written into the user folder. A new `operators/widgets_panel.py` scans the folder, registers what it finds, and pops `IOPS_PT_WidgetList`.

**Tech Stack:** Python, Blender 5.1.2 bpy API, pytest (pure-logic tests; bpy-bound parts verified live via the Blender MCP reload).

**Spec:** `docs/superpowers/specs/2026-06-15-widget-library-folder-and-popup-design.md`

**Conventions used throughout:**
- Run tests with: `python -m pytest tests/ui/widgets/test_composed.py -q` (from repo root `D:\git\InteractionOps`).
- Live reload in Blender (MCP `execute_blender_code`):
  ```python
  import bpy, sys
  bpy.ops.preferences.addon_disable(module="InteractionOps")
  for m in [m for m in sys.modules if m.startswith("InteractionOps")]:
      del sys.modules[m]
  bpy.ops.preferences.addon_enable(module="InteractionOps")
  ```

---

## File Structure

**Modify:**
- `widgets/composed.py` — RNA resolver + adapter, `_clean_row`, `FLIPBOX.prop`, `ROW`, edge-gated buttons, prefs-driven `widgets_folder()`, remove shadow guard, keep `EDGE_DATA_DEF` as a plain template constant (no longer "built-in").
- `widgets/__init__.py` — remove the two Python widget imports + register/unregister.
- `prefs/addon_preferences.py` — 3 `widgets_*` props; folder section + popup button in `draw_widgets_tab`'s caller. (Folder UI drawn inside `widget_composer.draw_widgets_tab`.)
- `prefs/widget_composer.py` — folder UI + popup button in the tab; remove `builtin_defs()`, the built-in branch in `sync_from_files`, the lock-icon/registry-fallback rows.
- `prefs/addon_properties.py` — `IOPS_WidgetListItem` + `widget_list` collection on `IOPS_SceneProperties`.
- `prefs/iops_prefs.py` — export `widgets_*` under a `WIDGETS_FOLDER` block.
- `operators/preferences/io_addon_preferences.py` — load `WIDGETS_FOLDER`.
- `__init__.py` — register the new operator, panel, and `IOPS_WidgetListItem`.
- `ai_skills/iops-custom-widgets/SKILL.md` — document `prop`, `ROW`, folder, popup.
- `tests/ui/widgets/test_composed.py` — new cases.

**Create:**
- `operators/widgets_panel.py` — `IOPS_OT_Call_Widgets_Panel` + `IOPS_PT_WidgetList`.

**Delete:**
- `widgets/edge_data.py`, `widgets/ccp_data_ops.py`.

**Write (outside repo, user data — not committed):**
- `B:\scripts\presets\IOPS\widgets\edge_data.json`
- `B:\scripts\presets\IOPS\widgets\ccp_data_ops.json`

---

## Task 1: RNA path resolver + bool adapter (pure)

**Files:**
- Modify: `widgets/composed.py`
- Test: `tests/ui/widgets/test_composed.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/ui/widgets/test_composed.py`:

```python
# ----------------------------------------------------------------------
# RNA path resolver + bool adapter
# ----------------------------------------------------------------------
class _Obj:
    pass


def _fake_context():
    ctx = _Obj()
    ctx.scene = _Obj()
    ctx.scene.CCP = _Obj()
    ctx.scene.CCP.flag = True
    return ctx


def test_resolve_rna_owner_walks_path():
    ctx = _fake_context()
    owner, attr = composed.resolve_rna_owner(ctx, "scene.CCP.flag")
    assert owner is ctx.scene.CCP and attr == "flag"


def test_resolve_rna_owner_missing_returns_none():
    ctx = _fake_context()
    owner, attr = composed.resolve_rna_owner(ctx, "scene.NOPE.flag")
    assert owner is None and attr is None


def test_rna_bool_adapter_get_set():
    ctx = _fake_context()
    ad = composed.rna_bool_adapter("scene.CCP.flag")
    assert ad["get"](ctx) == (True, False)
    ad["set"](ctx, False)
    assert ctx.scene.CCP.flag is False
    # Missing path -> disabled sentinel, set is a no-op (no raise)
    bad = composed.rna_bool_adapter("scene.NOPE.flag")
    assert bad["get"](ctx) == (None, False)
    bad["set"](ctx, True)
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `python -m pytest tests/ui/widgets/test_composed.py -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'resolve_rna_owner'`.

- [ ] **Step 3: Implement the helpers in `widgets/composed.py`**

Add after `parse_values` (near the other pure helpers, before `validate_def`):

```python
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
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `python -m pytest tests/ui/widgets/test_composed.py -q`
Expected: PASS (all, including the 3 new).

- [ ] **Step 5: Commit**

```bash
git add widgets/composed.py tests/ui/widgets/test_composed.py
git commit -m "feat(widgets): RNA bool adapter for JSON-composed widgets"
```

---

## Task 2: Schema — `_clean_row` refactor + `FLIPBOX.prop` + `ROW`

**Files:**
- Modify: `widgets/composed.py` (`validate_def`)
- Test: `tests/ui/widgets/test_composed.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/ui/widgets/test_composed.py`:

```python
# ----------------------------------------------------------------------
# FLIPBOX prop + ROW
# ----------------------------------------------------------------------
def test_validate_flipbox_prop():
    wdef, errors = composed.validate_def({
        "name": "w",
        "rows": [
            {"type": "FLIPBOX", "prop": "scene.CCP.red_export_opaqueAreas",
             "label": "Opaque"},
            {"type": "FLIPBOX", "prop": "scene.CCP.x"},   # label defaults
        ],
    })
    assert errors == []
    assert wdef["rows"][0]["prop"] == "scene.CCP.red_export_opaqueAreas"
    assert wdef["rows"][0]["label"] == "Opaque"
    assert wdef["rows"][1]["label"] == "x"   # last path segment


def test_validate_flipbox_needs_exactly_one_of_prop_target():
    wdef, errors = composed.validate_def({
        "name": "w",
        "rows": [
            {"type": "FLIPBOX"},                                   # neither
            {"type": "FLIPBOX", "prop": "scene.x", "target": "SEAM"},  # both
        ],
    })
    assert wdef["rows"] == []
    assert len(errors) == 2


def test_validate_row_grouping():
    wdef, errors = composed.validate_def({
        "name": "w",
        "rows": [
            {"type": "ROW", "cells": [
                {"type": "FLIPBOX", "prop": "scene.CCP.x", "label": "X"},
                {"type": "BUTTON", "label": "Export", "op": "ccp.do"},
            ]},
            {"type": "ROW", "cells": []},                  # empty -> drop
            {"type": "ROW", "cells": [{"type": "NOPE"}]},  # all bad -> drop
        ],
    })
    assert len(wdef["rows"]) == 1
    row = wdef["rows"][0]
    assert row["type"] == "ROW" and len(row["cells"]) == 2
    assert row["cells"][0]["type"] == "FLIPBOX"
    assert row["cells"][1]["type"] == "BUTTON"
    assert len(errors) >= 2


def test_validate_row_rejects_nested_row():
    wdef, errors = composed.validate_def({
        "name": "w",
        "rows": [{"type": "ROW", "cells": [
            {"type": "ROW", "cells": [{"type": "SECTION", "label": "x"}]},
        ]}],
    })
    assert wdef["rows"] == []   # only cell was a nested ROW -> dropped -> empty
    assert errors
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `python -m pytest tests/ui/widgets/test_composed.py -q`
Expected: FAIL — current `validate_def` has no `prop`/`ROW` handling (flipbox-with-prop loses the prop; ROW is an unknown type).

- [ ] **Step 3: Refactor `validate_def` to use `_clean_row`, add `prop` + `ROW`**

Replace the entire `validate_def` function in `widgets/composed.py` with:

```python
def _clean_row(row):
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
    if rtype == "SLIDER":
        target = str(row.get("target", "")).upper()
        if target not in FLOAT_TARGETS:
            return None, f"slider target '{target}' invalid"
        out["target"] = target
        try:
            out["snap"] = max(0.0, float(row.get("snap", 0.125)))
        except (TypeError, ValueError):
            out["snap"] = 0.125
        return out, None
    if rtype == "PRESETS":
        target = str(row.get("target", "")).upper()
        if target not in FLOAT_TARGETS:
            return None, f"presets target '{target}' invalid"
        out["target"] = target
        vals = []
        values = row.get("values", [])
        if isinstance(values, list):
            for v in values:
                try:
                    vals.append(max(0.0, min(1.0, float(v))))
                except (TypeError, ValueError):
                    pass
        if not vals:
            return None, "presets without values"
        out["values"] = vals
        return out, None
    if rtype == "FLIPBOX":
        prop = str(row.get("prop", "")).strip()
        target = str(row.get("target", "")).strip().upper()
        if bool(prop) == bool(target):
            return None, "flipbox needs exactly one of prop/target"
        if prop:
            out["prop"] = prop
            out["label"] = str(row.get("label", "")) or prop.rsplit(".", 1)[-1]
        else:
            if target not in BOOL_TARGETS:
                return None, f"flipbox target '{target}' invalid"
            out["target"] = target
            out["label"] = str(row.get("label", "")) or target.title()
        return out, None
    if rtype == "ROW":
        cells_in = row.get("cells", [])
        if not isinstance(cells_in, list):
            return None, "row cells is not a list"
        cells = []
        for cell in cells_in:
            c, _err = _clean_row(cell)
            if c is None or c["type"] == "ROW":
                continue   # drop unusable / nested ROW cells silently
            cells.append(c)
        if not cells:
            return None, "row has no usable cells"
        out["cells"] = cells
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
        "space": "VIEW_3D",   # IMAGE_EDITOR widgets come later (spec)
        "rows": [],
    }
    rows = data.get("rows", [])
    if not isinstance(rows, list):
        return clean, ["rows is not a list"]
    for i, row in enumerate(rows):
        out, err = _clean_row(row)
        if err:
            errors.append(f"row {i}: {err} — dropped")
        if out is not None:
            clean["rows"].append(out)
    return clean, errors
```

Note: the old `test_validate_drops_bad_rows_keeps_good` expected exactly 5 errors and the old message phrasing; the refactor keeps "row N: ... — dropped" so the count stays 5 (SLIDER-SHARP, NOPE, PRESETS-bad-values, BUTTON-noidname, "not a dict"). Verify it still passes in Step 4; if the not-a-dict case now reads "row N: not an object — dropped", that's fine — the test only counts `len(errors) == 5`.

- [ ] **Step 4: Run tests, verify they pass**

Run: `python -m pytest tests/ui/widgets/test_composed.py -q`
Expected: PASS (old + new). If `test_validate_full_edge_data_def_is_clean` fails, it's Task 3's concern (EDGE_DATA_DEF stays a constant) — it should still pass here since the constant is untouched.

- [ ] **Step 5: Commit**

```bash
git add widgets/composed.py tests/ui/widgets/test_composed.py
git commit -m "feat(widgets): FLIPBOX prop + explicit ROW in JSON schema"
```

---

## Task 3: `build_controls` — RNA flipbox, ROW, edge-gated buttons

**Files:**
- Modify: `widgets/composed.py` (`build_controls`, `_binds_edges`)

No pytest (build_controls imports bpy-bound `ui.widgets` + `adapters` at call time). Verified live in Task 10.

- [ ] **Step 1: Update `_binds_edges` to recurse into ROW cells and ignore `prop`**

Replace `_binds_edges` in `widgets/composed.py` with:

```python
def _binds_edges(row_defs):
    """True if any control binds an EDGE adapter (target=). Recurses into
    ROW cells. prop-bound flipboxes are NOT edge-bound."""
    def row_binds(r):
        if r.get("type") == "ROW":
            return any(row_binds(c) for c in r.get("cells", []))
        return bool(r.get("target"))
    return any(row_binds(r) for r in row_defs)
```

- [ ] **Step 2: Update `build_controls` for prop flipboxes, ROW, and edge-gated buttons**

Replace `build_controls` in `widgets/composed.py` with:

```python
def build_controls(row_defs):
    """Materialize a validated `rows` list into framework controls."""
    from ..ui.widgets import (Section, Slider, PresetRow, FlipBox,
                              ActionButton, Row)
    from .adapters import ADAPTERS, has_selected_edges

    edge_bound = _binds_edges(row_defs)
    # Buttons/presets gray with no selection ONLY for edge widgets; a
    # scene-prop widget (e.g. ccp_data_ops) keeps them always enabled.
    gate = has_selected_edges if edge_bound else None

    def one(row):
        rtype = row["type"]
        if rtype == "SECTION":
            return Section(row.get("label", ""))
        if rtype == "SLIDER":
            a = ADAPTERS[row["target"]]
            return Slider(get=a["get"], set=a["set"],
                          snap=row.get("snap", 0.125),
                          snapshot=a.get("snapshot"),
                          restore=a.get("restore"))
        if rtype == "PRESETS":
            a = ADAPTERS[row["target"]]
            return PresetRow(row["values"], set=a["set"], enabled_get=gate)
        if rtype == "FLIPBOX":
            if row.get("prop"):
                ad = rna_bool_adapter(row["prop"])
                return FlipBox(row["label"], get=ad["get"], set=ad["set"])
            a = ADAPTERS[row["target"]]
            return FlipBox(row["label"], get=a["get"], set=a["set"])
        if rtype == "BUTTON":
            return ActionButton(row["label"], op=row["op"],
                                kwargs=row.get("op_kwargs") or {},
                                role=row.get("role", "default"),
                                enabled_get=gate)
        return None

    controls = []
    for item in merge_flipbox_runs(row_defs):
        if isinstance(item, list):
            controls.append(Row([one(r) for r in item]))
        elif isinstance(item, dict) and item.get("type") == "ROW":
            controls.append(Row([one(r) for r in item["cells"]]))
        else:
            ctrl = one(item)
            if ctrl is not None:
                controls.append(ctrl)
    return controls
```

Note: `merge_flipbox_runs` passes a ROW dict through unchanged (it is not a FLIPBOX), so the explicit-ROW branch handles it; bare adjacent FLIPBOX defs still merge as before.

- [ ] **Step 3: Commit**

```bash
git add widgets/composed.py
git commit -m "feat(widgets): build RNA flipboxes, explicit rows, scene-prop button gating"
```

---

## Task 4: Configurable widgets folder (prefs props + resolver + tab UI)

**Files:**
- Modify: `prefs/addon_preferences.py` (props)
- Modify: `widgets/composed.py` (`widgets_folder`)
- Modify: `prefs/widget_composer.py` (`draw_widgets_tab` folder section)

- [ ] **Step 1: Add the three props to `IOPS_AddonPreferences`**

In `prefs/addon_preferences.py`, after the `widget_defs_index` property (~line 97), add:

```python
    # Widget library folder (executor-parity). Source folder for the
    # JSON widgets the popup lists and the loader registers.
    widgets_use_script_path_user: BoolProperty(
        name="Use user script path",
        description="Resolve the widgets folder under the user scripts path",
        default=True,
    )
    widgets_subfolder: StringProperty(
        name="Widgets sub-folder",
        default="presets/IOPS/widgets",
    )
    widgets_folder: StringProperty(
        name="Widgets Folder",
        subtype="DIR_PATH",
        default=bpy.utils.script_path_user(),
    )
```

(`BoolProperty`/`StringProperty` are already imported at the top of the file.)

- [ ] **Step 2: Make `composed.widgets_folder()` read the prefs (defensive)**

Replace `widgets_folder` in `widgets/composed.py` with:

```python
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
```

- [ ] **Step 3: Draw the folder section at the top of the Widgets tab**

In `prefs/widget_composer.py`, in `draw_widgets_tab`, insert the folder block at the very top (before `col.label(text="Widgets")`):

```python
def draw_widgets_tab(layout, context, prefs):
    import os
    # Widgets library folder (executor-parity).
    box = layout.box()
    box.label(text="Widgets Folder:", icon="FILE_FOLDER")
    box.prop(prefs, "widgets_use_script_path_user")
    if prefs.widgets_use_script_path_user:
        import bpy
        box.label(text=bpy.utils.script_path_user())
        box.prop(prefs, "widgets_subfolder")
    else:
        box.prop(prefs, "widgets_folder")
    box.operator("iops.scripts_call_widgets_panel",
                 text="Open Widgets Panel", icon="MENU_PANEL")

    col = layout.column()
    col.label(text="Widgets")
    # ... existing list + manage column unchanged ...
```

Keep the rest of the function (the `template_list` + ops column) exactly as is.

- [ ] **Step 4: Live check — folder resolves and persists**

Reload the addon (see conventions). Then:

```python
import bpy
from InteractionOps.widgets import composed
prefs = bpy.context.preferences.addons["InteractionOps"].preferences
r = {"default": composed.widgets_folder()}
prefs.widgets_use_script_path_user = False
prefs.widgets_folder = "B:\\team\\widgets"
r["explicit"] = composed.widgets_folder()
prefs.widgets_use_script_path_user = True
r
```
Expected: `default` ends with `presets\IOPS\widgets`; `explicit` == `B:\team\widgets`.

(The "Open Widgets Panel" button refers to an operator added in Task 8; it will error if clicked before then — do not click yet.)

- [ ] **Step 5: Commit**

```bash
git add prefs/addon_preferences.py widgets/composed.py prefs/widget_composer.py
git commit -m "feat(widgets): configurable library folder (executor-parity)"
```

---

## Task 5: Prefs JSON round-trip for the folder settings

**Files:**
- Modify: `prefs/iops_prefs.py` (export)
- Modify: `operators/preferences/io_addon_preferences.py` (load)

- [ ] **Step 1: Export the folder props**

In `prefs/iops_prefs.py`, inside the `iops_prefs = {...}` dict, add a new block after the `"EXECUTOR"` block:

```python
        "WIDGETS_FOLDER": {
            "widgets_use_script_path_user": safe("widgets_use_script_path_user", True),
            "widgets_subfolder": safe("widgets_subfolder", "presets/IOPS/widgets"),
            "widgets_folder": safe("widgets_folder", bpy.utils.script_path_user()),
        },
```

- [ ] **Step 2: Load the folder props**

In `operators/preferences/io_addon_preferences.py`, add a new `case` alongside the existing `match` cases (mirror the `"EXECUTOR"` case):

```python
                    case "WIDGETS_FOLDER":
                        if isinstance(value, dict):
                            defaults = default_prefs.get("WIDGETS_FOLDER", {})
                            prefs.widgets_use_script_path_user = safe_get(
                                value, "widgets_use_script_path_user",
                                defaults.get("widgets_use_script_path_user", True))
                            prefs.widgets_subfolder = safe_get(
                                value, "widgets_subfolder",
                                defaults.get("widgets_subfolder", "presets/IOPS/widgets"))
                            prefs.widgets_folder = safe_get(
                                value, "widgets_folder",
                                defaults.get("widgets_folder", bpy.utils.script_path_user()))
```

Read the surrounding `match`/`safe_get`/`default_prefs` code first to match the exact indentation and the `default_prefs` source (it is the dict returned by `get_iops_prefs()` with defaults).

- [ ] **Step 3: Live check — Save then Load prefs round-trips the values**

Reload addon. Then:

```python
import bpy
prefs = bpy.context.preferences.addons["InteractionOps"].preferences
prefs.widgets_subfolder = "presets/IOPS/widgets_test"
bpy.ops.iops.save_addon_preferences()
prefs.widgets_subfolder = "WRONG"
bpy.ops.iops.load_addon_preferences()
result = prefs.widgets_subfolder   # expect "presets/IOPS/widgets_test"
```
Then restore: set back to `"presets/IOPS/widgets"` and Save again.
Expected: `result == "presets/IOPS/widgets_test"`.

(Operator idnames `iops.save_addon_preferences` / `iops.load_addon_preferences` are the tab's Save/Load buttons — confirm names via `prefs/addon_preferences.py` draw; adjust if different.)

- [ ] **Step 4: Commit**

```bash
git add prefs/iops_prefs.py operators/preferences/io_addon_preferences.py
git commit -m "feat(widgets): persist library folder in prefs JSON round-trip"
```

---

## Task 6: Remove the Python widget classes + built-in machinery

**Files:**
- Delete: `widgets/edge_data.py`, `widgets/ccp_data_ops.py`
- Modify: `widgets/__init__.py`, `widgets/composed.py`, `prefs/widget_composer.py`

- [ ] **Step 1: Grep for references that must be cleaned**

Run: `python -m pytest tests/ui/widgets/test_composed.py -q` first (baseline green), then search:
- `grep` for `edge_data`, `ccp_data_ops`, `EdgeDataWidget`, `CCPDataOpsWidget`, `builtin_defs`, `EDGE_DATA_DEF` across the repo (use the Grep tool).
Note every hit; they are addressed below. `EDGE_DATA_DEF` STAYS in `composed.py` as a plain template constant (used by `test_validate_full_edge_data_def_is_clean` and as the source for the JSON file in Task 7) — it is simply no longer treated as a registered built-in.

- [ ] **Step 2: Delete the two Python widget files**

```bash
git rm widgets/edge_data.py widgets/ccp_data_ops.py
```

- [ ] **Step 3: Rewrite `widgets/__init__.py` registration (composed-only)**

Replace the `if _HAS_BPY:` block body in `widgets/__init__.py` with:

```python
if _HAS_BPY:
    def register():
        # Composed (JSON) widgets are loaded from the library folder by
        # the root __init__ (composed.load_all + sync_from_files). Nothing
        # to register here anymore — kept for symmetric wiring.
        pass

    def unregister():
        try:
            from . import composed
            composed.unregister_all()
        except Exception as e:
            print(f"IOPS widgets: composed unregister failed: {e}")
else:  # plain pytest / headless tooling without bpy
    def register():
        pass

    def unregister():
        pass
```

(Remove the `from ..ui.widgets import register_widget, unregister_widget`, the `from .edge_data ...`, `from .ccp_data_ops ...` imports and the module-level `register_widget(...)` calls.)

- [ ] **Step 4: Remove the shadow guard in `composed.register_composed`**

In `widgets/composed.py`, replace `register_composed` with:

```python
def register_composed(wdef):
    """(Re)register one composed widget. Idempotent — keyed by name."""
    from ..ui import widgets as framework
    inst = framework.register_widget(make_widget(wdef))
    _live.add(wdef["name"])
    return inst, None
```

(The "may not shadow a built-in" check is gone — there are no Python built-ins now. Callers still handle the `(inst, err)` tuple; `err` is always None.)

- [ ] **Step 5: Remove built-in machinery from `prefs/widget_composer.py`**

- Delete `builtin_defs()`.
- In `sync_from_files`, delete the loop that adds `builtin_defs().values()` as locked items, AND delete the `iter_widgets()` registry-fallback loop added earlier (registered widgets now all come from files). The function should: clear `widget_defs`, then add one item per `composed.list_widget_files()` def, then restore selection.
- In `def_to_item`, the `builtin` parameter and `item.builtin` handling can stay (harmless) but is always False now; the UIList lock-icon branch in `IOPS_UL_WidgetDefs.draw_item` becomes dead — simplify to always draw the editable name field:

```python
class IOPS_UL_WidgetDefs(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        from ..ui.widgets import events
        split = layout.split(factor=0.55, align=True)
        split.prop(item, "name", text="", emboss=False)
        _km, kmi = events.find_user_toggle_kmi(item.name)
        if kmi is not None:
            split.prop(kmi, "type", text="", full_event=True)
        else:
            split.label(text="")
```

- In `rename_item`, the `if item.builtin:` early-return branch is now dead; leave it (harmless) or remove it. If removed, also drop the `builtin` set in `def_to_item`. Keep minimal: leave `builtin` field + branches in place (always False) to limit churn, OR remove cleanly — implementer's choice, but do not leave a half-removed state.
- In `_taken_names` / `io_widgets.py` `IOPS_OT_WidgetDefDuplicate`: any `builtin_defs()` calls must be removed. In `io_widgets.py`, `_taken_names()` does `taken.update(widget_composer.builtin_defs())` — change to just `taken = {it.name for it in prefs.widget_defs}`. In `IOPS_OT_WidgetDefDuplicate.execute`, the `if item.builtin:` branch using `builtin_defs()` is dead; reduce to `src = widget_composer.item_to_def(item)`.

- [ ] **Step 6: Run pure tests**

Run: `python -m pytest tests -q`
Expected: PASS. (`test_validate_full_edge_data_def_is_clean` still passes — `EDGE_DATA_DEF` remains a constant.)

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(widgets): remove Python built-ins, widgets are JSON-only"
```

---

## Task 7: Write the two widget JSON files into the user folder

**Files:**
- Write (outside repo): `B:\scripts\presets\IOPS\widgets\edge_data.json`, `ccp_data_ops.json`

Not committed (user data outside the repo). Use the Write tool.

- [ ] **Step 1: Write `B:\scripts\presets\IOPS\widgets\edge_data.json`**

```json
{
  "version": 1,
  "name": "edge_data",
  "title": "Edge Data",
  "space": "VIEW_3D",
  "rows": [
    {"type": "SECTION", "label": "Bevel Weight"},
    {"type": "SLIDER", "target": "BEVEL", "snap": 0.125},
    {"type": "PRESETS", "target": "BEVEL", "values": [0, 0.25, 0.5, 1.0]},
    {"type": "SECTION", "label": "Crease"},
    {"type": "SLIDER", "target": "CREASE", "snap": 0.125},
    {"type": "PRESETS", "target": "CREASE", "values": [0, 0.5, 0.9, 1.0]},
    {"type": "SECTION", "label": "Flags"},
    {"type": "FLIPBOX", "target": "SHARP", "label": "Sharp"},
    {"type": "FLIPBOX", "target": "SEAM", "label": "Seam"},
    {"type": "FLIPBOX", "target": "FREESTYLE", "label": "Freestyle"},
    {"type": "BUTTON", "label": "Clear", "op": "iops.executor",
     "op_kwargs": {"script": "B:\\scripts\\iops_exec\\CLEAN_Edge_Data_Clear.py"},
     "role": "error"}
  ]
}
```

- [ ] **Step 2: Write `B:\scripts\presets\IOPS\widgets\ccp_data_ops.json`**

Materials use single-cell ROWs so they stack one-per-row (a bare run of
adjacent FLIPBOX would implicit-merge into one multi-column row);
Sets/Light/Locators use two-cell ROWs (toggle + Export).

```json
{
  "version": 1,
  "name": "ccp_data_ops",
  "title": "CCP Data OPS",
  "space": "VIEW_3D",
  "rows": [
    {"type": "SECTION", "label": "Materials"},
    {"type": "ROW", "cells": [{"type": "FLIPBOX", "prop": "scene.CCP.red_export_opaqueAreas", "label": "OpaqueAreas"}]},
    {"type": "ROW", "cells": [{"type": "FLIPBOX", "prop": "scene.CCP.red_export_decalAreas", "label": "DecalAreas"}]},
    {"type": "ROW", "cells": [{"type": "FLIPBOX", "prop": "scene.CCP.red_export_transparentAreas", "label": "TransparentAreas"}]},
    {"type": "ROW", "cells": [{"type": "FLIPBOX", "prop": "scene.CCP.red_export_additiveAreas", "label": "AdditiveAreas"}]},
    {"type": "ROW", "cells": [{"type": "FLIPBOX", "prop": "scene.CCP.red_export_distortionAreas", "label": "DistortionAreas"}]},
    {"type": "SECTION", "label": "Sets"},
    {"type": "ROW", "cells": [{"type": "FLIPBOX", "prop": "scene.CCP.red_export_bannerSets", "label": "Banner"}, {"type": "BUTTON", "label": "Export", "op": "ccp_tools.export_banner_data"}]},
    {"type": "ROW", "cells": [{"type": "FLIPBOX", "prop": "scene.CCP.red_export_decalSets", "label": "Decal"}, {"type": "BUTTON", "label": "Export", "op": "ccp_tools.export_decal_data"}]},
    {"type": "ROW", "cells": [{"type": "FLIPBOX", "prop": "scene.CCP.red_export_planeSets", "label": "Plane"}, {"type": "BUTTON", "label": "Export", "op": "ccp_tools.export_plane_data"}]},
    {"type": "ROW", "cells": [{"type": "FLIPBOX", "prop": "scene.CCP.red_export_spriteSets", "label": "Sprite"}, {"type": "BUTTON", "label": "Export", "op": "ccp_tools.export_sprite_data"}]},
    {"type": "ROW", "cells": [{"type": "FLIPBOX", "prop": "scene.CCP.red_export_spriteLineSets", "label": "Sprite Line"}, {"type": "BUTTON", "label": "Export", "op": "ccp_tools.export_sprite_line_sets_data"}]},
    {"type": "SECTION", "label": "Light"},
    {"type": "ROW", "cells": [{"type": "FLIPBOX", "prop": "scene.CCP.red_export_lightSets", "label": "Light"}, {"type": "BUTTON", "label": "Export", "op": "ccp_tools.export_light_data"}]},
    {"type": "ROW", "cells": [{"type": "FLIPBOX", "prop": "scene.CCP.red_export_spotlightSets", "label": "Spotlight"}, {"type": "BUTTON", "label": "Export", "op": "ccp_tools.export_spotlight_data"}]},
    {"type": "SECTION", "label": "Locators"},
    {"type": "ROW", "cells": [{"type": "FLIPBOX", "prop": "scene.CCP.red_export_booster", "label": "Booster"}, {"type": "BUTTON", "label": "Export", "op": "ccp_tools.export_booster_data"}]},
    {"type": "ROW", "cells": [{"type": "FLIPBOX", "prop": "scene.CCP.red_export_locatorSets", "label": "Locator"}, {"type": "BUTTON", "label": "Export", "op": "ccp_tools.export_locator_data"}]},
    {"type": "ROW", "cells": [{"type": "FLIPBOX", "prop": "scene.CCP.red_export_locatorTurrets", "label": "Turrets"}, {"type": "BUTTON", "label": "Export", "op": "ccp_tools.export_locator_turret_data"}]},
    {"type": "BUTTON", "label": "Update Red File", "op": "ccp_tools.update_red_file"}
  ]
}
```

- [ ] **Step 3: Verify both files validate**

Run (pytest, standalone composed):
```python
python -c "import importlib.util,os,json; \
p=os.path.join(os.environ['ALLUSERSPROFILE'],''); \
spec=importlib.util.spec_from_file_location('c','widgets/composed.py'); \
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); \
import json; \
print(m.validate_def(json.load(open(r'B:\\scripts\\presets\\IOPS\\widgets\\ccp_data_ops.json')))[1]); \
print(m.validate_def(json.load(open(r'B:\\scripts\\presets\\IOPS\\widgets\\edge_data.json')))[1])"
```
Expected: two empty lists `[]` (no validation errors). If the one-liner is awkward on Windows, instead add a temporary throwaway pytest that loads both files through `composed.validate_def` and asserts `errors == []`, run it, then delete it.

(No commit — files are outside the repo.)

---

## Task 8: Scan-to-popup operator + panel + storage + registration

**Files:**
- Create: `operators/widgets_panel.py`
- Modify: `prefs/addon_properties.py` (`IOPS_WidgetListItem` + `widget_list`)
- Modify: `__init__.py` (register operator, panel, item)

- [ ] **Step 1: Add the list-item property group + collection**

In `prefs/addon_properties.py`, add after `IOPS_ExecutorScriptItem`:

```python
class IOPS_WidgetListItem(PropertyGroup):
    """One widget (name + display title) for the scan-to-popup list."""
    name: StringProperty(name="Widget name", default="")
    title: StringProperty(name="Title", default="")
```

And in `IOPS_SceneProperties`, after `filtered_executor_scripts`, add:

```python
    widget_list: CollectionProperty(
        type=IOPS_WidgetListItem,
        name="Widget list",
        description="Widgets found in the library folder for the popup",
    )
```

- [ ] **Step 2: Create `operators/widgets_panel.py`**

```python
"""Scan-to-popup for JSON widgets — mirrors the script executor.

`iops.scripts_call_widgets_panel` scans the configured widgets folder,
registers every valid definition (idempotent), refreshes the per-widget
toggle hotkeys, stores (name, title) on the scene, and pops a list panel.
Each row toggles that widget's GPU panel via iops.widget_toggle.
"""
import os

import bpy

from ..widgets import composed


class IOPS_OT_Call_Widgets_Panel(bpy.types.Operator):
    """Scan the widgets folder and open a list of all widgets"""

    bl_idname = "iops.scripts_call_widgets_panel"
    is_bindable = True
    bl_label = "IOPS Widgets Panel"

    def execute(self, context):
        iops = getattr(context.scene, "IOPS", None)
        if iops is None:
            self.report({"ERROR"}, "IOPS scene data not available")
            return {"CANCELLED"}
        folder = composed.widgets_folder()
        found = []
        if os.path.isdir(folder):
            for fn in composed.list_widget_files():
                wdef, _err = composed.load_def(os.path.join(folder, fn))
                if wdef is None:
                    continue
                composed.register_composed(wdef)   # idempotent, keyed by name
                found.append((wdef["name"], wdef.get("title") or wdef["name"]))
        # New widgets need toggle-hotkey entries + prefs rows.
        try:
            from ..ui.widgets import events
            events.sync_toggle_kmis()
            from ..prefs import widget_composer
            widget_composer.sync_from_files()
        except Exception as e:
            print("IOPS widgets panel: sync failed:", e)
        iops.widget_list.clear()
        for name, title in sorted(found, key=lambda t: t[1].lower()):
            item = iops.widget_list.add()
            item.name = name
            item.title = title
        bpy.ops.wm.call_panel(name="IOPS_PT_WidgetList")
        return {"FINISHED"}


class IOPS_PT_WidgetList(bpy.types.Panel):
    bl_idname = "IOPS_PT_WidgetList"
    bl_label = "Widgets"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"

    def draw(self, context):
        layout = self.layout
        iops = getattr(context.scene, "IOPS", None)
        items = list(iops.widget_list) if iops is not None else []
        if not items:
            layout.label(text="No widgets in folder")
            return
        col = layout.column(align=True)
        letter = ""
        for item in items:
            head = (item.title or item.name)[:1].upper()
            if head != letter:
                col.label(text=head)
                letter = head
            col.operator("iops.widget_toggle", text=item.title,
                         icon="MESH_PLANE").name = item.name


classes = (IOPS_OT_Call_Widgets_Panel, IOPS_PT_WidgetList)
```

- [ ] **Step 3: Register the new classes in `__init__.py`**

- Add the import near the other operator imports:
  `from .operators.widgets_panel import classes as _widgets_panel_classes`
- Add `IOPS_WidgetListItem` to the imports from `.prefs.addon_properties`:
  `from .prefs.addon_properties import IOPS_SceneProperties, IOPS_CollectionItem, IOPS_ExecutorScriptItem, IOPS_WidgetListItem`
- In the `classes = (...)` tuple: add `IOPS_WidgetListItem` immediately BEFORE `IOPS_SceneProperties` (the collection's item type must register first), and add `*_widgets_panel_classes` near the other operator groups (after `*ui_widgets.classes` is fine).

- [ ] **Step 4: Live verify the popup**

Reload addon. With CCP Tools enabled and a CCP asset in the scene:

```python
import bpy
bpy.ops.iops.scripts_call_widgets_panel()   # may need a VIEW_3D override
import bpy
iops = bpy.context.scene.IOPS
result = [(i.name, i.title) for i in iops.widget_list]
```
Expected: `[('ccp_data_ops', 'CCP Data OPS'), ('edge_data', 'Edge Data')]`
(sorted by title). Then in the real viewport, run the operator (or bind it), confirm the popup lists both, and clicking each summons its GPU panel.

- [ ] **Step 5: Commit**

```bash
git add operators/widgets_panel.py prefs/addon_properties.py __init__.py
git commit -m "feat(widgets): scan-to-popup operator + widget list panel"
```

---

## Task 9: Update the authoring skill

**Files:**
- Modify: `ai_skills/iops-custom-widgets/SKILL.md`

- [ ] **Step 1: Document the new schema + popup**

Update the skill:
- JSON vs Python table: note Python widget classes are no longer shipped; authoring is JSON-first in the library folder.
- Add to the schema description: `FLIPBOX` may bind `"prop": "<dotted RNA path on context>"` (scene/object bool) instead of `"target"`; absence-safe (renders disabled).
- Document the `ROW` row type: `{"type":"ROW","cells":[ ... ]}` for mixing a toggle + button on one line; single-cell ROW forces one-per-row (prevents the implicit adjacent-FLIPBOX merge).
- Note the configurable Widgets Folder pref (executor-parity) and the `iops.scripts_call_widgets_panel` scan-to-popup operator (lists folder widgets; click summons).
- Update the gotcha table row about ActionButton op (INVOKE_DEFAULT) stays; add: scene-prop widgets keep buttons always-enabled (edge gating only applies when the widget binds edge `target`s).

- [ ] **Step 2: Commit**

```bash
git add ai_skills/iops-custom-widgets/SKILL.md
git commit -m "docs(widgets): skill covers prop/ROW schema + library popup"
```

---

## Task 10: Full live verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full pure suite**

Run: `python -m pytest tests -q`
Expected: all pass.

- [ ] **Step 2: Reload + smoke-test in Blender 5.1.2**

Reload addon. Verify, capturing a result dict / screenshot for each:
1. Both JSON widgets auto-load: `sorted(w.name for w in InteractionOps.ui.widgets.iter_widgets())` → `['ccp_data_ops', 'edge_data']`.
2. Toggle kmis exist for both (addon "Window" keymap).
3. `iops.scripts_call_widgets_panel` pops a list with both; clicking summons each GPU panel.
4. `edge_data` in EDIT_MESH: sliders/presets/flags/Clear work; out-of-EDIT collapses to the hint.
5. `ccp_data_ops`: Materials stack one-per-row; Sets/Light/Locators show toggle + Export on one row; toggles reflect/drive `scene.CCP.red_export_*`; Export buttons + Update Red File fire (INVOKE_DEFAULT); with CCP Tools absent, toggles render disabled.
6. Folder pref: flip "Use user script path" off, set an explicit folder, reload, confirm the popup scans it.

- [ ] **Step 3: Final commit (if any verification fixups were needed)**

```bash
git add -A
git commit -m "fix(widgets): verification fixups"   # only if needed
```

---

## Self-Review (completed during planning)

- **Spec coverage:** folder pref + executor-parity (Task 4), saved in prefs (Task 5), schema RNA bool + ROW (Tasks 1–3), extract both widgets to JSON (Task 7), remove Python classes + built-in machinery (Task 6), scan-to-popup operator + panel (Task 8), tests + skill (Tasks 1–3, 9), live verify (Task 10). All spec sections mapped.
- **Deviations from spec (intentional, low-risk):** `EDGE_DATA_DEF` is KEPT in `composed.py` as a plain template constant (source for the JSON file + existing test) rather than deleted — it is no longer wired as a registered built-in, satisfying the "everything is data" intent without rewriting a passing test.
- **Type consistency:** `_clean_row` returns `(out|None, err|None)` and is used by `validate_def` and ROW cells; `rna_bool_adapter` returns `{"get","set"}` matching `ADAPTERS` bundle shape consumed in `build_controls`; `register_composed` keeps its `(inst, err)` return so existing callers (`load_all`) are unaffected; `widget_list` items expose `.name`/`.title` matching the panel draw and the toggle operator's `name` prop.
- **Placeholder scan:** none — every code step shows full code; JSON files shown in full.
