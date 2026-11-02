# Cursor Bisect Delimiter and Cursor-Plane Axis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Cursor Bisect confine a cut to the mesh piece under the mouse (delimiter: island / seam / sharp / UV island / material / normal angle) and add the cursor's Z as a third cut-normal axis so the cut runs in the plane of the hovered face.

**Architecture:** A bpy-free graph walk (`utils/cursor_bisect_core.py`, pytest) decides which faces belong to the island; the operator builds the boundary predicate from the BMesh and stamps the resulting face set on an int layer (`cursor_bisect_cut`) so it survives the one-or-many `bisect_plane` passes of single, bevel and fill cuts. The Z axis is a third value of the existing `normal_axis` state, threaded through one `_axis_vector()` helper that replaces five inline copies.

**Tech Stack:** Blender 5.2 Python (bpy, bmesh, mathutils), pytest for the core module, headless `blender --background` scripts under `tests/blender/` for BMesh-bound code.

**Spec:** `docs/superpowers/specs/2026-10-26-cursor-bisect-delimiter-and-plane-axis-design.md`

## Global Constraints

- Keys: `L` delimiter on/off, `Shift+L` cycle type, `X` cycles normal axis `X → Y → Z`.
- Delimiter types, in cycle order: `ISLAND, SEAM, SHARP, UV, MATERIAL, NORMAL`; labels `Mesh Island, Seam, Sharp, UV Island, Material, Normal`. Default `ISLAND`, delimiter off by default.
- The delimiter is a filter: it never adds faces beyond the candidate set (selected visible faces if any are selected, else all visible faces). The island walk is uncapped.
- Face under the mouse = the hover-tracked face; no click-time raycast, no corner fallback. A ray miss invalidates the hover for the delimiter.
- With the delimiter on, only the hit object is cut; others are left alone.
- In Z mode Inset (V), Bevel (B) and Fill Cut (F) are off and their keys report `Not available with Z axis`.
- New preference `cursor_bisect_delimit_angle`: degrees, default 30.0, min 0.0, max 180.0.
- New scene props `cursor_bisect_delimit` (bool, False) and `cursor_bisect_delimit_type` (enum of the six types, default `ISLAND`); `cursor_bisect_normal_axis` gains `Z`.
- Headless runs set every `BLENDER_USER_*` variable to a scratch directory (see `tests/blender/test_picking_snap.py` docstring and the repo memory note); Blender is `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe`.
- Files keep their current line endings (`utils/picking.py` is CRLF; the operator, prefs and tests are LF).
- One squashed commit per feature before pushing; commit per task during work is fine.

## Review Focus

1. **Hover face index stale after a cut.** After LMB the bmesh face count changes; the tracked `hit_face_index` may now point at a different face until the next mouse move. The next cut without a mouse move must not walk from a wrong face: the cache key includes `_mesh_version`, and `delimited_faces` returns an empty set for an out-of-range index. Test: `test_delimited_faces_out_of_range_is_empty` in Task 2.
2. **Non-manifold edge (3+ faces).** The walk must still reach all link faces across a Mesh Island edge and apply pairwise boundary rules. Test: `test_walk_non_manifold_edge_reaches_all_faces` in Task 1.
3. **UV type on a mesh without a UV layer.** Must behave like Mesh Island, not raise. Test: `test_uv_without_layer_is_island` in Task 2.
4. **Z axis with Fill Cut remembered ON from a previous run.** `_load_scene_props` restores `fill_cut_mode=True` while `normal_axis='Z'`; the operator must force the three features off on invoke when the axis is Z. Covered by the explicit step in Task 6 (`_enforce_z_restrictions` called from invoke after `_load_scene_props`).
5. **Hidden hit face.** Hovering a hidden-but-raycast-hit face must yield no cut and the `no face under the cursor` report rather than cutting through a hidden face. Test: `test_delimited_faces_hidden_start_is_empty` in Task 2.

---

