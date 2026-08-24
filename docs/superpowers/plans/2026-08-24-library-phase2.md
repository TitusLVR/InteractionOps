# IOPS Library (Phase 2: native wiring) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the Phase-1 library module into IOPS-native surfaces: a default hotkey through the IOPS hotkey system, entries in the Assets pie, and theme-driven popup rendering with correct blf state handling.

**Architecture:** Three independent integration seams. (1) The hotkey system gains a "3D View" keymap route (Window-level bindings are shadowed by Blender's more-specific 3D View keymap, and Blender's own `view3d.region_quadview` sits on Ctrl+Alt+Q there — the binding must live in the same keymap to win). (2) The Assets pie gets its two free slots (1 = bottom-left, 3 = bottom-right) filled with Library Popup and a Publish submenu. (3) The GPU popup's text moves onto the themed blf stack `ui/hud/text.py` (which manages SHADOW enable/disable per draw — the addon's known blf-leak-safe path) and its rectangle colors move into `IOPS_ThemePreferences` with defaults equal to the current hardcoded values, so default rendering is pixel-identical.

**Tech Stack:** Blender Python (bpy, gpu, blf), existing IOPS hotkey system (`utils/functions.py`, `prefs/hotkeys_default.py`), theme system (`prefs/theme.py`, `ui/draw/theme.py`, `ui/hud/text.py`).

**Spec:** This plan header + Global Constraints. Phase 1 plan for background: `docs/superpowers/plans/2026-08-24-library-port-phase1.md`.

## Global Constraints

- Branch: `kitbash` in worktree D:\git\InteractionOps\.claude\worktrees\library-port. All work there.
- The word "frontline" never appears anywhere in this phase's changes (no legacy-compat strings are needed here). "CCP" never appears anywhere.
- Hotkey-system rules (these fixed real regressions — violating them breaks all IOPS hotkeys):
  1. `keyconfigs.update()` runs AFTER `register_keymaps(...)` — do not reorder anything in `keymap_registration()` or the load-hotkeys operators.
  2. `unregister_keymaps()` touches only `keyconfigs.addon` — do not modify it.
  3. `keymap_registration()` is called exactly once, from `register()` — do not add calls.
- bpy-importing files cannot be pytest-tested. Verification per task = `python -m py_compile` on touched files + the headless smoke test:

```powershell
$scripts = "$env:TEMP\iops_smoke\scripts"
New-Item -ItemType Directory -Force "$scripts\addons" | Out-Null
if (Test-Path "$scripts\addons\InteractionOps") { (Get-Item "$scripts\addons\InteractionOps").Delete() }
New-Item -ItemType Junction -Path "$scripts\addons\InteractionOps" -Target "D:\git\InteractionOps\.claude\worktrees\library-port" | Out-Null
$env:BLENDER_USER_SCRIPTS = $scripts
& "V:\SteamLibrary\steamapps\common\Blender\blender.exe" --background --factory-startup --python "D:\git\InteractionOps\.claude\worktrees\library-port\tests\smoke_register.py" 2>&1
```

  Pass = output contains `SMOKE_OK` and no `Traceback`.
- Full pytest gate: only the pre-existing failure `tests/test_polygon_match.py::test_assemble_dedups_same_placement_disjoint_faces` is allowed.
- Commit messages: short imperative subject, ending with the line: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- `__init__.py` import order is intentional (`# ruff: noqa: I001` header) — never re-sort.

---

### Task 1: Default hotkey via the IOPS hotkey system

**Files:**
- Modify: `utils/functions.py` (`keymap_name_for_idname` ~line 680; `register_keymaps` ~line 693)
- Modify: `prefs/hotkeys_default.py`
- Modify: `operators/library/library_popup.py` (one line)
- Modify: `prefs/addon_preferences.py` (Keymaps tab: keymap list ~line 791; bucket chain ~line 802-910)
- Modify: `tests/smoke_register.py` (add assertions)

**Interfaces:**
- Consumes: existing hotkey plumbing; `IOPS_OT_LibraryPopup` (bl_idname `iops.library_popup`).
- Produces: `iops.library_popup` bound to Ctrl+Alt+Q in a new addon "3D View" keymap; a "Library:" bucket in the prefs Keymaps tab; all `iops.library*` idnames route to the "3D View" keymap.

