# Vertex Color Preview Toggle + Black/White Swatches Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a one-click "Preview VC" toggle (renders every object as its vertex color, unlit, in EEVEE and Cycles, reversibly) and Black/White fill swatches to the Vertex Color widget.

**Architecture:** The toggle is a scene bool (`scene.IOPS.iops_vc_preview`) with an update callback that calls `vc_preview_set()`, which drives `view_layer.material_override` with a reused temp emission material (`IOPS_VC_Preview`) and switches/restores viewport shading. Black/White reuse the existing explicit-color override on `iops.mesh_assign_vertex_color`. No widget-framework changes.

**Tech Stack:** Blender 5.1.2 `bpy` (shader nodes, `view_layer.material_override`); the iOps GPU widget framework (JSON defs); pytest for the bpy-free validation check only.

## Global Constraints

- Target Blender **5.1.2**. `view_layer.material_override` renders under both EEVEE (Next) and Cycles.
- Existing behavior of `iops.mesh_assign_vertex_color` is unchanged; Black/White drive it via `op_kwargs` (`use_override_color`/`override_color`), like R/G/B.
- No widget-framework changes — literal-color `SWATCH` and `prop`-bound `FLIPBOX` already exist.
- The preview must be **fully reversible**: toggle off clears `view_layer.material_override` and restores the stored viewport shading. Zero user materials are mutated.
- The widget JSON lives in the Blender user-scripts folder `B:\scripts\presets\iops\widgets\vertex_color.json` (NOT repo-tracked — every widget follows this convention).
- `widgets/composed.py` stays bpy-free; `python -m pytest tests -q` must show no NEW failures (one pre-existing unrelated `test_polygon_match` failure is known).
- Live Blender verification runs through the `blender` MCP (controller), addon reloaded via disable → purge `sys.modules['InteractionOps.*']` → enable.

---

### Task 1: Preview backend — `vc_preview_set` + scene props

**Files:**
- Modify: `operators/assign_vertex_color.py` (add module-level constant + 3 functions after the imports, before `class IOPS_OT_VertexColorAssign` at line 5)
- Modify: `prefs/addon_properties.py` (add an update callback before `class IOPS_SceneProperties` at line 242; add two props after `iops_vertex_color` at line 287)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `assign_vertex_color.vc_preview_set(context, enable: bool) -> None` — toggles the preview.
  - `assign_vertex_color.VC_PREVIEW_MAT = "IOPS_VC_Preview"`.
  - `assign_vertex_color._build_vc_preview_material(layer_name: str)` and `_active_view3d_space(context)` helpers.
  - Scene props `scene.IOPS.iops_vc_preview: bool` (with update callback) and `scene.IOPS.iops_vc_preview_prev_shading: str` (hidden).

This task is bpy-dependent — verified live in Blender by the controller (no pytest).

- [ ] **Step 1: Add the helper functions + constant to `operators/assign_vertex_color.py`**

Insert immediately after line 3 (`from bpy.props import FloatProperty, BoolProperty`) and before the blank line preceding `class IOPS_OT_VertexColorAssign`:

```python

VC_PREVIEW_MAT = "IOPS_VC_Preview"


def _active_view3d_space(context):
    """Return the active VIEW_3D space to switch shading on, or None."""
    sd = getattr(context, "space_data", None)
    if sd is not None and sd.type == "VIEW_3D":
        return sd
    screen = getattr(context, "screen", None)
    if screen is not None:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                return area.spaces.active
    return None


def _build_vc_preview_material(layer_name):
    """Create or refresh the IOPS_VC_Preview material: a Color Attribute node
    feeding an Emission into the Material Output (unlit, engine-agnostic)."""
    mat = bpy.data.materials.get(VC_PREVIEW_MAT)
    if mat is None:
        mat = bpy.data.materials.new(VC_PREVIEW_MAT)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    vcol = nt.nodes.new("ShaderNodeVertexColor")
    vcol.layer_name = layer_name or ""
    vcol.location = (-300.0, 0.0)
    emit = nt.nodes.new("ShaderNodeEmission")
    emit.location = (0.0, 0.0)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (300.0, 0.0)
    nt.links.new(emit.inputs["Color"], vcol.outputs["Color"])
    nt.links.new(out.inputs["Surface"], emit.outputs["Emission"])
    return mat


def vc_preview_set(context, enable):
    """Toggle the vertex-color preview via view_layer.material_override.

    enable=True: build/reuse IOPS_VC_Preview from the active object's active
    color attribute, set it as the view-layer override, and switch the active
    VIEW_3D to Rendered (storing the previous shading). enable=False: clear the
    override and restore the stored shading. Safe from a UI property update
    (data-API only, no operator calls)."""
    scene_props = context.scene.IOPS
    view_layer = context.view_layer
    if enable:
        obj = context.object
        layer_name = ""
        if obj is not None and obj.type == "MESH":
            active = obj.data.color_attributes.active_color
            if active is not None:
                layer_name = active.name
        view_layer.material_override = _build_vc_preview_material(layer_name)
        space = _active_view3d_space(context)
        if space is not None:
            if not scene_props.iops_vc_preview_prev_shading:
                scene_props.iops_vc_preview_prev_shading = space.shading.type
            space.shading.type = "RENDERED"
    else:
        view_layer.material_override = None
        space = _active_view3d_space(context)
        if space is not None and scene_props.iops_vc_preview_prev_shading:
            space.shading.type = scene_props.iops_vc_preview_prev_shading
        scene_props.iops_vc_preview_prev_shading = ""
    area = getattr(context, "area", None)
    if area is not None:
        area.tag_redraw()

```

- [ ] **Step 2: Add the update callback to `prefs/addon_properties.py`**

Insert immediately before `class IOPS_SceneProperties(PropertyGroup):` (line 242):

```python
def _iops_vc_preview_update(self, context):
    # Lazy import avoids a circular import at module load; assign_vertex_color
    # imports only bpy, so this is safe.
    from ..operators.assign_vertex_color import vc_preview_set
    vc_preview_set(context, self.iops_vc_preview)


```

- [ ] **Step 3: Add the two scene properties**

In `prefs/addon_properties.py`, inside `IOPS_SceneProperties`, immediately after the `iops_vertex_color` property block (ends at line 287) and before the `# Object Color picker ...` comment:

```python
    iops_vc_preview: BoolProperty(
        name="Preview VC",
        description="Preview vertex color in the viewport via a temporary "
                    "emission material override (EEVEE and Cycles)",
        default=False,
        update=_iops_vc_preview_update,
    )
    iops_vc_preview_prev_shading: StringProperty(
        name="VC Preview Previous Shading",
        description="Viewport shading type to restore when the preview is off",
        default="",
        options={"HIDDEN"},
    )
```

(`BoolProperty` and `StringProperty` are already imported at the top of the file.)

- [ ] **Step 4: Syntax-check both files**

Run:
```bash
cd "D:/git/InteractionOps" && python -c "import ast; ast.parse(open('operators/assign_vertex_color.py').read()); ast.parse(open('prefs/addon_properties.py').read()); print('AST OK')"
```
Expected: `AST OK`

- [ ] **Step 5: Run the full test suite (no regression)**

Run: `python -m pytest tests -q`
Expected: no NEW failures (only the known pre-existing `test_polygon_match` failure).

- [ ] **Step 6: Live-verify in Blender (controller)**

Reload the addon, then via `execute_blender_code` (with at least one mesh in the scene):
```python
import bpy
sp = bpy.context.scene.IOPS
sp.iops_vc_preview = True
vl = bpy.context.view_layer
on = {
    'override': vl.material_override.name if vl.material_override else None,
    'nodes': sorted(n.bl_idname for n in bpy.data.materials['IOPS_VC_Preview'].node_tree.nodes),
    'prev_shading_stored': sp.iops_vc_preview_prev_shading,
}
sp.iops_vc_preview = False
off = {'override': vl.material_override, 'prev_shading_cleared': sp.iops_vc_preview_prev_shading == ""}
print(on, off)
```
Expected: on → override `IOPS_VC_Preview`, nodes include `ShaderNodeVertexColor`, `ShaderNodeEmission`, `ShaderNodeOutputMaterial`, a shading type stored; off → override `None`, stored shading cleared. (If a socket name lookup raises, fall back to index sockets and report — but `"Color"`/`"Emission"`/`"Surface"` are correct on 5.1.2.)

