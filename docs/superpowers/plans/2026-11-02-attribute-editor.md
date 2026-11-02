# iOps Attribute Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A sidebar panel that lists a mesh's generic attributes, edits the active attribute's value on the selection, previews it in the viewport and offers attribute tools Blender lacks.

**Architecture:** Pure logic in `utils/attribute_editor_core.py` (type table, filtering, maths, predicates); bmesh / `mesh.attributes` backends and every `iops.attr_*` operator in `operators/mesh_attribute_editor.py`; a WindowManager mirror + UIList + panel + value fields with get/set callbacks + app handlers + preview overlay in `ui/iops_attribute_panel.py`, following `ui/iops_selection_sets_panel.py` (mirror) and `operators/mesh_nonplanar_overlay.py` (overlay reads `obj.to_mesh()`, never Python bmesh from handlers).

**Tech Stack:** Blender 5.2.3 LTS, bpy / bmesh / gpu / blf, numpy, pytest for the core module, headless Blender scripts under `tests/blender/`.

**Spec:** `docs/superpowers/specs/2026-11-02-attribute-editor-design.md`

## Global Constraints

- Blender 5.2.3 LTS; bmesh layer accessors available: `bool, color, deform, float, float_color, float_vector, int, string`.
- Handlers and draw callbacks never touch Python bmesh; they read `obj.to_mesh()` (Edit Mode) or `obj.data` (Object Mode) with `foreach_get`. bmesh is read only once per selection change (active element) and written only inside operators.
- Every tool and button is an operator with `bl_options = {"REGISTER", "UNDO"}`; the value fields write directly from their setters (drag-friendly) and push one debounced `ed.undo_push` 0.3 s after the last tick; panel `draw()` never writes RNA.
- Multi-object Edit Mode: the active object defines the list, the value cache, `Mixed` and the `active_index` sync; writes and tools fan out to every edit mesh with the same (name, domain, data_type).
- While `context.window.modal_operators` is non-empty, no bmesh read happens in handlers; the cache shows the first selected element with `(first)`.
- `.iops_ss_*` layers (`selection_sets_core.ATTR_PREFIX`) are never listed, even with `show_hidden`.
- Handlers are gated: no work unless `draw()` ran in the last 1.0 s or a preview is on.
- Naming: operators `iops.attr_*`, classes `IOPS_OT_Attr*`, panel `IOPS_PT_attributes_panel` (label `iOps Attributes`, category `iOps`), UIList `IOPS_UL_Attributes`, menu `IOPS_MT_attr_specials`, WM pointer `WindowManager.iops_attr`.
- Core module imports no `bpy`; tests import it as `utils.attribute_editor_core` (see `tests/conftest.py`).
- Headless tests run as `blender --background --factory-startup --python-exit-code 1 --python tests/blender/<file>.py` with every `BLENDER_USER_*` variable pointed at a scratch dir (see the headless-blender-env note in memory).
- Ruff config `ruff.toml` applies (`ruff check <files>` clean).

## Review Focus

1. Multi-object Edit Mode where only some meshes carry the attribute: writes must skip meshes without it and not create it (Task 3 test `test_write_skips_meshes_without_attr`).
2. Attribute deleted or renamed in the Properties editor while the panel is open: the mirror must rebuild and `index` must clamp, no `KeyError` in `draw()` (Task 5 test `test_mirror_clamps_after_remove`).
3. Hidden elements (`.hide_vert`): never written by Set on selection and never labelled by the preview (Task 3 test `test_write_ignores_hidden`, Task 7 `labels_skip_hidden`).
4. A face selection with CORNER attribute: edits reach every loop of every selected face and the value shown is the active face's first corner (Task 3 test `test_corner_write_all_loops`).
5. Empty mesh or an object that is not a mesh under the cursor while a preview is on: the overlay disables itself without exceptions (Task 7 test `preview_disables_on_non_mesh`).

---

### Task 1: Core — type table, row listing, formatting

**Files:**
- Create: `utils/attribute_editor_core.py`
- Test: `tests/test_attribute_editor_core.py`

**Interfaces:**
- Produces:
  - `DOMAINS = ("POINT", "EDGE", "FACE", "CORNER")`
  - `TypeInfo = namedtuple("TypeInfo", "bm_layer widget components preview")` where `bm_layer` is the bmesh accessor name or `None`, `widget` in `{"FLOAT","INT","BOOL","VECTOR","COLOR","STRING","READONLY"}`, `components` int, `preview` frozenset of `{"LABELS","HEATMAP","GREYSCALE","COLOUR"}`.
  - `TYPES: dict[str, TypeInfo]` for the 14 data types of the spec table, plus key `"VGROUP"` (`bm_layer="deform"`, widget `FLOAT`, 1, labels+heatmap).
  - `BUILTIN_NAMES = frozenset({"position","sharp_edge","sharp_face","material_index","crease_vert","crease_edge","bevel_weight_vert","bevel_weight_edge"})`
  - `Row = namedtuple("Row", "name data_type domain kind editable")`
  - `list_rows(attributes, vertex_groups, *, show_hidden=False, show_builtin=False, show_vgroups=True, uv_names=(), color_names=(), edit_mode=True) -> list[Row]` — `attributes` is an iterable of `(name, data_type, domain)`, `vertex_groups` an iterable of names. `editable` = `TYPES[t].bm_layer is not None` in edit mode, `True` otherwise (STRING always `False`). Order: domain order then name; VGROUP rows last, in vertex-group order.
  - `editor_rows(rows, active_name, select_mode) -> list[Row]` — `select_mode` is the `(vert, edge, face)` triple; returns the active row first (if any), then the rows whose domain matches: vert→POINT, edge→EDGE, face→FACE and CORNER; no duplicates.
  - `format_value(value, data_type, decimals=2) -> str` — floats `f"{v:.{decimals}f}"`, ints as is, bools `"1"/"0"`, sequences joined with a space, strings as is.
  - `unique_name(name, taken) -> str` — `.001` suffix rule (same as `selection_sets_core.unique_name`; reuse by import).

- [ ] **Step 1: Write the failing tests**