- [ ] **Step 1: Route library idnames to a "3D View" keymap.** In `utils/functions.py`:

In `keymap_name_for_idname`, add as the FIRST check:

```python
    if "iops.library" in idname:
        return "3D View"
```

In `register_keymaps`, teach `items_for` the space type and pre-create the keymap. Replace the body of `items_for` and the pre-create loop with:

```python
    km_space_types = {"3D View": "VIEW_3D"}

    def items_for(name):
        if name not in km_cache:
            km_cache[name] = kc.keymaps.new(
                name,
                space_type=km_space_types.get(name, "EMPTY"),
            ).keymap_items
        return km_cache[name]

    # Pre-create the keymaps so they exist even when `keys` is empty
    # (the prefs Keymaps UI reads these by name).
    for name in ("Window", "Mesh", "Object Mode", "UV Editor", "3D View"):
        items_for(name)
```

(Blender's builtin "3D View" keymap has `space_type="VIEW_3D"`, `region_type="WINDOW"` — the default region_type — so the addon keymap merges onto it only when the space_type matches. `keymaps.new(name)` with default `space_type="EMPTY"` keeps the four existing keymaps exactly as before.)

- [ ] **Step 2: Ship the default key.** In `prefs/hotkeys_default.py`, append to `keys_default` before the closing bracket:

```python
    # IOPS Library
    ("iops.library_popup", "Q", "PRESS", True, True, False, False),
```

(Ctrl+Alt+Q — carried over from the source addon so existing muscle memory keeps working. Blender maps `view3d.region_quadview` to the same combo in the builtin 3D View keymap; the addon keymap item takes precedence within the same keymap, which is exactly why Step 1's "3D View" routing exists.)

- [ ] **Step 3: Flag bindability.** In `operators/library/library_popup.py`, add directly under the `bl_idname` line of `IOPS_OT_LibraryPopup` (matching the repo-wide stamp convention):

```python
    is_bindable = True
```

- [ ] **Step 4: Prefs Keymaps tab.** In `prefs/addon_preferences.py`:
  - In the `keymaps = [...]` list (~line 791), append `kc_user.keymaps["3D View"],` after the `"UV Editor"` entry.
  - Add a "Library:" bucket. First read the existing bucket idiom (the box/label/column trio, e.g. the "Other:" block at ~line 775 and one `elif` branch at ~line 862) and replicate it exactly: declare `box_library` / `col_library` / `km_library_col` alongside the other bucket declarations (place it just before the "Other" declarations), and insert this branch into the dispatch chain BEFORE the final catch-all `elif kmi.idname.startswith("iops."):`:

```python
                    elif kmi.idname.startswith("iops.library"):
                        try:
                            rna_keymap_ui.draw_kmi(
                                ["ADDON", "USER", "DEFAULT"], kc, km, kmi, km_library_col, 0
                            )
                        except AttributeError:
                            pass
```

  (Match the exact `try/except` shape of the neighboring branches — read one first; if neighbors have no try/except, match that instead.)

- [ ] **Step 5: Extend the smoke test.** In `tests/smoke_register.py`, after the existing WM-prop assertions and before `addon_disable`, add:

```python
km = bpy.context.window_manager.keyconfigs.addon.keymaps.get("3D View")
assert km is not None, "addon '3D View' keymap missing"
assert km.space_type == "VIEW_3D", "3D View keymap has wrong space_type"
assert any(
    kmi.idname == "iops.library_popup" for kmi in km.keymap_items
), "iops.library_popup not bound in 3D View keymap"
```

- [ ] **Step 6: Verify.** `python -m py_compile` on all five touched files; run the smoke test (Global Constraints block) → `SMOKE_OK`, no `Traceback`; `python -m pytest tests/ -q` → only the allowed pre-existing failure.

- [ ] **Step 7: Commit.**

```bash
git add utils/functions.py prefs/hotkeys_default.py operators/library/library_popup.py prefs/addon_preferences.py tests/smoke_register.py
git commit -m "feat(library): Ctrl+Alt+Q popup hotkey via IOPS hotkey system"
```

---

### Task 2: Assets pie integration

**Files:**
- Modify: `ui/iops_pie_assets.py`
- Modify: `__init__.py` (one import line + one classes-tuple entry)
- Modify: `tests/smoke_register.py` (one assertion)

**Interfaces:**
- Consumes: `iops.library_popup`, `iops.library_publish` (EnumProperty `publish_kind`: OBJECT/COLLECTION/MATERIAL/SHADER_GROUP).
- Produces: `IOPS_MT_LibraryPublishSub` menu; Assets pie slots 1 and 3 filled.

- [ ] **Step 1: Publish submenu.** In `ui/iops_pie_assets.py`, add after `IOPS_MT_AssetMarkSub` (matching its style):

```python
class IOPS_MT_LibraryPublishSub(Menu):
    """Publish the active datablock into the IOPS master library"""

    bl_idname = "IOPS_MT_LibraryPublishSub"
    bl_label = "Publish to Library"

    def draw(self, context):
        layout = self.layout
        op = layout.operator("iops.library_publish", text="Active Object", icon="OBJECT_DATA")
        op.publish_kind = "OBJECT"
        op = layout.operator("iops.library_publish", text="Active Collection", icon="OUTLINER_COLLECTION")
        op.publish_kind = "COLLECTION"
        op = layout.operator("iops.library_publish", text="Active Material", icon="MATERIAL")
        op.publish_kind = "MATERIAL"
        op = layout.operator("iops.library_publish", text="Shader Group", icon="NODETREE")
        op.publish_kind = "SHADER_GROUP"
```

- [ ] **Step 2: Fill pie slots 1 and 3.** In `IOPS_MT_Pie_Assets.draw`, the six existing `pie.*` calls fill slots 4, 6, 2, 8, 7, 9; append exactly two more at the end of `draw` (the next two calls land in slot 1 = bottom-left, then slot 3 = bottom-right):

```python
        # --- 1 - BOTTOM-LEFT: Library popup ---------------------------------
        pie.operator("iops.library_popup", text="Library Popup", icon="ASSET_MANAGER")

        # --- 3 - BOTTOM-RIGHT: Publish to Library (sub-menu) ----------------
        pie.menu("IOPS_MT_LibraryPublishSub", text="Publish to Library", icon="EXPORT")
```

- [ ] **Step 3: Register.** In `__init__.py`, the file already imports from `.ui.iops_pie_assets` — extend that import with `IOPS_MT_LibraryPublishSub` and add it to the `classes` tuple adjacent to the other `IOPS_MT_*` assets entries. Do not re-sort imports.
- [ ] **Step 4: Smoke assertion.** In `tests/smoke_register.py`, next to the panel assertion add:

```python
assert hasattr(bpy.types, "IOPS_MT_LibraryPublishSub"), "publish submenu not registered"
```

- [ ] **Step 5: Verify.** py_compile on the three touched files; smoke test → `SMOKE_OK`; pytest gate.
- [ ] **Step 6: Commit.**

```bash
git add ui/iops_pie_assets.py __init__.py tests/smoke_register.py
git commit -m "feat(library): popup + publish entries in assets pie"
```

---

### Task 3: Popup theming + blf hygiene

**Files:**
- Modify: `prefs/theme.py` (`IOPS_ThemePreferences` props + Theme-tab rollout)
- Modify: `operators/library/library_popup.py`

**Interfaces:**
- Consumes: `ui/hud/text.py` (`draw(text, x, y, *, theme, role=None, color=None, size_token="normal", ...)`, `measure(text, *, theme, size_token=...) -> (w, h)`); `ui/draw/theme.py` (`get_theme(context) -> Theme`, `Role` enum with `HUD_HEADER`, `HUD_LABEL`, `HUD_LABEL_INACTIVE`); prefs path `get_prefs(context).iops_theme`.
- Produces: 11 `popup_*` color props on `IOPS_ThemePreferences` (auto-included in `.itheme` presets — `operators/preferences/io_theme.py` serializes by iterating `theme.bl_rna.properties`, verify once and note in your report); popup draws all text through the themed blf stack.

- [ ] **Step 1: Theme props.** In `prefs/theme.py`, inside `IOPS_ThemePreferences` after the `panel_bg_*` block, add (using the file's `_color` helper; defaults are EXACTLY the popup's current hardcoded values, so default rendering is unchanged):

```python
    # --- Library popup ---
    popup_bg:             _color((0.055, 0.055, 0.055, 0.98), "Popup Background")
    popup_border:         _color((0.240, 0.240, 0.240, 1.00), "Popup Border")
    popup_header_bg:      _color((0.090, 0.090, 0.090, 1.00), "Popup Header")
    popup_section_bg:     _color((0.115, 0.115, 0.115, 1.00), "Section")
    popup_section_hover:  _color((0.180, 0.180, 0.180, 1.00), "Section Hover")
    popup_tile_bg:        _color((0.095, 0.095, 0.095, 1.00), "Tile")
    popup_tile_hover:     _color((0.200, 0.200, 0.200, 1.00), "Tile Hover")
    popup_label_bg:       _color((0.120, 0.120, 0.120, 1.00), "Tile Label Strip")
    popup_button_bg:      _color((0.150, 0.150, 0.150, 1.00), "Header Button")
    popup_button_hover:   _color((0.240, 0.240, 0.240, 1.00), "Header Button Hover")
    popup_remove_hover:   _color((0.320, 0.120, 0.100, 1.00), "Remove Hover")
```

Then add a "Library Popup" rollout to the Theme tab draw in the same file: read how an existing rollout section is built (e.g. the Background-panel block around line 545) and replicate the idiom, listing the 11 props in the order above.

- [ ] **Step 2: Popup rect colors from theme.** In `operators/library/library_popup.py`, add a small module helper and use it at every `draw_overlay_rectangle` call site, replacing the hardcoded tuples 1:1 (mapping below). The helper reads the prop with a fallback equal to the current constant, so a missing theme never breaks drawing:

```python
def _popup_color(name, fallback):
    prefs = get_prefs(bpy.context)
    theme = getattr(prefs, "iops_theme", None) if prefs else None
    value = getattr(theme, name, None) if theme else None
    return tuple(value) if value is not None else fallback
```

Mapping (old constant → prop name): `(0.24,0.24,0.24,1.0)` border AND header-button-hover → `popup_border` / `popup_button_hover` (border at the panel-outline call site, button-hover inside `draw_header_button`); `(0.055,0.055,0.055,0.98)` → `popup_bg`; `(0.09,0.09,0.09,1.0)` → `popup_header_bg`; `(0.15,0.15,0.15,1.0)` → `popup_button_bg`; `(0.18,0.18,0.18,1.0)` → `popup_section_hover`; `(0.115,0.115,0.115,1.0)` → `popup_section_bg`; `(0.20,0.20,0.20,1.0)` → `popup_tile_hover`; `(0.095,0.095,0.095,1.0)` → `popup_tile_bg`; `(0.12,0.12,0.12,1.0)` → `popup_label_bg`; `(0.32,0.12,0.10,1.0)` → `popup_remove_hover`.

- [ ] **Step 3: Text through the themed blf stack.** In `operators/library/library_popup.py`:
  - Import: `from ...ui.hud import text as hud_text` and `from ...ui.draw.theme import Role, get_theme`.
  - Delete the local `draw_overlay_text` function.
  - In `draw_overlay`, resolve `theme = get_theme(context)` once at the top and pass it down (add a `theme` parameter to `draw_header_button` or make it read `get_theme(bpy.context)` — prefer the parameter).
  - Replace every text call site:
    - Panel title "IOPS Library" → `hud_text.draw(..., theme=theme, role=Role.HUD_HEADER, size_token="hud_header")`.
    - Category rows (the `v`/`>` glyph and "%s (%d)" label), header buttons, tile name labels, and the remove "X" → `role=Role.HUD_LABEL, size_token="hud_label"`.
    - The no-thumbnail fallback text on tiles → `role=Role.HUD_LABEL_INACTIVE, size_token="hud_label"`.
  - Replace both `blf.size(0, ...)` + `blf.dimensions(0, ...)` measurement pairs with `hud_text.measure(label, theme=theme, size_token=...)` using the same size_token as the corresponding draw.
  - Remove the now-unused `import blf` if nothing else in the file uses blf.
  - Layout metrics (tile/label/row heights, the `maximum_characters` truncation heuristic) stay EXACTLY as they are — this task changes text rendering and rect color sourcing only.
- [ ] **Step 4: Verify.** py_compile on both files; smoke test → `SMOKE_OK`; pytest gate. In your report, note the io_theme serialization check result (bl_rna.properties iteration ⇒ popup props included in .itheme save).
- [ ] **Step 5: Commit.**

```bash
git add prefs/theme.py operators/library/library_popup.py
git commit -m "feat(library): theme-driven popup colors + themed blf text"
```
