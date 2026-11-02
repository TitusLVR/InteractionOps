# Instance Collection Edit In Place (Phase 1, local collections) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Edit the objects of a local collection where one of its instances stands: Start moves the originals onto the instancer, Stop moves them back keeping every edit, Restore puts everything back from a snapshot whatever happened in between.

**Architecture:** Pure matrix/bookkeeping helpers in `utils/instance_edit_core.py` (numpy, pytest). Session state lives in `Scene.iops_instance_edit` (a stack of PropertyGroup sessions, saved with the file, in the undo stack). Three operators in `operators/instance_edit.py` share one restore routine. A header block after Selection Sets and a pie entry expose them.

**Tech Stack:** bpy PropertyGroups, `Object.hide_set` / `LayerCollection.exclude`, numpy + pytest for the core, headless Blender script for the integration test, blender-mcp for live checks.

**Spec:** `docs/superpowers/specs/2026-10-22-instance-collection-edit-in-place-design.md` (phase 2 spec `2026-10-22-instance-edit-linked-library-design.md` only constrains the storage shape here).

## Global Constraints

- Snapshot is written to the scene **before any mutation**; the session is cleared **only after** a restore routine ran to completion.
- Start order is fixed: layer/collection visibility, then object visibility, then transforms.
- Roots are moved through `matrix_world`; children are never touched; Restore writes `matrix_basis` only.
- Other instancers are always hidden while editing (no option), including instancers of ancestor collections.
- Poll of Start: Object Mode, active is an Empty with `instance_type == 'COLLECTION'`, `instance_collection.library is None`, no object of `instance_collection.all_objects` has `.library`, no session on the stack.
- Animated / driven / constrained roots: Start proceeds and reports a WARNING naming them, never refuses.
- Storage is a stack from day one: `Scene.iops_instance_edit.sessions`; phase 1 allows at most one item.
- Pref `iops_instance_edit_header` (default True) hides only the idle button; the red icon is drawn whenever a session exists.
- Operators are `{"REGISTER", "UNDO"}`. Repo conventions: English code/comments, `python -m pytest tests -q` green, commit per task on master.

## Review Focus

1. Instancer with non-zero `instance_offset` and rotation+scale: originals must land exactly on the instance's visible content, not just its origin. → Task 1 `test_edit_frame_offset_rotation_scale` + Task 6 headless `test_start_places_roots`.
2. Object parented to something outside the collection: moving it via `matrix_world` must honour that parent, and Restore (basis) must bring it back. → Task 1 `test_split_roots_parent_outside_is_root` + Task 6 `test_restore_external_parent`.
3. Source collection excluded from the view layer with an excluded child collection inside: both must become visible or `hide_set` raises mid-Start. → Task 6 `test_start_unexcludes_descendants`.
4. Instancer deleted mid-session: Stop and Restore must still complete and clear the session. → Task 6 `test_stop_after_instancer_deleted`.
5. File reopened with a session recorded: header must show the red icon + Restore without any selection. → Task 5 draw function reads only the scene stack; Task 6 `test_header_draw_with_session_no_selection` (draw via `bpy.types.VIEW3D_MT_editor_menus` is not callable headless, so the test asserts `session_active(scene)` and that `IOPS_OT_instance_edit_restore.poll` is True with nothing selected).

---

### Task 1: Core helpers (`utils/instance_edit_core.py`)

**Files:**
- Create: `utils/instance_edit_core.py`
- Test: `tests/test_instance_edit_core.py`

**Interfaces:**
- Consumes: numpy only. No bpy.
- Produces:
  - `edit_frame(instance_matrix, instance_offset) -> np.ndarray(4,4)`: `M @ T(-offset)`; inputs are any 4x4 / 3-sequence convertible by `np.asarray(dtype=float)`.
  - `moved(frame, world) -> np.ndarray(4,4)` = `frame @ world`; `unmoved(frame, world)` = `inv(frame) @ world`.
  - `to_flat(m) -> list[float]` (16, row-major) and `from_flat(flat) -> np.ndarray(4,4)`.
  - `split_roots(names, parent_of) -> (roots: list[str], children: list[str])`, input order kept; root = parent None or parent not in `names`.
  - `layer_path(names) -> str` joined with `"\x1f"` (unit separator; collection names may contain `/`), `split_layer_path(path) -> list[str]`.
  - `plan_restore(rows, alive) -> (to_restore: list, missing: list[str])` where `rows` is an iterable of objects with `.name`; `alive` is a set of names.
  - `warnings(roots_info) -> list[str]`: `roots_info` rows are dicts `{"name", "has_transform_anim", "has_transform_constraint"}`; returns one line per flagged root, exact text `"<name>: animated/driven transform"` or `"<name>: transform constraint"` (both lines when both), plus, when non-empty, a first line `"Do not edit these objects or change the frame while editing:"`.