```python
from utils.attribute_editor_core import (TYPES, BUILTIN_NAMES, Row, list_rows,
                                         editor_rows, format_value)

def test_type_table_edit_support():
    assert TYPES["FLOAT"].bm_layer == "float"
    assert TYPES["BYTE_COLOR"].bm_layer == "color"
    assert TYPES["INT8"].bm_layer is None
    assert TYPES["FLOAT2"].bm_layer is None
    assert TYPES["VGROUP"].bm_layer == "deform"
    assert "HEATMAP" in TYPES["FLOAT_VECTOR"].preview
    assert "COLOUR" in TYPES["FLOAT_COLOR"].preview

def test_list_rows_filters_hidden_builtin_and_orders():
    attrs = [(".select_vert", "BOOLEAN", "POINT"), ("tilt", "FLOAT", "POINT"),
             ("sharp_edge", "BOOLEAN", "EDGE"), ("bw", "FLOAT", "EDGE"),
             ("UVMap", "FLOAT2", "CORNER"), ("Col", "BYTE_COLOR", "CORNER"),
             ("id", "INT", "FACE"), ("q", "QUATERNION", "POINT")]
    rows = list_rows(attrs, ["marks"], uv_names=("UVMap",), color_names=("Col",))
    assert [r.name for r in rows] == ["q", "tilt", "bw", "id", "marks"]
    assert rows[0].editable is False and rows[1].editable is True
    assert rows[-1] == Row("marks", "VGROUP", "POINT", "VGROUP", True)
    attrs.append((".iops_ss_V_bolts", "INT", "POINT"))
    rows = list_rows(attrs, [], show_hidden=True, show_builtin=True, show_vgroups=False)
    assert ".select_vert" in [r.name for r in rows]
    assert ".iops_ss_V_bolts" not in [r.name for r in rows]
    assert "sharp_edge" in [r.name for r in rows] and "UVMap" in [r.name for r in rows]

def test_list_rows_object_mode_everything_editable_but_string():
    rows = list_rows([("a", "INT8", "POINT"), ("s", "STRING", "POINT")], [], edit_mode=False)
    assert [r.editable for r in rows] == [True, False]

def test_editor_rows_active_first_then_select_mode_domain():
    rows = [Row("tilt", "FLOAT", "POINT", "ATTR", True), Row("bw", "FLOAT", "EDGE", "ATTR", True),
            Row("id", "INT", "FACE", "ATTR", True), Row("c", "FLOAT_COLOR", "CORNER", "ATTR", True)]
    assert [r.name for r in editor_rows(rows, "bw", (True, False, False))] == ["bw", "tilt"]
    assert [r.name for r in editor_rows(rows, "id", (False, False, True))] == ["id", "c"]
    assert [r.name for r in editor_rows(rows, None, (False, True, False))] == ["bw"]

def test_format_value():
    assert format_value(45.0, "FLOAT") == "45.00"
    assert format_value(45.0, "FLOAT", decimals=0) == "45"
    assert format_value((1.0, 2.5, 0.0), "FLOAT_VECTOR", decimals=1) == "1.0 2.5 0.0"
    assert format_value(True, "BOOLEAN") == "1"
    assert format_value(7, "INT") == "7"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/git/InteractionOps && python -m pytest tests/test_attribute_editor_core.py -v`
Expected: FAIL with `ModuleNotFoundError: utils.attribute_editor_core`

- [ ] **Step 3: Implement the interfaces above in `utils/attribute_editor_core.py`**