### Task 1: Core island walk (bpy-free)

**Files:**
- Create: `utils/cursor_bisect_core.py`
- Test: `tests/test_cursor_bisect_core.py`

**Interfaces:**
- Produces:
  - `DELIMIT_TYPES: tuple[str, ...] = ('ISLAND', 'SEAM', 'SHARP', 'UV', 'MATERIAL', 'NORMAL')`
  - `DELIMIT_LABELS: dict[str, str]` mapping each type to its label from Global Constraints.
  - `next_delimit_type(current: str) -> str` cycles through `DELIMIT_TYPES` in order, wrapping.
  - `walk_island(start, in_candidates, neighbors, is_boundary) -> set`
    - `start`: hashable face id.
    - `in_candidates(face) -> bool`.
    - `neighbors(face) -> Iterable[tuple[edge, other_face]]`.
    - `is_boundary(edge, face_a, face_b) -> bool`.
    - Returns the set of faces reachable from `start` through edges where `is_boundary` is False, visiting only faces for which `in_candidates` is True. Returns an empty set when `start` fails `in_candidates`. BFS with plain sets, no recursion.
  - `normals_split(n_a, n_b, angle_deg: float) -> bool`: True when the angle between the two unit vectors (3-tuples) exceeds `angle_deg`. Clamps the dot product to [-1, 1] before `acos`.
  - `AXES: tuple[str, ...] = ('X', 'Y', 'Z')`, `next_axis(axis: str) -> str` cycles `X → Y → Z → X`.
  - `axis_vector(axis: str) -> tuple[float, float, float]` returns the unit vector of that cursor axis.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cursor_bisect_core.py
from utils.cursor_bisect_core import (
    DELIMIT_TYPES, DELIMIT_LABELS, next_delimit_type, walk_island,
    normals_split, next_axis, axis_vector,
)

# Faces 0-1-2-3 in a strip, edges e01, e12, e23 between neighbours;
# face 4 is disconnected.
STRIP = {0: [("e01", 1)], 1: [("e01", 0), ("e12", 2)],
         2: [("e12", 1), ("e23", 3)], 3: [("e23", 2)], 4: []}

def _nb(graph):
    return lambda f: graph.get(f, [])

def test_walk_whole_strip_without_boundaries():
    assert walk_island(0, lambda f: True, _nb(STRIP), lambda e, a, b: False) == {0, 1, 2, 3}

def test_walk_stops_at_boundary_edge():
    assert walk_island(0, lambda f: True, _nb(STRIP), lambda e, a, b: e == "e12") == {0, 1}

def test_walk_stays_inside_candidates():
    assert walk_island(1, lambda f: f in {1, 2}, _nb(STRIP), lambda e, a, b: False) == {1, 2}

def test_walk_start_outside_candidates_is_empty():
    assert walk_island(0, lambda f: f != 0, _nb(STRIP), lambda e, a, b: False) == set()

def test_walk_non_manifold_edge_reaches_all_faces():
    fan = {0: [("e", 1), ("e", 2)], 1: [("e", 0), ("e", 2)], 2: [("e", 0), ("e", 1)]}
    assert walk_island(0, lambda f: True, _nb(fan), lambda e, a, b: False) == {0, 1, 2}

def test_walk_pairwise_boundary_on_non_manifold_edge():
    fan = {0: [("e", 1), ("e", 2)], 1: [("e", 0), ("e", 2)], 2: [("e", 0), ("e", 1)]}
    blocked = lambda e, a, b: {a, b} == {0, 2}
    assert walk_island(0, lambda f: True, _nb(fan), blocked) == {0, 1, 2}  # 2 reached via 1

def test_delimit_cycle_order_and_labels():
    assert DELIMIT_TYPES == ('ISLAND', 'SEAM', 'SHARP', 'UV', 'MATERIAL', 'NORMAL')
    assert next_delimit_type('NORMAL') == 'ISLAND'
    assert next_delimit_type('ISLAND') == 'SEAM'
    assert DELIMIT_LABELS['UV'] == 'UV Island'
    assert DELIMIT_LABELS['ISLAND'] == 'Mesh Island'