- [ ] **Step 1: Write the failing tests** `tests/test_instance_edit_core.py`

```python
import numpy as np
import pytest
from utils.instance_edit_core import (edit_frame, moved, unmoved, to_flat, from_flat,
                                      split_roots, layer_path, split_layer_path,
                                      plan_restore, warnings)

def rot_z(deg):
    c, s = np.cos(np.radians(deg)), np.sin(np.radians(deg))
    return np.array([[c,-s,0,0],[s,c,0,0],[0,0,1,0],[0,0,0,1.0]])

def test_edit_frame_offset_rotation_scale():
    M = rot_z(90) @ np.diag([2,2,2,1.0]); M[:3,3] = (10, 0, 0)
    A = edit_frame(M, (1, 0, 0))
    # a collection point at the offset itself sits on the instancer origin
    assert np.allclose(A @ np.array([1,0,0,1.0]), [10,0,0,1])
    # a point one unit past the offset along X lands rotated+scaled: (10, 2, 0)
    assert np.allclose(A @ np.array([2,0,0,1.0]), [10,2,0,1])

def test_moved_unmoved_round_trip():
    A = edit_frame(rot_z(33) @ np.diag([1,3,0.5,1.0]), (0.2,-1,4))
    W = rot_z(-70); W[:3,3] = (3,4,5)
    assert np.allclose(unmoved(A, moved(A, W)), W)

def test_flat_round_trip():
    W = rot_z(10); W[:3,3] = (1,2,3)
    assert np.allclose(from_flat(to_flat(W)), W) and len(to_flat(W)) == 16

def test_split_roots_parent_outside_is_root():
    roots, children = split_roots(["a","b","c"], {"a": None, "b": "a", "c": "ext"})
    assert roots == ["a","c"] and children == ["b"]

def test_split_roots_chain_inside():
    roots, children = split_roots(["x","y","z"], {"x": None, "y": "x", "z": "y"})
    assert roots == ["x"] and children == ["y","z"]

def test_layer_path_round_trip_with_slash_in_name():
    names = ["Scene Collection", "Props/Kit", "Asset"]
    assert split_layer_path(layer_path(names)) == names

def test_plan_restore_reports_missing():
    class R:  # mimics a PropertyGroup row
        def __init__(self, n): self.name = n
    rows = [R("a"), R("gone"), R("b")]
    keep, missing = plan_restore(rows, {"a","b"})
    assert [r.name for r in keep] == ["a","b"] and missing == ["gone"]

def test_warnings_lines():
    assert warnings([{"name":"a","has_transform_anim":False,"has_transform_constraint":False}]) == []
    out = warnings([{"name":"a","has_transform_anim":True,"has_transform_constraint":True},
                    {"name":"b","has_transform_anim":False,"has_transform_constraint":True}])
    assert out == ["Do not edit these objects or change the frame while editing:",
                   "a: animated/driven transform", "a: transform constraint",
                   "b: transform constraint"]
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_instance_edit_core.py -q`
Expected: ImportError on `utils.instance_edit_core`.