Import `unique_name` from `utils.selection_sets_core` (relative-import-free: the core modules import each other as `from .selection_sets_core import unique_name` and tests load them as `utils.*`; match how `utils/falloff_core.py` imports, if it imports anything).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_attribute_editor_core.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add utils/attribute_editor_core.py tests/test_attribute_editor_core.py
git commit -m "feat(attr-editor): core type table and row listing"
```

---

### Task 2: Core — value maths, chains, predicates, heatmap

**Files:**
- Modify: `utils/attribute_editor_core.py`
- Test: `tests/test_attribute_editor_core.py`

**Interfaces:**
- Produces (all pure, lists in → lists out, no numpy required):
  - `default_value(data_type)` — `0.0`, `0`, `False`, `(0,0,0)`, `(0,0,0,1)` for colours, `""`, `(1,0,0,0)` for QUATERNION, `(0,0)` for 2D types, `(0,)*4` FLOAT4, identity 16-tuple FLOAT4X4.
  - `coerce(value, src_type, dst_type, component=0)` — float/int/bool between each other (`bool→1.0`, `float→int` truncates toward zero, `int/float→bool` nonzero); vector/colour → scalar picks `component`; scalar → vector/colour broadcasts to all components (alpha stays 1.0); same type passthrough; unsupported → `None`.
  - `mixed_count(values) -> int` — number of distinct values (tuples compared exactly, floats with `abs diff <= 1e-6`).
  - `math_op(values, op, a=0.0, b=1.0)` — `ADD` (+a), `MULTIPLY` (*a), `CLAMP` (to [a,b]), `INVERT` (1 − v for floats, `not v` for bools, −v for ints), `REMAP` (from [min(values), max(values)] to [a,b]; constant input → a), `ROUND` (to `a` decimals, int(a)); vectors apply per component.
  - `randomize(n, lo, hi, seed, data_type)` — `random.Random(seed)`; ints via `randint`, bools via `random() < 0.5`, vectors per component.
  - `smooth(values, neighbours, iterations=1, factor=0.5)` — Laplacian: `v + factor * (mean(neighbours) − v)`, `neighbours[i]` a list of indices into `values`, elements without neighbours unchanged; vectors per component.
  - `order_chain(vert_indices, edges) -> list[int] | None` — `edges` iterable of `(a, b)` over the selected verts; returns the verts ordered along a single open path (degree ≤ 2, exactly two ends) or a closed loop (all degree 2; start at `min(vert_indices)`), `None` if branching, disconnected, or fewer than 2 verts.
  - `gradient(n, v0, v1, mode="LINEAR")` — `n` values from `v0` to `v1`; `EASE_IN_OUT` uses smoothstep `t*t*(3-2t)`; vectors per component; `n == 1` → `[v0]`.
  - `select_predicate(op, ref, tol=1e-6, hi=None)` — returns `f(value) -> bool`; ops `EQUAL`, `NOT_EQUAL`, `LESS`, `GREATER`, `RANGE` (`ref..hi` inclusive); vectors compare length for LESS/GREATER/RANGE and exact-within-tol per component for EQUAL.
  - `HEATMAP_RAMP = ((0,0,1),(0,1,1),(0,1,0),(1,1,0),(1,0,0))`; `heat_color(t) -> (r,g,b)` piecewise-linear over the ramp, `t` clamped to [0,1].
  - `luminance(rgba) -> float` — `0.2126 r + 0.7152 g + 0.0722 b`.
  - `scalar_for_preview(value, data_type) -> float` — numbers as is, bools 0/1, vectors length, colours luminance.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from utils.attribute_editor_core import (default_value, coerce, mixed_count, math_op,
    randomize, smooth, order_chain, gradient, select_predicate, heat_color,
    luminance, scalar_for_preview)

def test_coerce_scalars_and_vectors():
    assert coerce(2.7, "FLOAT", "INT") == 2
    assert coerce(True, "BOOLEAN", "FLOAT") == 1.0
    assert coerce((1.0, 2.0, 3.0), "FLOAT_VECTOR", "FLOAT", component=2) == 3.0
    assert coerce(0.5, "FLOAT", "FLOAT_COLOR") == (0.5, 0.5, 0.5, 1.0)
    assert coerce("x", "STRING", "FLOAT") is None

def test_mixed_count():
    assert mixed_count([1.0, 1.0000001, 2.0]) == 2
    assert mixed_count([(1, 2, 3), (1, 2, 3)]) == 1

def test_math_ops():
    assert math_op([1.0, 2.0], "ADD", a=1.0) == [2.0, 3.0]
    assert math_op([1.0, 2.0], "MULTIPLY", a=2.0) == [2.0, 4.0]
    assert math_op([-1.0, 5.0], "CLAMP", a=0.0, b=1.0) == [0.0, 1.0]
    assert math_op([0.25], "INVERT") == [0.75]
    assert math_op([True], "INVERT") == [False]
    assert math_op([10.0, 20.0, 30.0], "REMAP", a=0.0, b=1.0) == [0.0, 0.5, 1.0]
    assert math_op([5.0, 5.0], "REMAP", a=2.0, b=3.0) == [2.0, 2.0]
    assert math_op([1.26], "ROUND", a=1) == [1.3]
    assert math_op([(1.0, 2.0, 3.0)], "MULTIPLY", a=2.0) == [(2.0, 4.0, 6.0)]

def test_randomize_is_seeded_and_bounded():
    a = randomize(5, 0.0, 10.0, 7, "FLOAT"); b = randomize(5, 0.0, 10.0, 7, "FLOAT")
    assert a == b and all(0.0 <= v <= 10.0 for v in a)
    assert all(isinstance(v, int) for v in randomize(3, 1, 3, 1, "INT"))

def test_smooth_moves_toward_neighbour_mean():
    out = smooth([0.0, 10.0, 0.0], [[1], [0, 2], [1]], iterations=1, factor=0.5)
    assert out[1] == pytest.approx(5.0) and out[0] == pytest.approx(5.0)
    assert smooth([3.0], [[]], iterations=3) == [3.0]

def test_order_chain_path_loop_and_branch():
    assert order_chain([5, 2, 9], [(2, 5), (9, 2)]) in ([5, 2, 9], [9, 2, 5])
    loop = order_chain([1, 2, 3], [(1, 2), (2, 3), (3, 1)])
    assert loop[0] == 1 and sorted(loop) == [1, 2, 3]
    assert order_chain([1, 2, 3, 4], [(1, 2), (2, 3), (2, 4)]) is None
    assert order_chain([1, 2, 3, 4], [(1, 2), (3, 4)]) is None
    assert order_chain([1], []) is None

def test_gradient():
    assert gradient(3, 0.0, 10.0) == [0.0, 5.0, 10.0]
    assert gradient(3, 0.0, 10.0, "EASE_IN_OUT") == [0.0, 5.0, 10.0]
    assert gradient(5, 0.0, 1.0, "EASE_IN_OUT")[1] == pytest.approx(0.15625)
    assert gradient(1, 2.0, 9.0) == [2.0]
    assert gradient(2, (0.0, 0.0, 0.0), (1.0, 2.0, 3.0)) == [(0.0, 0.0, 0.0), (1.0, 2.0, 3.0)]

def test_select_predicate():
    assert select_predicate("EQUAL", 45.0, tol=0.01)(45.005)
    assert not select_predicate("EQUAL", 45.0)(46.0)
    assert select_predicate("RANGE", 1.0, hi=2.0)(1.5) and not select_predicate("RANGE", 1.0, hi=2.0)(2.5)
    assert select_predicate("GREATER", 1.0)((0.0, 2.0, 0.0))

def test_heatmap_and_luminance():
    assert heat_color(0.0) == (0, 0, 1) and heat_color(1.0) == (1, 0, 0)
    assert heat_color(0.5) == (0, 1, 0)
    assert heat_color(0.125) == pytest.approx((0, 0.5, 1))
    assert luminance((1, 1, 1, 1)) == pytest.approx(1.0)
    assert scalar_for_preview((3.0, 4.0, 0.0), "FLOAT_VECTOR") == 5.0
    assert default_value("FLOAT_COLOR") == (0.0, 0.0, 0.0, 1.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_attribute_editor_core.py -v`
Expected: the new tests FAIL with `ImportError`