- [ ] **Step 7: Commit**

```bash
git add operators/assign_vertex_color.py prefs/addon_properties.py
git commit -m "feat(vertex-color): preview toggle via view_layer material override"
```

---

### Task 2: Widget JSON — Black/White swatches + Preview flipbox

**Files:**
- Modify: `B:/scripts/presets/iops/widgets/vertex_color.json` (Blender user-scripts folder; not repo-tracked)

**Interfaces:**
- Consumes: `iops.mesh_assign_vertex_color` explicit-color override (existing); `scene.IOPS.iops_vc_preview` (Task 1).
- Produces: the updated `vertex_color` widget (7 rows).

- [ ] **Step 1: Replace the widget JSON with the full 7-row definition**

Write `B:/scripts/presets/iops/widgets/vertex_color.json` with exactly:

```json
{
  "version": 1,
  "name": "vertex_color",
  "title": "Vertex Color",
  "space": "VIEW_3D",
  "rows": [
    {"type": "SECTION", "label": "Fill RGB"},
    {"type": "ROW", "cells": [
      {"type": "SWATCH", "color": [1, 0, 0, 1], "label": "R",
       "op": "iops.mesh_assign_vertex_color",
       "op_kwargs": {"use_override_color": true, "override_color": [1, 0, 0, 1]}},
      {"type": "SWATCH", "color": [0, 1, 0, 1], "label": "G",
       "op": "iops.mesh_assign_vertex_color",
       "op_kwargs": {"use_override_color": true, "override_color": [0, 1, 0, 1]}},
      {"type": "SWATCH", "color": [0, 0, 1, 1], "label": "B",
       "op": "iops.mesh_assign_vertex_color",
       "op_kwargs": {"use_override_color": true, "override_color": [0, 0, 1, 1]}}
    ]},
    {"type": "ROW", "cells": [
      {"type": "SWATCH", "color": [0, 0, 0, 1], "label": "",
       "op": "iops.mesh_assign_vertex_color",
       "op_kwargs": {"use_override_color": true, "override_color": [0, 0, 0, 1]}},
      {"type": "SWATCH", "color": [1, 1, 1, 1], "label": "",
       "op": "iops.mesh_assign_vertex_color",
       "op_kwargs": {"use_override_color": true, "override_color": [1, 1, 1, 1]}}
    ]},
    {"type": "SECTION", "label": "Alpha", "show_if": {"mode": "EDIT_MESH"}},
    {"type": "ROW", "show_if": {"mode": "EDIT_MESH"}, "cells": [
      {"type": "SWATCH", "color": [0.5, 0.5, 0.5, 0], "show_alpha": true, "label": "A0",
       "op": "iops.mesh_assign_vertex_color_alpha",
       "op_kwargs": {"vertex_color_alpha": 0.0}},
      {"type": "SWATCH", "color": [0.5, 0.5, 0.5, 1], "show_alpha": true, "label": "A1",
       "op": "iops.mesh_assign_vertex_color_alpha",
       "op_kwargs": {"vertex_color_alpha": 1.0}}
    ]},
    {"type": "SECTION", "label": "Preview"},
    {"type": "FLIPBOX", "prop": "scene.IOPS.iops_vc_preview", "label": "Preview VC (Rendered)"}
  ]
}
```

- [ ] **Step 2: Validate bpy-free**

Run:
```bash
cd "D:/git/InteractionOps" && python -c "import json,sys; sys.path.insert(0,'.'); from widgets import composed; d=json.load(open('B:/scripts/presets/iops/widgets/vertex_color.json')); c,e=composed.validate_def(d); print('errors:', e); print('rows:', [r['type'] for r in c['rows']])"
```
Expected: `errors: []` and `rows: ['SECTION', 'ROW', 'ROW', 'SECTION', 'ROW', 'SECTION', 'FLIPBOX']`.