- [ ] **Step 3: Implement the functions in `utils/instance_edit_core.py`** with the signatures above; module docstring says "no bpy". `unmoved` uses `np.linalg.inv`.

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add utils/instance_edit_core.py tests/test_instance_edit_core.py
git commit -m "feat(instance-edit): pure core for edit frame, roots and restore planning"
```

---

### Task 2: Session storage (`operators/instance_edit_state.py`)

**Files:**
- Create: `operators/instance_edit_state.py`
- Modify: `__init__.py` (class tuple near line 700, `register()` near line 829, `unregister()` near line 978)

**Interfaces:**
- Consumes: Task 1 `to_flat`, `from_flat`, `layer_path`, `split_layer_path`.
- Produces (all in `instance_edit_state.py`):
  - PropertyGroups, registered in this order: `IOPS_IE_ObjRef` (`ref: PointerProperty(type=bpy.types.Object)`, `name: StringProperty`, `is_root: BoolProperty`, `basis: FloatVectorProperty(size=16)`, `hide_get: BoolProperty`, `hide_viewport: BoolProperty`), `IOPS_IE_InstRef` (`ref` Object, `name`, `hide_get`), `IOPS_IE_LayerRef` (`path: StringProperty`, `exclude`, `hide_viewport`), `IOPS_IE_CollRef` (`ref: PointerProperty(type=bpy.types.Collection)`, `name`, `hide_viewport`), `IOPS_IE_Session` (`kind: EnumProperty items LOCAL/LINKED default LOCAL`, `instancer` Object pointer + `instancer_name`, `collection` Collection pointer + `collection_name`, `frame: FloatVectorProperty(size=16)`, `linked_to_scene: BoolProperty`, `prev_active_layer_path: StringProperty`, `objects`, `instancers`, `layer_colls`, `colls` CollectionProperties of the rows above), `IOPS_IE_Stack` (`sessions: CollectionProperty(type=IOPS_IE_Session)`).
  - `CLASSES` tuple in registration order; `register_props()` sets `bpy.types.Scene.iops_instance_edit = PointerProperty(type=IOPS_IE_Stack)`; `unregister_props()` deletes it (guarded).
  - `active_session(scene) -> IOPS_IE_Session | None` (last item), `push_session(scene) -> IOPS_IE_Session`, `pop_session(scene)`, `session_active(scene) -> bool`.
  - `resolve_object(row) -> bpy.types.Object | None`: `row.ref` if not None else `bpy.data.objects.get(row.name)`.
  - `resolve_collection(row)` likewise on `bpy.data.collections`.
  - `find_layer_collection(root_layer_coll, collection) -> LayerCollection | None` (depth-first), `layer_collection_path(root, layer_coll) -> str` (names from root down, via `layer_path`), `layer_collection_by_path(root, path) -> LayerCollection | None`.
  - `set_frame(session, np_matrix)` / `get_frame(session) -> np.ndarray` and `set_basis(row, mathutils.Matrix)` / `get_basis(row) -> mathutils.Matrix` (row-major flat, `Matrix` built from 4 rows).

- [ ] **Step 1: Implement the module** as specified. No operators here.

- [ ] **Step 2: Register in `__init__.py`**: import `instance_edit_state`, splice `*instance_edit_state.CLASSES` into the class tuple right after `IOPS_PT_SelectionSets_Panel`; call `instance_edit_state.register_props()` right after `Scene.iops_selection_sets` is assigned; `unregister_props()` next to the `iops_selection_sets` deletion.

- [ ] **Step 3: Verify over MCP (blender-mcp skill)**: reload the addon; run

```python
import bpy, numpy as np
from InteractionOps.operators import instance_edit_state as st
sc = bpy.context.scene
assert not st.session_active(sc)
s = st.push_session(sc); st.set_frame(s, np.eye(4)); assert st.session_active(sc)
r = s.objects.add(); r.name = "nope"; assert st.resolve_object(r) is None
st.pop_session(sc); assert not st.session_active(sc)
lc = st.find_layer_collection(bpy.context.view_layer.layer_collection, sc.collection)
assert lc is bpy.context.view_layer.layer_collection
```
Expected: no assertion error.

- [ ] **Step 4: Commit**

```bash
git add operators/instance_edit_state.py __init__.py
git commit -m "feat(instance-edit): scene session stack and snapshot rows"
```

---

### Task 3: Start operator (`operators/instance_edit.py`)

**Files:**
- Create: `operators/instance_edit.py`
- Modify: `__init__.py` (class tuple: add the operator after the state classes)

**Interfaces:**
- Consumes: Task 1 (`edit_frame`, `moved`, `split_roots`, `warnings`), Task 2 (everything), `operators.assets_management._is_collection_instance`.
- Produces:
  - `collect_targets(coll) -> list[Object]` = `list(coll.all_objects)`, deduplicated, stable order.
  - `instancers_of(scene, coll) -> list[Object]`: objects of `scene.objects` with `instance_type == 'COLLECTION'` whose `instance_collection` is `coll` or has `coll` in `instance_collection.children_recursive`.
  - `can_start(context) -> (bool, str)` implementing the Global Constraints poll (reason string for the tooltip / report).
  - `write_snapshot(context, session, instancer, coll, targets, root_names, frame)` filling every row kind; records `linked_to_scene`, `layer_colls` (the collection's layer collections and all descendants, by path), `colls` (collection, ancestors in the scene tree, descendants), `prev_active_layer_path`.
  - `apply_edit_state(context, session)`: the mutation half of Start in the fixed order (link collection if needed; layer colls exclude/hide off; colls hide_viewport off; targets hide off; instancers `hide_set(True)`; roots `matrix_world = frame @ matrix_world`; active layer collection = the collection's; select targets).
  - `class IOPS_OT_instance_edit_start(bpy.types.Operator)`: `bl_idname = "iops.instance_edit_start"`, label "Edit Instance", `bl_options = {"REGISTER", "UNDO"}`, `poll` = `can_start(context)[0]` with `poll_message_set` of the reason, `execute`: compute frame + roots, warnings → `self.report({'WARNING'}, "\n".join(lines))` when any, `write_snapshot`, then `apply_edit_state` inside `try`; on exception call Task 4's `restore_session(context, session)` and re-raise. (Task 4 adds that function; until then wrap the exception branch so the module imports: `from . import instance_edit_restore` is lazy inside the `except`.)

- [ ] **Step 1: Implement** as specified. `instancer.instance_collection.instance_offset` goes into `edit_frame` (Blender 5.2 keeps the offset on the Collection). Ancestor collections for `colls`: walk `bpy.data.collections` for parents via `children` membership up to `scene.collection`. Objects whose `hide_set` raises because they are not in the view layer: report and skip (they still get moved).

- [ ] **Step 2: Register** `IOPS_OT_instance_edit_start` in `__init__.py`.

- [ ] **Step 3: Verify over MCP**: in a fresh scene build: collection `Asset` (excluded) with `Cube` and `Child` (parent `Cube`), child collection `Sub` (excluded) with `Sphere`; instancers `A` at (10,0,0) rotated 90° Z with `Asset.instance_offset=(1,0,0)` and `B` at (0,10,0); select `A`, run `bpy.ops.iops.instance_edit_start()`. Assert: `Cube.matrix_world.translation` ≈ (10, -1, 0) (Cube origin at (0,0,0) minus offset, rotated), `A.hide_get() and B.hide_get()`, layer collections of `Asset` and `Sub` not excluded, `scene.iops_instance_edit.sessions[0].objects` has 3 rows, `Cube`'s row `is_root`, `Child`'s not, active layer collection is `Asset`.

- [ ] **Step 4: Commit**

```bash
git add operators/instance_edit.py __init__.py
git commit -m "feat(instance-edit): Start operator moves originals onto the instancer"
```

---

### Task 4: Restore routine, Restore and Stop operators

**Files:**
- Modify: `operators/instance_edit.py`
- Modify: `__init__.py` (register the two operators)

**Interfaces:**
- Consumes: Task 1 `plan_restore`, `unmoved`, `split_roots`; Task 2 resolvers.
- Produces:
  - `restore_visibility(context, session) -> list[str]` (missing names): reverse of `apply_edit_state`'s visibility half, instancers via `hide_set(prev)`, previous active layer collection restored, collection unlinked from scene root if `linked_to_scene`.
  - `restore_session(context, session) -> list[str]`: ensure Object Mode (`bpy.ops.object.mode_set(mode='OBJECT')` when `context.mode != 'OBJECT'`), for every row from `plan_restore` set `matrix_basis` then `hide_set`/`hide_viewport`, then `restore_visibility`, then `pop_session`. Session popped only when everything before it finished.
  - `stop_session(context, session) -> list[str]`: Object Mode; for every current root of `collection.all_objects` (via `split_roots` on current parents): `matrix_world = inverse(frame) @ matrix_world`; then `restore_visibility`; `pop_session`; select + activate the instancer when it resolves.
  - `class IOPS_OT_instance_edit_restore` (`iops.instance_edit_restore`, label "Restore Instance Edit", description "Put every object of the edited collection back where it was when editing started, discarding transform edits made since; geometry, modifier and material edits stay"), `class IOPS_OT_instance_edit_stop` (`iops.instance_edit_stop`, label "Stop Instance Edit"). Both: poll `session_active(scene)`, `{"REGISTER","UNDO"}`, report `{'WARNING'}` with `"Missing: " + ", ".join(missing)` when any.

- [ ] **Step 1: Implement** the three functions and two operators; wire Task 3's exception branch to `restore_session`.

- [ ] **Step 2: Register** both operators in `__init__.py`.

- [ ] **Step 3: Verify over MCP** on the Task 3 scene: after Start, `Cube.location.x += 1`, add a new cube (lands in `Asset`), run `iops.instance_edit_stop`; assert `Cube.matrix_basis.translation` ≈ (0, -1, 0): the +1 world-X move survives, expressed in the collection frame through `inverse(frame)` (the instancer is rotated 90° about Z, so world X maps to local -Y); the new cube's `matrix_world` equals `inverse(frame) @ (its world at creation)`, `A` and `B` visible, `Asset` excluded again, stack empty. Then Start again, move `Cube`, run `iops.instance_edit_restore`; assert `Cube.matrix_basis` equals the pre-Start basis exactly and stack empty.

- [ ] **Step 4: Commit**

```bash
git add operators/instance_edit.py __init__.py
git commit -m "feat(instance-edit): Stop keeps edits, Restore rewinds to the snapshot"
```

---

### Task 5: Header block, preference, pie entry

**Files:**
- Create: `ui/iops_instance_edit_header.py`
- Modify: `prefs/addon_preferences.py:225-229` (add pref next to `iops_ss_header`), `prefs/addon_preferences.py:1148` (draw it on the next line), `operators/preferences/io_addon_preferences.py:313` (add `("iops_instance_edit_header", True)` to the tuple), `prefs/iops_prefs.py:246` (add `"iops_instance_edit_header": safe("iops_instance_edit_header", True)`), `ui/iops_pie_edit.py:716-721` (the `else` branch that emits two `pie.separator()` for local collections), `__init__.py:843` and `:961` (append/remove the draw function right after the Selection Sets one).

**Interfaces:**
- Consumes: Task 2 `active_session`, `session_active`; Task 3 `can_start`.
- Produces: `draw_iops_instance_edit_header(self, context)` appended to `VIEW3D_MT_editor_menus`.

- [ ] **Step 1: Pref** `iops_instance_edit_header: BoolProperty(name="Instance Edit in 3D View Header", description="Show the Edit Instance button in the 3D View header (the red icon of an open session is always shown)", default=True)` in the four files listed.

- [ ] **Step 2: Header draw function**: return unless `context.mode in {"OBJECT","EDIT_MESH"}`; `layout.separator()`; if `session_active(scene)`: `row = layout.row(align=True); row.alert = True; row.operator("iops.instance_edit_stop", text="", icon="OUTLINER_COLLECTION", depress=True)` then `row.operator("iops.instance_edit_restore", text="", icon="RECOVER_LAST")`; else if pref on: `row.operator("iops.instance_edit_start", text="", icon="OUTLINER_COLLECTION")` (greyed by poll). Tooltip of Stop must name the session: set `bl_description` dynamically is not possible, so the Stop operator gets a classmethod `description(cls, context, properties)` returning `f"Stop editing {s.collection_name} (instanced by {s.instancer_name})"`.

- [ ] **Step 3: Pie**: in the local-collection `else` branch replace the first `pie.separator()` (slot 7) with `pie.operator("iops.instance_edit_start", text="Edit Instance", icon="OUTLINER_COLLECTION")`; keep the second separator.

- [ ] **Step 4: Verify over MCP**: reload addon; `"iops_instance_edit_header" in prefs.bl_rna.properties`; `draw_iops_instance_edit_header in bpy.types.VIEW3D_MT_editor_menus._dyn_ui_initialize()`; with a session pushed by `instance_edit_state.push_session`, `IOPS_OT_instance_edit_stop.description(bpy.context, None)` contains the collection name; pop it.

- [ ] **Step 5: Commit**

```bash
git add ui/iops_instance_edit_header.py prefs/addon_preferences.py prefs/iops_prefs.py operators/preferences/io_addon_preferences.py ui/iops_pie_edit.py __init__.py
git commit -m "feat(instance-edit): header buttons, red session icon, pref and pie entry"
```

---

### Task 6: Headless integration test

**Files:**
- Create: `tests/blender/test_instance_edit.py` (run like `tests/smoke_register.py`: `blender --background --factory-startup --python tests/blender/test_instance_edit.py` with `BLENDER_USER_SCRIPTS` pointing at a scripts dir whose `addons/InteractionOps` is this repo).
- Modify: `tests/smoke_register.py` (add `"instance_edit_start"`, `"instance_edit_stop"`, `"instance_edit_restore"` to the operator list).

**Interfaces:**
- Consumes: the three operators; `Scene.iops_instance_edit`.

- [ ] **Step 1: Write the script**: a `build_scene()` helper creating the Task 3 scene from `bpy.ops.wm.read_homefile(use_empty=True)`, plus `Ext` (an object outside `Asset`) with `Child2` in `Asset` parented to `Ext`. Test functions, each starting from a fresh `build_scene()`, each asserting with `mathutils.Matrix` comparisons at 1e-5:
  - `test_start_places_roots`: Cube world == `frame @ cube_world_before`; Child's world follows (its basis unchanged).
  - `test_restore_external_parent`: Start, set `Child2.location += (0,0,3)`, Restore → `Child2.matrix_basis == before`, `Ext` untouched.
  - `test_start_unexcludes_descendants`: `Sub` excluded before → `Sphere` moved and visible after Start; excluded again after Stop.
  - `test_stop_keeps_edits_and_new_objects`: as Task 4 Step 3.
  - `test_stop_after_instancer_deleted`: Start, `bpy.data.objects.remove(A)`, Stop → returns FINISHED, stack empty, `B` visible.
  - `test_restore_after_object_deleted`: Start, remove `Sphere`, Restore → FINISHED, stack empty, report mentions `Sphere` (capture via `bpy.ops` return + checking the session row name before the call).
  - `test_header_draw_with_session_no_selection`: Start, deselect all, `bpy.context.view_layer.objects.active = None` → `IOPS_OT_instance_edit_restore.poll(bpy.context)` is True; Stop.
  - `test_poll_refuses_linked_and_nested_session`: a collection containing an object with `library` set is not constructible headless without a second file, so this test writes a tiny library blend to a temp dir with `bpy.data.libraries.write`, links one object into `Asset`, and asserts `can_start(bpy.context)[0] is False`; also after Start on a clean scene, `can_start` is False (session present).
  The script runs every `test_*` function, prints `PASS <name>` / `FAIL <name>` with the traceback, and exits with code 1 on any failure.

- [ ] **Step 2: Run it**

Run: `blender --background --factory-startup --python tests/blender/test_instance_edit.py` (the user's `C:\Blender\stable\blender-5.2.2-lts.d13f752e3b9c\blender.exe`, with the `BLENDER_USER_SCRIPTS` junction as the smoke test describes).
Expected: every line `PASS`, exit code 0. Fix the operators, not the tests, on failure.

- [ ] **Step 3: Run the pure tests and the smoke test**

Run: `python -m pytest tests -q`; then the smoke test command from its docstring.
Expected: green; smoke exits 0.

- [ ] **Step 4: Commit**

```bash
git add tests/blender/test_instance_edit.py tests/smoke_register.py
git commit -m "test(instance-edit): headless start/stop/restore scenarios"
```

---

### Task 7: Docs

**Files:**
- Modify: `README.md` (feature list, wherever Selection Sets is described) and the mkdocs page that documents the 3D View header / Selection Sets (find with `grep -rn "Selection Sets" docs/*.md docs/**/*.md`).

- [ ] **Step 1:** Add a short "Edit Instance" section: what Start / Stop / Restore do, the red icon, that other instances are hidden while editing, the animation/driver warning, that linked collections are not supported yet (phase 2).

- [ ] **Step 2: Commit**

```bash
git add README.md docs
git commit -m "docs(instance-edit): document Edit Instance / Stop / Restore"
```