- [ ] **Step 3: Implement the functions in `utils/attribute_editor_core.py`**

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_attribute_editor_core.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add utils/attribute_editor_core.py tests/test_attribute_editor_core.py
git commit -m "feat(attr-editor): core maths, chains, predicates, heatmap"
```

---

### Task 3: Backend — read and write attributes per type and domain

**Files:**
- Create: `operators/mesh_attribute_editor.py`
- Test: `tests/blender/test_attribute_editor.py` (new; copy the `enable_addon()` helper from `tests/blender/test_object_search_rename.py`)

**Interfaces:**
- Consumes: Task 1/2 core (`TYPES`, `DOMAINS`, `coerce`, `default_value`).
- Produces (module `operators/mesh_attribute_editor.py`, all take `obj`/`bm` explicitly, no `bpy.context` inside):
  - `edit_meshes(context) -> list[tuple[Object, BMesh]]` — every mesh in multi-object edit via `bmesh.from_edit_mesh`.
  - `bm_seq(bm, domain)` — `verts` / `edges` / `faces`; CORNER returns `None` (loops are reached through faces).
  - `bm_layer(bm, row)` — the layer for a `Row` (`kind == "VGROUP"` → `bm.verts.layers.deform.verify()`), `None` when missing or the type has no bmesh layer.
  - `bm_selected_indices(bm, domain) -> list[int]` — selected, unhidden elements of that domain; CORNER → indices of selected faces.
  - `bm_active_index(bm, domain) -> int | None` — from `bm.select_history.active` if it is of the domain (CORNER → active face), else `None`.
  - `bm_read(bm, row, index)` — one value (vertex-group row: `v[deform].get(group_index, 0.0)`; CORNER: the face's first loop).
  - `bm_write(bm, row, indices, value, *, group_index=None)` — writes `value` on the indices (CORNER: all loops of those faces; VGROUP: `v[deform][group_index] = value`); returns the number of elements written.
  - `bm_values(bm, row, indices) -> list` and `bm_write_values(bm, row, indices, values)` — per-element lists (used by the tools).
  - `mesh_read_all(me, name) -> list` and `mesh_write_all(me, name, value)` — Object Mode through `attributes[name].data.foreach_set/get`, any data type (vector/colour/2D via flattened arrays, STRING via per-item loop).
  - `snapshot(obj, name, domain) -> tuple(np positions, np values, np selected, np hidden)` — handler-safe read: `obj.to_mesh()` in Edit Mode (`to_mesh_clear()` in `finally`), `obj.data` in Object Mode; positions in world space per domain (vertex, edge midpoint, `polygons.center`, corner at 75 % vertex + 25 % face centre). Vertex-group rows read through `obj.vertex_groups` weight on the temp mesh (`me.vertices[i].groups`). Returns `None` for non-mesh objects.
  - `vgroup_index(obj, name) -> int | None`.
  - `finish_edit(obj)` — `bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)`.

- [ ] **Step 1: Write the failing headless test**

In `tests/blender/test_attribute_editor.py`, helpers `_track_mesh()` building a 6-vertex path mesh (`bpy.data.meshes.new` + `from_pydata`, 5 edges, no faces) with FLOAT POINT `tilt` = `[0,10,20,30,40,50]`, a `scale` attribute, a vertex group `marks`, and a 2-face quad mesh `_quad_mesh()` with a FLOAT CORNER attribute `c` and `.hide_vert` on one vertex of face 2. Tests (each enters Edit Mode with `bpy.ops.object.mode_set`, selects via bmesh, calls the backend, exits, reads `me.attributes[...]`):

```python
def test_bm_write_selected_only():       # select verts 1,2 → bm_write(…, 45.0) → tilt == [0,45,45,30,40,50]
def test_write_ignores_hidden():          # hide vert 0 + select all → written count == 5, tilt[0] == 0
def test_corner_write_all_loops():        # select face 0 → bm_write c=1.0 → every loop of face 0 == 1.0, face 1 loops == 0
def test_vgroup_write_adds_vertex():      # vert 3 not in marks; bm_write VGROUP row 0.7 → weight(3) == 0.7
def test_write_skips_meshes_without_attr(): # two objects in multi-edit, only one has tilt → the other still has no attr
def test_snapshot_in_edit_mode_reads_edit_state(): # in edit mode set tilt[0] via bmesh to 99 (no update_edit_mesh) → snapshot values[0] == 99, positions.shape == (6,3)
def test_mesh_write_all_object_mode():    # object mode mesh_write_all(me, "tilt", 5.0) → all 5.0; also FLOAT_VECTOR attribute (1,2,3)
```

- [ ] **Step 2: Run the headless test to verify it fails**

Run (PowerShell, scratch dirs per the headless-blender-env note):
`& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --factory-startup --python-exit-code 1 --python tests/blender/test_attribute_editor.py`
Expected: exit code 1, `ImportError` on `InteractionOps.operators.mesh_attribute_editor`

- [ ] **Step 3: Implement the backend in `operators/mesh_attribute_editor.py`**

Layer accessor by type: `getattr(bm_seq(bm, domain).layers, TYPES[t].bm_layer)` (CORNER → `bm.loops.layers`). `.hide_*` arrays come from `me.attributes.get(".hide_vert"/".hide_edge"/".hide_poly")` in `snapshot`, missing → all visible.

- [ ] **Step 4: Run the headless test to verify it passes**

Same command. Expected: exit code 0, prints `OK 7 tests`.

- [ ] **Step 5: Commit**

```bash
git add operators/mesh_attribute_editor.py tests/blender/test_attribute_editor.py
git commit -m "feat(attr-editor): bmesh and mesh attribute backends"
```

---

### Task 4: Operators — set value, fill, new / remove / duplicate / convert

**Files:**
- Modify: `operators/mesh_attribute_editor.py`
- Modify: `__init__.py` (import block near line 395, `classes` tuple near line 725)
- Modify: `tests/smoke_register.py`
- Test: `tests/blender/test_attribute_editor.py`

**Interfaces:**
- Consumes: Task 3 backend; Task 1 `Row`, `unique_name`, `default_value`.
- Produces operators (all `bl_options = {"REGISTER", "UNDO"}`; `row_name: StringProperty`, `row_kind: EnumProperty(ATTR/VGROUP)` identify the target; a helper `resolve_row(context, name, kind) -> Row | None` rebuilds it from `obj.data.attributes` / `obj.vertex_groups`):
  - `IOPS_OT_AttrSetValue` `iops.attr_set_value` — props `value_float, value_int, value_bool, value_vector (size 3), value_color (size 4), value_string`; picks the one for the row's widget; Edit Mode: `bm_write` on `bm_selected_indices` for every edit mesh that has the row; Object Mode: `mesh_write_all`. Reports `{"CANCELLED"}` with `self.report({"WARNING"}, …)` when nothing is selected in Edit Mode.
  - `IOPS_OT_AttrFill` `iops.attr_fill` — same value props + `reset: BoolProperty` + `target: EnumProperty(SELECTED, UNSELECTED, ALL)`; `invoke` opens `wm.invoke_props_dialog`.
  - `IOPS_OT_AttrNew` `iops.attr_new` — props `name` (default `Attribute`), `data_type` (enum of the spec's 14 types, default FLOAT), `domain` (POINT/EDGE/FACE/CORNER), `value_float` default; dialog; creates through `me.attributes.new(unique_name(name, existing), data_type, domain)` (works in Edit Mode: `attributes.new` is allowed there) and fills the default in Object Mode only; makes the new row active (`_tag_mirror_dirty()`, `_set_active_row(context, name)` hooks like `mesh_selection_sets._set_active_mirror_row`).
  - `IOPS_OT_AttrRemove` `iops.attr_remove` — `me.attributes.remove` / `obj.vertex_groups.remove`.
  - `IOPS_OT_AttrDuplicate` `iops.attr_duplicate` — new attribute `unique_name(f"{name}.copy")`, same type/domain, copied data (Edit Mode via `layers.new` + `copy_from` as in `mesh_selection_sets.bm_rename_set`; Object Mode via `foreach_get/set`).
  - `IOPS_OT_AttrConvert` `iops.attr_convert` — props `data_type`, `domain`; sets `me.attributes.active` to the row and calls `bpy.ops.geometry.attribute_convert(mode="GENERIC", domain=…, data_type=…)`; Object Mode only (`poll`).
  - `IOPS_OT_AttrRefresh` `iops.attr_refresh` — calls `_rebuild_mirror_now(context)` hook.
  - Hooks wired by the UI module (no-ops until then): `_tag_mirror_dirty()`, `_rebuild_mirror_now(context)`, `_set_active_row(context, name)`, `_invalidate_cache()`.

- [ ] **Step 1: Write the failing headless tests**

```python
def test_set_value_edit_mode_and_undo():  # select verts 1,2; bpy.ops.iops.attr_set_value(row_name="tilt", row_kind="ATTR", value_float=45.0); exit edit → [0,45,45,30,40,50]; bpy.ops.ed.undo() → [0,10,20,30,40,50]
def test_set_value_object_mode_sets_all(): # object mode → every vertex 45
def test_fill_unselected_reset():        # select vert 0; attr_fill(target="UNSELECTED", reset=True) → tilt == [0,0,0,0,0,0] except index 0 keeps 0 (use scale=[1..6] instead: scale == [1,0,0,0,0,0])
def test_new_duplicate_remove():          # attr_new(name="tilt", data_type="FLOAT", domain="POINT") → "tilt.001" exists; attr_duplicate(row_name="tilt") → "tilt.copy" with equal data; attr_remove(row_name="tilt.copy") → gone
def test_convert_object_mode():           # attr_convert(row_name="tilt", data_type="INT", domain="POINT") → data_type == "INT"
```

And in `tests/smoke_register.py` add `"attr_set_value", "attr_fill", "attr_new", "attr_remove", "attr_duplicate", "attr_convert", "attr_refresh"` to the operator loop.

- [ ] **Step 2: Run both to verify they fail**

Headless test: exit 1 (`AttributeError: ... iops.attr_set_value`). Smoke test: `assert` on `missing operator: iops.attr_set_value`.

- [ ] **Step 3: Implement the operators and register them in `__init__.py`**

Import block after `from .operators.mesh_nonplanar_overlay import …`; classes appended after `IOPS_OT_SSDeleteAll` in the `classes` tuple.

- [ ] **Step 4: Run both to verify they pass**

Expected: headless `OK 12 tests`; smoke test exits 0.

- [ ] **Step 5: Commit**

```bash
git add operators/mesh_attribute_editor.py __init__.py tests/smoke_register.py tests/blender/test_attribute_editor.py
git commit -m "feat(attr-editor): set value, fill, new/remove/duplicate/convert operators"
```

---

### Task 5: UI — mirror, value fields, UIList, panel, handlers

**Files:**
- Create: `ui/iops_attribute_panel.py`
- Modify: `__init__.py` (import block near line 382, `classes` near line 725, `register()` after `register_selection_sets_ui()`, `unregister()` next to `unregister_selection_sets_ui()`)
- Modify: `tests/smoke_register.py`
- Test: `tests/blender/test_attribute_editor.py`

**Interfaces:**
- Consumes: Task 1 `list_rows`, `editor_rows`, `format_value`, `mixed_count`; Task 3 `snapshot`, `edit_meshes`, `bm_active_index`, `bm_read`, `vgroup_index`; Task 4 hooks.
- Produces:
  - `IOPS_AttrMirrorItem(PropertyGroup)`: `name, data_type, domain, kind: StringProperty`, `editable: BoolProperty`, `count: IntProperty`; `name` has an `update` that renames the attribute / vertex group write-through (guarded by a `_syncing` flag like the selection-sets mirror).
  - `IOPS_AttrState(PropertyGroup)`: `mirror: CollectionProperty(IOPS_AttrMirrorItem)`, `index: IntProperty(update=_index_update)` (syncs `me.attributes.active_index` / `obj.vertex_groups.active_index`), `show_hidden, show_builtin, show_vgroups: BoolProperty(update → tag_mirror_dirty)`, value fields `value_float: FloatProperty(get, set, precision=3)`, `value_int`, `value_bool`, `value_vector (size 3)`, `value_color (size 4, subtype COLOR)`, `value_string` — getters return `_CACHE["value"]` coerced to the field; setters call `apply_value(context, row, value)` (direct `bm_write` on `bm_selected_indices` for every edit mesh carrying the row, `finish_edit`, or `mesh_write_all` in Object Mode; updates `_CACHE["value"]` and `mixed = 1`) and then `_schedule_undo_push()` — a `bpy.app.timers.register(fn, first_interval=0.3)` one-shot that is re-armed on every tick and runs `bpy.ops.ed.undo_push(message="iOps Attribute Value")` once; `preview_mode: EnumProperty(LABELS, GREYSCALE, COLOUR, HEATMAP)`, `preview_decimals: IntProperty(default 2, 0..6)`, `preview_text_size: EnumProperty(small, normal, large)`.
  - `WindowManager.iops_attr = PointerProperty(type=IOPS_AttrState)` created in `register_attribute_ui()`; removed in `unregister_attribute_ui()`.
  - Module state `_CACHE = {"sig": None, "row": None, "value": None, "mixed": 0, "first": False, "selected_count": 0}`, `_LAST_DRAW = 0.0`, `tag_mirror_dirty()`, `rebuild_mirror(context, force=False)`, `refresh_cache(context)`, `active_row(context) -> Row | None`.
  - `rebuild_mirror` signature: `(obj.name, context.mode, tuple((a.name, a.data_type, a.domain) for a in me.attributes), tuple(vg.name for vg in obj.vertex_groups), filters)`; keeps the active row by name, clamps `index`.
  - `refresh_cache`: gated by `time.monotonic() - _LAST_DRAW < 1.0 or preview_on()`; selection signature from `snapshot(...)[2]` (`selected` array) hash + element count; on change reads the active index through `bm_active_index` (once, and only when `len(context.window.modal_operators) == 0`, otherwise `first = True` and the first selected index) and the value through `snapshot` values; `mixed = mixed_count(values[selected])`. Active object only; `snapshot` is never called for the other edit objects.
  - `IOPS_UL_Attributes(UIList)`: row = name (`prop(item, "name", emboss=False)`), domain icon (`VERTEXSEL / EDGESEL / FACESEL / FACE_CORNER` — use `"SNAP_FACE_CENTER"` if `FACE_CORNER` is not an icon id), type tag label, `count` in Object Mode, eye operator `iops.attr_preview` (Task 7; until then the button is omitted). Not-editable rows draw with `row.enabled = False` and tooltip text through the operator description "Edit in Object Mode (bmesh has no layer for this type)".
  - `IOPS_PT_attributes_panel(Panel)`: `bl_space_type VIEW_3D`, `bl_region_type UI`, `bl_category "iOps"`, `bl_label "iOps Attributes"`, `poll`: active object is a mesh and mode in `{OBJECT, EDIT_MESH}`. `draw()` stamps `_LAST_DRAW`, draws filters row, `template_list` (rows=5) + side column (`attr_new`, `attr_remove`, `attr_duplicate`, separator, `attr_refresh`, `IOPS_MT_attr_specials` menu), then the value editor: one row per `editor_rows(...)` entry — label `name` (+ domain icon when it differs from the select mode, `(first)` suffix when `_CACHE["first"]`), the widget for its type, `Mixed (n)` label when `mixed > 1`; fields disabled when nothing is selected or the row is not editable. Object Mode: one widget for the active row + `attr_set_value` button labelled `Set All`. Preview block (Task 7) is a collapsed sub-panel `IOPS_PT_attributes_preview` (`bl_parent_id`, `bl_options = {"DEFAULT_CLOSED"}`).
  - `IOPS_MT_attr_specials(Menu)`: `attr_fill` (Set on selection), `attr_fill` with `reset=True` (Reset on selection), `attr_convert`; Task 6 appends the rest.
  - Handlers list `_HANDLERS` identical in shape to the selection-sets module: `depsgraph_update_post → _resync`, `undo_post / redo_post / load_post → _force_resync`.
  - `register_attribute_ui()` / `unregister_attribute_ui()` wire the Task 4 hooks (`mae._tag_mirror_dirty = tag_mirror_dirty`, `mae._rebuild_mirror_now = …`, `mae._set_active_row = …`, `mae._invalidate_cache = …`).

- [ ] **Step 1: Write the failing tests**

Smoke test additions: `assert hasattr(bpy.types, "IOPS_PT_attributes_panel")`, `hasattr(bpy.types, "IOPS_UL_Attributes")`, `hasattr(wm, "iops_attr")`.

Headless (`tests/blender/test_attribute_editor.py`), driving the module functions directly (no UI event loop in background mode):

```python
def test_mirror_lists_rows_and_syncs_active():   # rebuild_mirror(ctx, force=True) → names == ["scale","tilt","marks"]; set wm.iops_attr.index to the "scale" row → me.attributes.active.name == "scale"
def test_mirror_clamps_after_remove():           # index = last row; me.attributes.remove(tilt); rebuild_mirror(force=True) → 0 <= index < len(mirror)
def test_cache_reads_active_vertex_and_mixed():  # edit mode, select verts 1,2 with active 2; _LAST_DRAW = time.monotonic(); refresh_cache(ctx) → value == 20.0, mixed == 2, first is False
def test_value_setter_writes_selection():        # wm.iops_attr.value_float = 45.0 → tilt[1] == tilt[2] == 45.0, tilt[0] == 0; cache value == 45.0 and mixed == 1
def test_setter_pushes_one_undo_step():          # three setter ticks 44, 45, 46 then run the scheduled timer fn directly → one bpy.ops.ed.undo() restores [0,10,20,...]
def test_cache_skips_bmesh_during_modal():       # monkeypatch module-level `_modal_running(context)` to return True → refresh_cache marks first=True and value == first selected (10.0)
def test_rename_through_mirror():                # mirror item name "tilt" → "lean" → me.attributes.get("lean") is not None
```

- [ ] **Step 2: Run both to verify they fail**

Expected: smoke `AssertionError` on the panel; headless `ImportError` on `InteractionOps.ui.iops_attribute_panel`.

- [ ] **Step 3: Implement `ui/iops_attribute_panel.py` and register**

`__init__.py`: import `IOPS_AttrMirrorItem, IOPS_AttrState, IOPS_UL_Attributes, IOPS_PT_attributes_panel, IOPS_MT_attr_specials, register_attribute_ui, unregister_attribute_ui`; `IOPS_AttrMirrorItem` before `IOPS_AttrState` before the UI classes in `classes` (CollectionProperty / PointerProperty targets register first, as the `IOPS_SS_*` comments say).

- [ ] **Step 4: Run both to verify they pass**

Expected: smoke exits 0; headless `OK 17 tests`.

- [ ] **Step 5: Verify in the live Blender (optional when the user's file is open: read-only reload is NOT allowed mid-edit — skip unless the scene is pristine)**

If the live scene is safe: full `addon_disable` / clear `sys.modules` `InteractionOps*` / `addon_enable` cycle over MCP, then `hasattr(bpy.types, "IOPS_PT_attributes_panel")`.

- [ ] **Step 6: Commit**

```bash
git add ui/iops_attribute_panel.py __init__.py tests/smoke_register.py tests/blender/test_attribute_editor.py
git commit -m "feat(attr-editor): sidebar panel with mirror list and live value editor"
```

---

### Task 6: Tools — gradient, math, smooth, randomize, copy/swap, vertex group ⇄ attribute, select by value

**Files:**
- Modify: `operators/mesh_attribute_editor.py`
- Modify: `ui/iops_attribute_panel.py` (`IOPS_MT_attr_specials`)
- Modify: `__init__.py`, `tests/smoke_register.py`
- Test: `tests/blender/test_attribute_editor.py`

**Interfaces:**
- Consumes: Task 2 `order_chain, gradient, math_op, smooth, randomize, coerce, select_predicate`; Task 3 `bm_values, bm_write_values, bm_selected_indices, edit_meshes, mesh_read_all, mesh_write_all, vgroup_index`.
- Produces operators (`REGISTER | UNDO`, `row_name` / `row_kind` props, dialogs via `invoke_props_dialog`, Edit Mode applies to the domain selection, Object Mode to all elements unless noted):
  - `IOPS_OT_AttrGradient` `iops.attr_gradient` — `mode: Enum(LINEAR, EASE_IN_OUT)`, `use_typed: Bool`, `value_start, value_end: Float`; POINT and EDGE rows, Edit Mode only; chain = selected verts + selected edges between them via `order_chain`; `None` → `report WARNING "Select a single chain of vertices"`, `CANCELLED`. Ends = chain-end values unless `use_typed`. EDGE rows write the chain's edges in order (`n = len(chain) - 1`, or `len(chain)` for a loop). Vectors per component; INT rounded.
  - Type gating, shared by every tool through `tool_supports(tool, row) -> str | None` (the reason text, `None` when supported) per the spec's type matrix; the menu draws unsupported entries disabled with that text as the operator description.
  - `IOPS_OT_AttrMath` `iops.attr_math` — `op: Enum(ADD, MULTIPLY, CLAMP, INVERT, REMAP, ROUND)`, `a: Float(default 1)`, `b: Float(default 1)`.
  - `IOPS_OT_AttrSmooth` `iops.attr_smooth` — `iterations: Int(1..100, default 1)`, `factor: Float(0..1, default 0.5)`; Edit Mode only; neighbours from bmesh (`v.link_edges` → other vert, `e` → edges sharing a vert, `f` → faces sharing an edge), restricted to the selected index set.
  - `IOPS_OT_AttrRandomize` `iops.attr_randomize` — `lo, hi: Float`, `seed: Int`.
  - `IOPS_OT_AttrCopy` `iops.attr_copy` — `target_name: String`, `component: Int(0..3)`, `swap: Bool`; both rows must share a domain; coerces with `coerce`; `None` result → `report ERROR "Cannot convert <src> to <dst>"`.
  - `IOPS_OT_AttrFromVGroup` `iops.attr_from_vgroup` — `group_name: String`, `target_name: String(default = group name)`; creates FLOAT POINT target if missing, copies weights (0 for non-members).
  - `IOPS_OT_AttrToVGroup` `iops.attr_to_vgroup` — `group_name: String(default = row name)`; creates the group if missing, weights clamped 0..1.
  - `IOPS_OT_AttrSelectByValue` `iops.attr_select_by_value` — `op: Enum(EQUAL, NOT_EQUAL, LESS, GREATER, RANGE, ACTIVE)`, `value: Float`, `hi: Float`, `tol: Float(default 1e-4)`, `extend: Bool`; Edit Mode only; `ACTIVE` compares against the active element's value (`bm_active_index` + `bm_read`); selects elements of the row's domain (`select = True`, then `bm.select_flush_mode()`), skipping hidden.
- `IOPS_MT_attr_specials` gains, after a separator: Gradient, Math, Smooth, Randomize, Copy / Swap, From Vertex Group, To Vertex Group, Select by Value.

- [ ] **Step 1: Write the failing headless tests**

```python
def test_gradient_along_chain():          # select all 6 verts + 5 edges; attr_gradient(use_typed=True, value_start=0, value_end=100) → tilt == [0,20,40,60,80,100]
def test_gradient_rejects_branch():       # quad mesh, select all → CANCELLED
def test_math_remap_on_selection():       # select verts 0..2 (tilt 0,10,20); attr_math(op="REMAP", a=0, b=1) → [0,0.5,1,30,40,50]
def test_smooth_path():                   # tilt = [0,10,0,10,0,10] select all; attr_smooth(iterations=1, factor=1.0) → tilt[1] == 0.0 (mean of 0,0), tilt[0] == 10.0
def test_randomize_seeded():              # attr_randomize(lo=0, hi=1, seed=3) twice with undo between → identical arrays
def test_copy_swap_and_coerce():          # attr_copy(row_name="tilt", target_name="scale", swap=True) → arrays exchanged; INT attr "id" copy from tilt → ints
def test_vgroup_roundtrip():              # attr_from_vgroup("marks") → "marks" FLOAT attr with weights; attr_to_vgroup(row_name="tilt", group_name="w") → weights clamped to 1.0
def test_select_by_value():               # deselect all; attr_select_by_value(row_name="tilt", op="GREATER", value=25) → selected verts == {3,4,5}; op="ACTIVE" with active vert 1 → {1}
def test_gradient_edge_domain_and_int_rounding(): # EDGE FLOAT attr "ew" on the path: gradient 0..1 over 5 edges → [0,0.25,0.5,0.75,1]; INT attr gradient 0..10 over 6 verts → [0,2,4,6,8,10]
def test_tool_supports_matrix():          # tool_supports("SMOOTH", bool_row) is a str; tool_supports("MATH", vector_row) is None; tool_supports("GRADIENT", face_row) is a str
```

Smoke additions: `attr_gradient, attr_math, attr_smooth, attr_randomize, attr_copy, attr_from_vgroup, attr_to_vgroup, attr_select_by_value`.

- [ ] **Step 2: Run both to verify they fail** — missing operators.

- [ ] **Step 3: Implement the operators, register, extend the menu**

- [ ] **Step 4: Run both to verify they pass** — headless `OK 25 tests`, smoke exit 0.

- [ ] **Step 5: Commit**

```bash
git add operators/mesh_attribute_editor.py ui/iops_attribute_panel.py __init__.py tests/smoke_register.py tests/blender/test_attribute_editor.py
git commit -m "feat(attr-editor): gradient, math, smooth, randomize, copy, vgroup and select-by-value tools"
```

---

### Task 7: Viewport preview — labels, greyscale / colour / heatmap, legend

**Files:**
- Modify: `ui/iops_attribute_panel.py`
- Modify: `prefs/addon_preferences.py` (new pref next to `nonplanar_angle` ~line 868 and its draw ~line 1305), `prefs/iops_prefs.py` (JSON round-trip next to `nonplanar_angle` ~line 308)
- Modify: `__init__.py` (`unregister()` calls `disable_preview()` the way it calls `mesh_nonplanar_overlay.disable_overlay`)
- Test: `tests/blender/test_attribute_editor.py` (data-side only: no GPU in background mode)

**Interfaces:**
- Consumes: Task 3 `snapshot`; Task 2 `heat_color, luminance, scalar_for_preview, format_value`; `ui.draw` (`Role, draw_scope, get_theme, safe_handler_add, safe_handler_remove`), `ui.hud.text.draw / measure`, `operators/mesh_nonplanar_overlay._get_shader` pattern (copy the depth-shrink shader into a private `_get_fill_shader()` with its own interface name `iops_attr_iface`).
- Produces:
  - Pref `attr_preview_max_labels: IntProperty(default=2000, min=100, max=100000)` under the same prefs group as `nonplanar_angle`.
  - Module state `_PREVIEW = {"row": None, "handle_view": None, "handle_pixel": None, "geom": None, "dirty": True, "range": (0.0, 1.0), "too_many": False}`.
  - `preview_on() -> bool`, `preview_row_name() -> str | None`.
  - `preview_collect(context)` — handler-side: `snapshot(obj, row.name, row.domain)` → positions, values, selected, hidden; drops hidden; scalar array via `scalar_for_preview`; `range = (min, max)`; per-element colours for the active mode (`HEATMAP` → `heat_color((v-min)/(max-min))`, constant range → `heat_color(0.5)`; `GREYSCALE` → luminance grey; `COLOUR` → rgb as stored; alpha 0.6 for fills, 1.0 for points); `too_many = len > prefs.attr_preview_max_labels`; stores float32 arrays; sets `dirty`.
  - `_draw_view()` (POST_VIEW): rebuilds the batch when dirty; POINT → `POINTS` (size 8), EDGE → `LINES` (width 2), FACE / CORNER → `TRIS` from `me.loop_triangles` + per-loop colour (CORNER) or per-face colour (FACE); uses `draw_scope(blend="ALPHA", depth="LESS_EQUAL")`; skipped when `space_data.overlay.show_overlays` is False.
  - `_draw_pixel()` (POST_PIXEL): labels via `hud.text.draw(text, x, y, theme=theme, role=Role.ACTIVE_POINT if selected else Role.HUD_LABEL, size_token=state.preview_text_size)` at `view3d_utils.location_3d_to_region_2d(region, rv3d, pos)` (+4 px, +4 px), only in `LABELS` mode and when not `too_many`; clip-plane check through `rv3d.use_clip_planes` + `rv3d.clip_planes` dot test; in HEATMAP mode draws a legend `f"{row.name}: {format_value(min)} … {format_value(max)}"` at the top-left of the region under the stats overlay (x = 20 + tools region width, y = region.height − 60).
  - `IOPS_OT_AttrPreview` `iops.attr_preview` — `row_name, row_kind`; toggles: same row → `disable_preview()`; other row → switch; first enable adds both handlers with `safe_handler_add(SpaceView3D, cb, (), "WINDOW", "POST_VIEW" / "POST_PIXEL")`; tags all VIEW_3D areas for redraw.
  - `disable_preview()` — removes handlers, resets `_PREVIEW`.
  - Handlers `_resync` / `_force_resync` call `preview_collect` when `preview_on()`; `preview_collect` disables the preview when the active object is not a mesh, the row vanished, or the mode left `{OBJECT, EDIT_MESH}`.
  - UIList eye icon: `HIDE_OFF` when `preview_row_name() == item.name` else `HIDE_ON`, `emboss=False`.
  - Sub-panel `IOPS_PT_attributes_preview` (`bl_parent_id = "IOPS_PT_attributes_panel"`, `DEFAULT_CLOSED`): `preview_mode` (greyscale / colour items disabled for non-colour rows via `row.enabled`), `preview_decimals`, `preview_text_size`, `too many elements (N > max labels)` label when `too_many`, and `prefs.attr_preview_max_labels`.

- [ ] **Step 1: Write the failing headless tests** (collection only; drawing needs a GPU)

```python
def test_preview_collect_values_and_range():  # preview row tilt, mode HEATMAP; preview_collect(ctx) → geom scalar == [0..50], range == (0.0, 50.0), len(colors) == 6, colors[0][:3] == (0,0,1), colors[-1][:3] == (1,0,0)
def test_labels_skip_hidden():                # hide vert 0 (edit mode) → geom has 5 positions
def test_preview_disables_on_non_mesh():      # enable on tilt; make an Empty active; preview_collect(ctx) → preview_on() is False
def test_preview_too_many_flag():             # prefs.attr_preview_max_labels = 100; mesh with 200 verts → too_many True
```

Smoke: `attr_preview` operator, `prefs.attr_preview_max_labels`.

- [ ] **Step 2: Run both to verify they fail**

- [ ] **Step 3: Implement the preview, the pref, the sub-panel and the eye button**

- [ ] **Step 4: Run both to verify they pass** — headless `OK 29 tests`, smoke exit 0.

- [ ] **Step 5: Verify drawing in the live Blender** only when the scene is pristine or the user confirms (the open file is their race track): reload the addon with the full disable/enable cycle, enable the preview on `tilt`, screenshot through `bpy.ops.screen.screenshot` to the scratchpad, inspect the image.

- [ ] **Step 6: Commit**

```bash
git add ui/iops_attribute_panel.py prefs/addon_preferences.py prefs/iops_prefs.py __init__.py tests/smoke_register.py tests/blender/test_attribute_editor.py
git commit -m "feat(attr-editor): viewport preview with labels, greyscale/colour and heatmap"
```

---

### Task 8: Docs, status, lint, squash

**Files:**
- Create: `docs/ui/ui_attributes.md`
- Modify: `mkdocs.yml` (UI nav, after `HUD: ui/ui_hud.md`), `docs/ui.md` (bullet list), `docs/superpowers/STATUS.md` (spec + plan rows)

- [ ] **Step 1: Write `docs/ui/ui_attributes.md`** in the voice of `docs/operators/op_selection_sets.md`: one intro paragraph, where the panel lives, a `Button | What it does` table covering list, filters, side column, value editor, `Mixed`, Object Mode `Set All`, the specials-menu tools, the preview sub-panel; a Tips list (Object-Mode-only types, the label cap pref, select mode drives which fields show).

- [ ] **Step 2: Add the nav entry and the overview bullet; add STATUS.md rows** (`✅` once Tasks 1–7 are committed, evidence = the files).

- [ ] **Step 3: Lint and full test run**

Run: `ruff check utils/attribute_editor_core.py operators/mesh_attribute_editor.py ui/iops_attribute_panel.py tests/test_attribute_editor_core.py tests/blender/test_attribute_editor.py` → no findings; `python -m pytest tests/ -q` → all passed; headless test + smoke test exit 0.

- [ ] **Step 4: Commit, then squash the task commits into one** (repo rule: one commit per feature on origin; use the `squash-feature-commits` skill) with message `feat(attr-editor): iOps Attributes sidebar panel — edit, preview and manage mesh attributes`.