def test_normals_split():
    assert normals_split((0, 0, 1), (1, 0, 0), 30.0) is True
    assert normals_split((0, 0, 1), (0, 0, 1), 30.0) is False
    assert normals_split((0, 0, 1), (0, 0, 1.0000001), 0.0) is False  # dot clamp, no NaN

def test_axis_cycle_and_vectors():
    assert next_axis('X') == 'Y' and next_axis('Y') == 'Z' and next_axis('Z') == 'X'
    assert axis_vector('Z') == (0.0, 0.0, 1.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_cursor_bisect_core.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'utils.cursor_bisect_core'`

- [ ] **Step 3: Implement `utils/cursor_bisect_core.py`** with the interfaces above. Module docstring: pure logic for Cursor Bisect, no bpy. `walk_island` is an iterative BFS using a `deque` and a `visited` set.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_cursor_bisect_core.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add utils/cursor_bisect_core.py tests/test_cursor_bisect_core.py
git commit -m "feat(cursor-bisect): bpy-free island walk and delimiter types"
```

---

### Task 2: BMesh boundary predicate and `delimited_faces`

**Files:**
- Modify: `operators/mesh_cursor_bisect.py` (module level, after the constants block at lines 18-40)
- Test: `tests/blender/test_cursor_bisect_delimit.py` (headless, new)

**Interfaces:**
- Consumes: `walk_island`, `normals_split` from Task 1.
- Produces, module-level in `operators/mesh_cursor_bisect.py`:
  - `delimit_boundary_test(bm, delimit_type: str, angle_deg: float) -> Callable[[BMEdge, BMFace, BMFace], bool]`
    - `ISLAND`: always False.
    - `SEAM`: `edge.seam`. `SHARP`: `not edge.smooth`. `MATERIAL`: `a.material_index != b.material_index`. `NORMAL`: `normals_split(a.normal, b.normal, angle_deg)`.
    - `UV`: uses `bm.loops.layers.uv.active`; if None → always False. Otherwise True when, for either vertex of the edge, the UV of face `a`'s loop at that vertex and face `b`'s loop at that vertex differ by more than `1e-6` in either component (builder's epsilon; keep it a module constant `UV_SPLIT_EPSILON`).
  - `delimited_faces(bm, start_index: int, candidates: set[int], delimit_type: str, angle_deg: float, is_visible=None) -> set[int]`
    - Returns the indices of the faces reachable from `bm.faces[start_index]` via `walk_island`, with `in_candidates = idx in candidates and (is_visible is None or is_visible(face))`.
    - `neighbors(face)` yields `(edge, other)` for every `other in edge.link_faces if other is not face`, over `face.edges`.
    - Returns an empty set when `start_index` is out of range, negative, or the start face is hidden / not in `candidates`.
    - Calls `bm.faces.ensure_lookup_table()` first.

- [ ] **Step 1: Write the failing headless test**

`tests/blender/test_cursor_bisect_delimit.py`, same scaffold as `tests/blender/test_picking_snap.py` (enable addon from the repo, PASS/FAIL per test, exit 1 on failure). Build meshes with `bmesh.new()`:

- `_grid(nx, ny)`: a flat quad grid in XY, returns `bm`; face index `y*nx + x` (create verts row-major, faces in that order, then `bm.faces.ensure_lookup_table()`).
- `_two_islands()`: two separate quads in one bmesh (indices 0 and 1).

```python
from InteractionOps.operators.mesh_cursor_bisect import delimited_faces, delimit_boundary_test

def test_island_reaches_connected_only():
    bm = _two_islands()
    assert delimited_faces(bm, 0, {0, 1}, 'ISLAND', 30.0) == {0}

def test_seam_stops_walk():
    bm = _grid(3, 1)                       # faces 0,1,2 in a row
    shared = [e for e in bm.faces[1].edges if bm.faces[2] in e.link_faces][0]
    shared.seam = True
    assert delimited_faces(bm, 0, {0, 1, 2}, 'SEAM', 30.0) == {0, 1}
    assert delimited_faces(bm, 0, {0, 1, 2}, 'ISLAND', 30.0) == {0, 1, 2}

def test_sharp_stops_walk():
    bm = _grid(3, 1)
    shared = [e for e in bm.faces[0].edges if bm.faces[1] in e.link_faces][0]
    shared.smooth = False
    assert delimited_faces(bm, 2, {0, 1, 2}, 'SHARP', 30.0) == {1, 2}

def test_material_stops_walk():
    bm = _grid(3, 1)
    bm.faces[2].material_index = 1
    assert delimited_faces(bm, 0, {0, 1, 2}, 'MATERIAL', 30.0) == {0, 1}

def test_normal_angle_stops_walk():
    # Three quads: two flat, the third folded up 90° about its shared edge.
    bm = _folded_strip(fold_deg=90.0)
    bm.normal_update()
    assert delimited_faces(bm, 0, {0, 1, 2}, 'NORMAL', 30.0) == {0, 1}
    assert delimited_faces(bm, 0, {0, 1, 2}, 'NORMAL', 120.0) == {0, 1, 2}

def test_uv_island_boundary_stops_walk():
    bm = _grid(2, 1)
    uv = bm.loops.layers.uv.new("UVMap")
    for f in bm.faces:
        for l in f.loops:
            l[uv].uv = (l.vert.co.x, l.vert.co.y)
    for l in bm.faces[1].loops:
        l[uv].uv = (l[uv].uv.x + 5.0, l[uv].uv.y)   # face 1 moved to its own UV island
    assert delimited_faces(bm, 0, {0, 1}, 'UV', 30.0) == {0}

def test_uv_without_layer_is_island():
    bm = _grid(2, 1)
    assert delimited_faces(bm, 0, {0, 1}, 'UV', 30.0) == {0, 1}

def test_candidates_filter_walk():
    bm = _grid(3, 1)
    assert delimited_faces(bm, 1, {1, 2}, 'ISLAND', 30.0) == {1, 2}
    assert delimited_faces(bm, 0, {1, 2}, 'ISLAND', 30.0) == set()

def test_delimited_faces_out_of_range_is_empty():
    bm = _grid(2, 1)
    assert delimited_faces(bm, 7, {0, 1}, 'ISLAND', 30.0) == set()
    assert delimited_faces(bm, -1, {0, 1}, 'ISLAND', 30.0) == set()

def test_delimited_faces_hidden_start_is_empty():
    bm = _grid(2, 1)
    bm.faces[0].hide = True
    vis = lambda f: not f.hide
    assert delimited_faces(bm, 0, {0, 1}, 'ISLAND', 30.0, is_visible=vis) == set()
    assert delimited_faces(bm, 1, {0, 1}, 'ISLAND', 30.0, is_visible=vis) == {1}
```

- [ ] **Step 2: Run to verify it fails**

Run (PowerShell, env vars set to scratch as in Global Constraints):
`& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --factory-startup --python-exit-code 1 --python tests/blender/test_cursor_bisect_delimit.py`
Expected: `ImportError: cannot import name 'delimited_faces'`, exit code 1

- [ ] **Step 3: Implement `delimit_boundary_test` and `delimited_faces`** at module level in `operators/mesh_cursor_bisect.py`; import `walk_island, normals_split` from `..utils.cursor_bisect_core`.

- [ ] **Step 4: Run to verify it passes**

Same command. Expected: `10/10 passed`, exit code 0.

- [ ] **Step 5: Commit**

```bash
git add operators/mesh_cursor_bisect.py tests/blender/test_cursor_bisect_delimit.py
git commit -m "feat(cursor-bisect): BMesh delimiter predicate and delimited_faces"
```

---

### Task 3: Properties and preferences

**Files:**
- Modify: `prefs/addon_properties.py:604-624` (scene props block)
- Modify: `prefs/addon_preferences.py:806-812` (after `cursor_bisect_coplanar_angle`) and `prefs/addon_preferences.py:1255-1258` (Operation row)
- Modify: `prefs/iops_prefs.py:296-305` (`CURSOR_BISECT` JSON section)
- Test: `tests/smoke_register.py` (existing)

**Interfaces:**
- Produces:
  - Scene props on `context.scene.IOPS`: `cursor_bisect_delimit: BoolProperty(default=False)`, `cursor_bisect_delimit_type: EnumProperty(items=[(t, DELIMIT_LABELS[t], "") for t in DELIMIT_TYPES], default='ISLAND')`; `cursor_bisect_normal_axis` items become `[('X',"X",""),('Y',"Y",""),('Z',"Z","")]`.
  - Addon pref `cursor_bisect_delimit_angle: FloatProperty(name="Delimit Angle", description="Normal-angle delimiter: faces meeting at more than this angle are on different islands", default=30.0, min=0.0, max=180.0, step=100, precision=1)`.
  - JSON key `"cursor_bisect_delimit_angle": safe("cursor_bisect_delimit_angle", 30.0)` in the `CURSOR_BISECT` section.

- [ ] **Step 1: Add the props, the pref, its row in the Operation line (`row.prop(self, "cursor_bisect_delimit_angle")` after the coplanar angle), and the JSON key.** `addon_properties.py` imports `DELIMIT_TYPES, DELIMIT_LABELS` from `..utils.cursor_bisect_core`.

- [ ] **Step 2: Run the registration smoke test**

Run: `& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --factory-startup --python-exit-code 1 --python tests/smoke_register.py`
Expected: `SMOKE_OK`, exit code 0. (Requires the junction `<scratch>/scripts/addons/InteractionOps → repo`, see the memory note.)

- [ ] **Step 3: Commit**

```bash
git add prefs/addon_properties.py prefs/addon_preferences.py prefs/iops_prefs.py
git commit -m "feat(cursor-bisect): delimiter props, Z axis item, delimit angle pref"
```

---

### Task 4: Operator delimiter state, keys, status, HUD, persistence

**Files:**
- Modify: `operators/mesh_cursor_bisect.py` — class attrs (~line 75-120), `update_status_bar` (328-358), `_sync_hud_state` / `_sync_hud_header` / `_build_hud` (1957-2035), modal key handlers (around the `N` handler at 873-878), `_save_scene_props` / `_load_scene_props` (1101-1130), MOUSEMOVE (674-731).

**Interfaces:**
- Consumes: `DELIMIT_TYPES, DELIMIT_LABELS, next_delimit_type` (Task 1); scene props (Task 3).
- Produces (operator attributes and methods used by Task 5):
  - `self.delimit_active: bool`, `self.delimit_type: str`.
  - `self.hover_valid: bool` — True after a MOUSEMOVE hit, False after a MOUSEMOVE miss. Existing `hit_obj` / `hit_face_index` are left untouched on a miss (hold-snap relies on them).
  - `self._mesh_version: int` — incremented after every cut, after RMB / Shift+RMB selection changes and after `Z` deselect.
  - `self._island_cache: tuple | None` — `(key, frozenset)` where `key = (obj.name, hit_face_index, delimit_type, _mesh_version)`.
  - `_delimit_angle(self, context) -> float` reads `cursor_bisect_delimit_angle` from prefs (fallback 30.0).
  - `_delimited_candidates(self, context, bm, obj, candidates: set[int]) -> set[int] | None`: returns `None` when the delimiter is off; otherwise the cached/recomputed `delimited_faces(bm, self.hit_face_index, candidates, self.delimit_type, angle, is_visible=self.is_face_visible_and_valid)` when `self.hover_valid and self.hit_obj == obj`, else an empty set.

- [ ] **Step 1: Add state and the two key handlers.** Class attrs `delimit_active = False`, `delimit_type = 'ISLAND'`, `hover_valid = False`, `_mesh_version = 0`, `_island_cache = None`. Handlers, placed next to the `N` handler:
  - `L` (no shift/ctrl/alt): toggle `delimit_active`, clear `_island_cache`, `calculate_cut_preview` + `calculate_fill_cut_preview` if fill is on, `update_status_bar`, `_sync_hud_state`, redraw.
  - `Shift+L`: `self.delimit_type = next_delimit_type(self.delimit_type)`, same refresh.

- [ ] **Step 2: Status bar and HUD.** Status text gains `[L] Delimit({state})` where state is `OFF` or `ON:{label}` placed after `[N] Mark Type`. HUD: two `HUDItem`s after "Mark Type": `HUDItem("Delimiter", "L", ...)` and `HUDItem("Delimit Type", "Shift+L", ItemState.OFF, ...)`; `_sync_hud_state` sets `"L"`; `_sync_hud_header` appends `f"Delimit: {DELIMIT_LABELS[self.delimit_type]}"` while the delimiter is on.

- [ ] **Step 3: Persistence.** Save/load `cursor_bisect_delimit` ↔ `delimit_active` and `cursor_bisect_delimit_type` ↔ `delimit_type` in `_save_scene_props` / `_load_scene_props`.

- [ ] **Step 4: Hover validity and versioning.** In MOUSEMOVE set `self.hover_valid = True` in the hit branch; add an `else:` branch that sets `self.hover_valid = False` and, when `delimit_active`, clears `cut_preview_lines` / `fill_cut_preview_lines` and redraws. Increment `_mesh_version` at the end of `execute`, `execute_fill_cut`, the RMB and Shift+RMB handlers, and the `Z` deselect handler.

- [ ] **Step 5: Implement `_delimit_angle` and `_delimited_candidates`** with the cache described in Interfaces.

- [ ] **Step 6: Verify registration and a manual pass**

Run the smoke test (command in Task 3). Expected `SMOKE_OK`.
Manual in the live Blender: start Cursor Bisect, press `L` and `Shift+L`; status bar shows `[L] Delimit(ON:Seam)` etc., HUD header shows `Delimit: Seam`. Exit and restart: state remembered.

- [ ] **Step 7: Commit**

```bash
git add operators/mesh_cursor_bisect.py
git commit -m "feat(cursor-bisect): delimiter toggle, type cycle, HUD and persistence"
```

---

### Task 5: Wire the delimiter into preview and cut

**Files:**
- Modify: `operators/mesh_cursor_bisect.py` — `get_faces_to_process` (1464-1500), `execute` (968-1090), `execute_fill_cut` (1796-1870), `_snapshot_face_selection` neighbourhood (260-300).

**Interfaces:**
- Consumes: `_delimited_candidates` (Task 4).
- Produces:
  - `_cut_face_set(self, context, bm, obj) -> set[int] | None`: candidate set = indices of selected visible faces if any, else all visible faces; returns `_delimited_candidates(...)` if the delimiter is on, else the candidate set. `None` is never returned (delimiter off → candidate set).
  - `_stamp_cut_layer(bm, face_indices) -> layer`: new int layer `cursor_bisect_cut` (removing a stale one first, same pattern as `_snapshot_face_selection`), value 1 for the given indices.
  - `_cut_report(self, context)`: reports `{'INFO'}` `Delimiter: no face under the cursor` when `delimit_active and not hover_valid`, or `Delimiter: face under the cursor is not selected` when the hovered face exists but the cut set came back empty while a selection exists.

- [ ] **Step 1: Preview.** In `get_faces_to_process`, when `self.delimit_active`: return `_cut_face_set(...)` (ignoring `face_depth` and the fallback limit). Otherwise keep the existing behaviour unchanged.

- [ ] **Step 2: Cut.** In `execute`, per object: compute `cut_set = self._cut_face_set(context, bm, obj)` once before the plane loop and stamp it with `_stamp_cut_layer`; in each plane pass `source_faces = [f for f in bm.faces if f[cut_layer] == 1 and is_vis(f)]` (replacing the `selected_faces` / all-visible choice). Remove the cut layer alongside `sel_layer`. Same change in `execute_fill_cut` (replacing the `had_selection` branch). Count objects where `source_faces` was non-empty; when the delimiter is on and the count is 0, call `_cut_report`.

- [ ] **Step 3: Extend the headless test** `tests/blender/test_cursor_bisect_delimit.py` with a cut-level check that does not need the modal: `test_stamp_cut_layer_survives_bisect` — grid 3×1, stamp `{0, 1}`, `bmesh.ops.bisect_plane` through the middle of face 0 (plane_no = (1,0,0)), then assert every face with layer value 1 lies within x-range of the original faces 0-1 and face 2 still has value 0 and is unsplit (its vertex count is 4 and `len(bm.faces) == 4`).

- [ ] **Step 4: Run the headless tests**

Run the delimiter test and the smoke test. Expected `11/11 passed` and `SMOKE_OK`.

- [ ] **Step 5: Manual verification in the live Blender** on `Cube.303` (two islands via the Mirror modifier are not needed; use any mesh with a seam): delimiter ON + Seam, hover one side, LMB: only that side is cut; preview lines matched the cut. Delimiter ON, mouse off the mesh, LMB: info report, nothing cut. RMB-select two faces, hover a third, LMB: info report `not selected`, nothing cut.

- [ ] **Step 6: Commit**

```bash
git add operators/mesh_cursor_bisect.py tests/blender/test_cursor_bisect_delimit.py
git commit -m "feat(cursor-bisect): delimiter filters preview and cut, cut layer survives multi-plane cuts"
```

---

### Task 6: Z axis (cursor plane)

**Files:**
- Modify: `operators/mesh_cursor_bisect.py` — `X` handler (756-764), the five `axis = Vector((1, 0, 0)) if self.normal_axis == 'X' else Vector((0, 1, 0))` sites (986, 1364, 1525, 1720, 1844 before Task 5 edits), `align_cursor_to_world` (2339-2375), plane preview `u/v` (2104-2109), `F`/`V`/`B` handlers (819-865), `_sync_hud_state`, invoke (after `_load_scene_props`).

**Interfaces:**
- Consumes: `next_axis`, `axis_vector` (Task 1).
- Produces:
  - `_axis_vector(self) -> Vector` = `Vector(axis_vector(self.normal_axis))`; replaces every inline axis choice.
  - `_enforce_z_restrictions(self)`: when `normal_axis == 'Z'` sets `fill_cut_mode = inset_active = bevel_active = False`, clears `inset_points`, `fill_cut_preview_lines`, `inset_input_string`.
  - `_z_blocked(self, context) -> bool`: True (and reports `{'INFO'}` `Not available with Z axis`) when `normal_axis == 'Z'`; used at the top of the `F`, `V`, `B` handlers to return `{'RUNNING_MODAL'}` early.

- [ ] **Step 1: Axis cycling.** `X` handler: `self.normal_axis = next_axis(self.normal_axis)`, then `_enforce_z_restrictions()`, recompute preview, `update_status_bar`, `_sync_hud_state`. Status text `[X] Axis` becomes `[X] Axis({self.normal_axis})`.

- [ ] **Step 2: Replace the five inline axis selections with `self._axis_vector()`.**

- [ ] **Step 3: `align_cursor_to_world`.** Add the `normal_axis == 'Z'` branch: world `X` → `Matrix.Rotation(math.radians(90), 3, 'Y')`, world `Y` → `Matrix.Rotation(math.radians(-90), 3, 'X')`, world `Z` → `Matrix.Identity(3)`. (Check: `R_y(90°)·(0,0,1) = (1,0,0)`, `R_x(-90°)·(0,0,1) = (0,1,0)`.)

- [ ] **Step 4: Plane preview.** For `Z`: `u = mat @ Vector((1, 0, 0))`, `v = mat @ Vector((0, 1, 0))`.

- [ ] **Step 5: Lines preview on coplanar faces.** In both preview intersection loops, skip an edge when `abs(d1) < EPSILON and abs(d2) < EPSILON` (the edge lies in the plane; `bisect_plane` adds nothing there). Without this, Z mode would outline the whole hovered face as if it were being cut.

- [ ] **Step 6: Disable F/V/B in Z.** Call `_z_blocked` first in each of the three handlers. `_sync_hud_state`: set `"F"`, `"V"`, `"B"` to `ItemState.DISABLED` when `normal_axis == 'Z'`, otherwise the existing ON/OFF. Call `_enforce_z_restrictions()` in `invoke` right after `_load_scene_props` (Review Focus 4).

- [ ] **Step 7: Add a headless test for the world-align matrices** to `tests/blender/test_cursor_bisect_delimit.py`: `test_world_align_rotations_for_z` builds the three matrices exactly as Step 3 and asserts `(m @ Vector((0,0,1)) - expected).length < 1e-6` for expected `(1,0,0)`, `(0,1,0)`, `(0,0,1)`. (This pins the matrices the operator uses; factor the matrix choice into a module-level `world_align_rotation(normal_axis, world_axis) -> Matrix` so the test and the operator share it, and make the existing X / Y branches use it too.)

- [ ] **Step 8: Run tests**

Delimiter headless test → `12/12 passed`; smoke test → `SMOKE_OK`; `python -m pytest tests -q` → all passed.

- [ ] **Step 9: Manual verification in the live Blender.** Hover a sloped face of a box, press `X` twice → status `[X] Axis(Z)`, preview lines appear on the side walls, not on the hovered face; LMB cuts the walls. `V`, `B`, `F` report `Not available with Z axis`. `W` cycles the cursor Z through world X/Y/Z. `X` again returns to X and the three keys work.

- [ ] **Step 10: Commit**

```bash
git add operators/mesh_cursor_bisect.py tests/blender/test_cursor_bisect_delimit.py
git commit -m "feat(cursor-bisect): Z axis cuts in the cursor plane"
```

---

### Task 7: Documentation

**Files:**
- Modify: `docs/operators/op_mesh_cursor_bisect.md` (controls table, new section before *Tips*), `docs/preferences.md:12`.

- [ ] **Step 1: Controls table.** Change the `X` row to `Cycle which cursor axis is the cut normal: X → Y → Z (Z cuts in the plane of the face under the cursor; Inset, Bevel and Fill Cut are unavailable in Z)`. Add rows `L` — `Delimiter on / off: cut only the piece of mesh under the cursor` and `Shift+L` — `Cycle delimiter type: Mesh Island → Seam → Sharp → UV Island → Material → Normal`.

- [ ] **Step 2: Add a `## Delimiter` section** (4-6 sentences): what it filters, that a face selection is the ceiling and the delimiter filters inside it, that only the hovered object is cut, what each type stops at, and that the Normal type uses the *Delimit Angle* preference.

- [ ] **Step 3: `docs/preferences.md`** line 12: add `delimit angle` to the list.

- [ ] **Step 4: Build check.** Run `python -m mkdocs build --strict` from the repo root if mkdocs is installed; otherwise confirm the Markdown renders (table rows have the same column count).

- [ ] **Step 5: Commit**

```bash
git add docs/operators/op_mesh_cursor_bisect.md docs/preferences.md
git commit -m "docs(cursor-bisect): delimiter and Z axis"
```

---

### Finish

- [ ] Run everything once more: pytest, both headless scripts, smoke test.
- [ ] Squash the task commits into one feature commit per the repo convention before pushing (`squash-feature-commits` skill).