- [ ] **Step 3: Live-verify in Blender (controller)**

Reload addon, then with a mesh in Edit Mesh with a vertex selection:
```python
import bpy
from InteractionOps.widgets import composed
composed.load_all()
bpy.ops.iops.widget_toggle(name="vertex_color")
```
Checks: Black swatch fills selection `(0,0,0,1)`, White `(1,1,1,1)` (read via bmesh float_color layer). The Preview flipbox toggles `scene.IOPS.iops_vc_preview` on/off and the viewport shows/clears the vertex-color override. Screenshot the panel: Fill RGB (R/G/B), a black+white row, Alpha (A0/A1), Preview flipbox.

- [ ] **Step 4: No git commit (file is outside the repo)**

The JSON is user data in the Blender scripts folder and is not tracked. Note in the report that Step 1 wrote it and Step 2 validated it; there is nothing to `git add`.

---

### Task 3: Documentation

**Files:**
- Modify: `docs/operators/op_assign_vertex_color.md` (append a "Vertex Color Preview" section)

**Interfaces:**
- Consumes: Task 1 (the scene props + helper).
- Produces: docs only.

- [ ] **Step 1: Document the preview toggle + black/white swatches**

In `docs/operators/op_assign_vertex_color.md`, append before the final `## Related` section (or at the end if none):

```markdown
## Vertex Color Preview (viewport)

A reversible viewport preview of the active color attribute, driven by the
Vertex Color widget's **Preview VC** toggle (`scene.IOPS.iops_vc_preview`).

- Turning it on builds/reuses a temporary material `IOPS_VC_Preview`
  (Color Attribute → Emission → Material Output) and assigns it to
  `view_layer.material_override`, then switches the active 3D viewport to
  Rendered shading. Emission is unlit, so the raw vertex color reads correctly
  in both **EEVEE** and **Cycles**.
- Turning it off clears the override and restores the previous viewport shading
  (stored in `scene.IOPS.iops_vc_preview_prev_shading`).
- Implemented by `vc_preview_set(context, enable)` in
  `operators/assign_vertex_color.py`; the toggle is view-layer-wide (every
  object renders as its vertex color while active) and mutates no user materials.

The widget's **Black** and **White** fill swatches use the same explicit-color
override as R/G/B (`use_override_color` with `override_color` `(0,0,0,1)` /
`(1,1,1,1)`).
```

- [ ] **Step 2: Commit**

```bash
git add docs/operators/op_assign_vertex_color.md
git commit -m "docs(vertex-color): preview toggle + black/white swatches"
```

---

## Self-Review

**Spec coverage:**
- Preview mechanism (material_override + temp emission material) → Task 1. ✓
- `layer_name` from active color attribute, `""` fallback → Task 1 `vc_preview_set`. ✓
- Scene bool + update callback + prev-shading store/restore → Task 1. ✓
- Rendered shading switch + restore → Task 1. ✓
- Black/White swatches (override path) → Task 2 JSON. ✓
- Preview flipbox bound to `scene.IOPS.iops_vc_preview` → Task 2 JSON. ✓
- 7-row layout → Task 2 validate step (`['SECTION','ROW','ROW','SECTION','ROW','SECTION','FLIPBOX']`). ✓
- bpy-free JSON validation + live Blender verify → Tasks 1-2. ✓
- Docs → Task 3. ✓

**Placeholder scan:** No TBD/TODO; every code step is complete. The only "fallback" note (socket-by-index) is a concrete contingency with the correct names stated, not a gap.

**Type consistency:** `vc_preview_set(context, enable)`, `VC_PREVIEW_MAT`, `_build_vc_preview_material`, `_active_view3d_space`, `iops_vc_preview`, `iops_vc_preview_prev_shading`, `_iops_vc_preview_update` are named identically across Task 1's code, the Task 2 flipbox `prop` path (`scene.IOPS.iops_vc_preview`), and the Task 3 docs. The update callback's lazy import path `..operators.assign_vertex_color` matches the helper's home file.
