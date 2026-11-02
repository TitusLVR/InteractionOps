# Instance Edit, Phase 2 (linked collections with write-back) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Edit a collection linked from another .blend where its instance stands, and on Commit merge exactly that collection back into the source file through a background Blender, with a dry-run plan the user confirms, a backup, and per-datablock control over shared data.

**Architecture:** Phase 1's session stack (`Scene.iops_instance_edit`) gains a `LINKED` kind with source-file bookkeeping and an owned-ID map. A new module `operators/instance_edit_linked.py` holds Start (linked branch), Commit, Cancel and Rollback; `operators/instance_edit_merge_worker.py` is a standalone script run by a background Blender (`--background --factory-startup`) in `plan` or `write` mode and talks JSON. Pure planning logic lives in `utils/instance_edit_core.py`. Phase 1 helpers (`edit_frame`, `is_similarity`, `_record_transform`, `_write_channels`, `root_names_of`, `_reveal_active_in_outliners`, `_ensure_object_mode`, `_session_view_layer`) are reused, not duplicated.

**Tech Stack:** bpy (`bpy.data.libraries.load/write`, `ID.user_remap`, `Library.reload`), `subprocess` through `operators/library/common.py` conventions, numpy + pytest for the core, headless Blender scripts for integration.

**Spec:** `docs/superpowers/specs/2026-10-22-instance-edit-linked-library-design.md` (builds on `2026-10-22-instance-collection-edit-in-place-design.md`).

## Global Constraints

- Verified Blender 5.2 facts the design rests on: `libraries.load(link=False)` copies every same-file ID reachable from the collection (nested same-file collections included); nothing from the source stays linked; third-library IDs stay linked; appending over existing names suffixes; `ID.user_remap` is a silent no-op across types; the append creates a `Library` datablock for the temp blend that must be removed before saving; `--factory-startup` sets `save_version = 1` (set 0 in the worker).
- Matching key between editing file and worker: transient custom property `id["iops_commit"] = <row index>` on every owned ID, written just before `libraries.write` and stripped in the same operator; the worker strips it from every appended ID and asserts none remain before saving. Names are never used for matching.
- The session owns exactly the opened collection: nested same-file collections are re-pointed to their linked originals, their copies removed, their IDs dropped from the owned set.
- Shared IDs (source original used outside `C`'s subtree) default to **kept** (source version wins, copy discarded); only the IDs the user ticks in the plan dialog are replaced. Exclusive IDs are always replaced.
- The worker saves exactly once, at its very end; any exception → `ok: false`, source untouched. Backup `<source>.iops_bak.blend` is written before the write run. Temp files live next to the source: `<stem>.iops_commit.blend` + `.json`.
- Perforce: never clear the read-only bit; with `iops_instance_edit_p4` on, try `p4 edit <file>` (cwd = source dir, 30 s timeout); still read-only → Commit CANCELLED with the reason, session stays open.
- Stack discipline: only the top session is operable; Stop/Restore poll `kind == "LOCAL"`, Commit/Cancel poll `kind == "LINKED"`. Other instancers of a linked collection are NOT hidden.
- Start (linked) refuses non-similarity / zero-scale frames exactly like phase 1 (same message). Untouched appended roots are exported with their recorded channels written back verbatim (phase 1's untouched rule), so an edit that touched nothing round-trips the source bit for bit.
- Headless verification only; never the user's live Blender; never save anything but the test's own temp files under the scratchpad.
- Repo conventions: English code/comments, LF, `python -m pytest tests -q` green, commit per task on master, `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus

1. Source file changed by someone else between Start and Commit: the merge still runs on the current content, the dialog shows the warning. → Task 5 `test_commit_warns_when_source_changed`.
2. A user-created object whose name collides with an existing source ID of another asset: must be `added` with a suffix, never `replaced`. → Task 1 `test_merge_plan_user_name_collision_is_added` + Task 4 worker test `test_worker_user_collision_keeps_foreign_id`.
3. Shared material left unticked: source keeps its version, every object of `C` in the source that used it is relinked to the source's material, the copy is gone. → Task 4 `test_worker_shared_kept_relinks`.
4. Worker crash mid-run (exception injected): source file bytes identical, no stray `Library` datablock, no `iops_commit` tags anywhere, session still open in the editing file. → Task 4 `test_worker_exception_leaves_source_untouched` + Task 5 `test_commit_failure_keeps_session`.
5. Nested linked collection from the same source file: after Start the inner instancer points at the still-linked collection and is not owned; an inner LINKED session on it commits to the same file first; the outer Commit then writes `C` whose Empty still references the linked `D`. → Task 3 `test_start_unowns_nested_same_file_collection` + Task 7 `test_nested_sessions_commit_inner_then_outer`.

---

### Task 1: Core planning helpers (`utils/instance_edit_core.py`)

**Files:**
- Modify: `utils/instance_edit_core.py`
- Test: `tests/test_instance_edit_core.py`

**Interfaces:**
- Produces:
  - `OwnedRow = namedtuple("OwnedRow", "index id_type source_name local_name")`.
  - `merge_plan(owned_rows, tagged, untagged_added, existing, users_outside, update_shared) -> dict` with keys `replaced, added, kept, shared, unlinked, deleted`, each a sorted list of `(id_type, name)`. Inputs: `tagged` = `{index: (id_type, appended_name)}` for appended IDs carrying the tag; `untagged_added` = list of `(id_type, final_name)`; `existing` = set of `(id_type, source_name)` present in the source; `users_outside` = set of `(id_type, source_name)` whose source original has users outside `C`'s subtree; `update_shared` = set of `(id_type, source_name)`. Rules: tagged + existing + (not shared or in update_shared) → `replaced` (and listed in `shared` when shared); tagged + existing + shared + not ticked → `kept` (+ `shared`); tagged + not existing → `added`; every untagged → `added` with its final name. `unlinked`/`deleted` are passed through from the caller as `(id_type, name)` lists (the worker computes membership).
  - `plans_match(a, b) -> bool` comparing the `replaced/added/kept` sets only (order-insensitive).
  - `source_changed(recorded, current) -> bool` on `(mtime, size)` tuples with a 1e-3 s tolerance on mtime.
  - `commit_temp_paths(source_path) -> (temp_blend, temp_json, backup_blend)` = `<dir>/<stem>.iops_commit.blend`, `<dir>/<stem>.iops_commit.json`, `<dir>/<stem>.iops_bak.blend`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_instance_edit_core.py`)

```python
from utils.instance_edit_core import (OwnedRow, merge_plan, plans_match,
                                      source_changed, commit_temp_paths)

ROWS = [OwnedRow(0, "objects", "Cube", "Cube"), OwnedRow(1, "materials", "SharedMat", "SharedMat.001"),
        OwnedRow(2, "meshes", "NewMeshFromSrc", "NewMeshFromSrc")]
TAGGED = {0: ("objects", "Cube.001"), 1: ("materials", "SharedMat.002"), 2: ("meshes", "NewMeshFromSrc")}
EXISTING = {("objects", "Cube"), ("materials", "SharedMat"), ("objects", "Lamp")}
OUTSIDE = {("materials", "SharedMat")}

def test_merge_plan_exclusive_replaced_shared_kept_by_default():
    p = merge_plan(ROWS, TAGGED, [], EXISTING, OUTSIDE, set())
    assert p["replaced"] == [("objects", "Cube")]
    assert p["kept"] == [("materials", "SharedMat")]
    assert p["shared"] == [("materials", "SharedMat")]
    assert p["added"] == [("meshes", "NewMeshFromSrc")]

def test_merge_plan_ticked_shared_is_replaced():
    p = merge_plan(ROWS, TAGGED, [], EXISTING, OUTSIDE, {("materials", "SharedMat")})
    assert ("materials", "SharedMat") in p["replaced"] and p["kept"] == []

def test_merge_plan_user_name_collision_is_added():
    p = merge_plan(ROWS, TAGGED, [("objects", "Lamp.001")], EXISTING, OUTSIDE, set())
    assert ("objects", "Lamp.001") in p["added"] and ("objects", "Lamp") not in p["replaced"]

def test_plans_match_ignores_order_and_unlinked():
    a = merge_plan(ROWS, TAGGED, [], EXISTING, OUTSIDE, set()); b = dict(a)
    b["replaced"] = list(reversed(a["replaced"])); b["unlinked"] = [("objects", "x")]
    assert plans_match(a, b)

def test_source_changed():
    assert not source_changed((100.0, 5), (100.0004, 5))
    assert source_changed((100.0, 5), (100.0, 6)) and source_changed((100.0, 5), (101.0, 5))

def test_commit_temp_paths():
    t, j, b = commit_temp_paths("D:/lib/Props.blend")
    assert t.endswith("Props.iops_commit.blend") and j.endswith("Props.iops_commit.json") and b.endswith("Props.iops_bak.blend")
```

- [ ] **Step 2: Run** `python -m pytest tests/test_instance_edit_core.py -q` → ImportError on the new names.
- [ ] **Step 3: Implement** the four functions + `OwnedRow`. Pure Python, `os.path` only.
- [ ] **Step 4: Run** `python -m pytest tests -q` → green.
- [ ] **Step 5: Commit** `feat(instance-edit): merge planning core for linked write-back`.

---

### Task 2: Session fields, owned rows, preferences

**Files:**
- Modify: `operators/instance_edit_state.py`, `prefs/addon_preferences.py` (next to `iops_instance_edit_header`), `operators/preferences/io_addon_preferences.py`, `prefs/iops_prefs.py`

**Interfaces:**
- Produces in `instance_edit_state.py`:
  - `IOPS_IE_OwnedRef(PropertyGroup)`: `id_type: StringProperty` (the `bpy.data` attribute, e.g. `"objects"`), `source_name`, `local_name`, `ref: PointerProperty(type=bpy.types.ID)`, `is_root: BoolProperty`, plus the phase-1 transform fields copied by name (`location`, `rotation_mode`, `rotation_euler`, `rotation_quaternion`, `rotation_axis_angle`, `scale`, `edit_basis`) so `_record_transform`/`_write_channels` work on it (they take any row with those attributes).
  - `IOPS_IE_Session` gains: `source_path: StringProperty`, `source_mtime: FloatProperty`, `source_size: IntProperty`, `source_coll_name: StringProperty`, `copy_collection: PointerProperty(Collection)`, `copy_collection_name: StringProperty`, `owned: CollectionProperty(type=IOPS_IE_OwnedRef)`, `library_name: StringProperty` (the `bpy.data.libraries` entry name).
  - `CLASSES` updated (OwnedRef before Session). `resolve_owned(row) -> ID | None` (ref only).
  - `WindowManager.iops_ie_shared: CollectionProperty(type=IOPS_IE_SharedRow)` where `IOPS_IE_SharedRow` has `id_type`, `source_name`, `users: StringProperty` (comma-joined other users), `update: BoolProperty(default=False)`; registered in `register_props`/removed in `unregister_props`.
- Prefs: `iops_instance_edit_p4: BoolProperty(name="Instance Edit: Perforce checkout", description="Run 'p4 edit' on a read-only source file before Commit", default=False)`, `iops_instance_edit_worker_timeout: IntProperty(name="Instance Edit: worker timeout (s)", default=300, min=30, max=3600)`; wired in all four places like `iops_instance_edit_header`; drawn under it.

- [ ] **Step 1: Implement** the fields, classes, registration and prefs.
- [ ] **Step 2: Verify headless**: enable the addon (`sys.path.insert(0, "D:/git")`), push a session, add an `owned` row with `ref = bpy.data.materials.new("m")`, assert `resolve_owned(row)` is that material and the prefs exist with their defaults; `python -m pytest tests -q` green.
- [ ] **Step 3: Commit** `feat(instance-edit): linked-session storage, shared-row list and prefs`.

---

### Task 3: Linked Start (`operators/instance_edit_linked.py`)

**Files:**
- Create: `operators/instance_edit_linked.py`
- Modify: `operators/instance_edit.py` (`can_start` linked branch; `IOPS_OT_instance_edit_start.execute` dispatches to the linked path), `__init__.py` (register module classes later in Task 5; this task only adds functions)

**Interfaces:**
- Consumes: phase-1 helpers listed in Architecture; `edit_frame`, `is_similarity`, `commit_temp_paths`.
- Produces:
  - `can_start_linked(context) -> (bool, reason)`: Object Mode; instancer Empty with `instance_collection.library` set; library file exists on disk; frame is a similarity; no LOCAL session on top of the stack whose collection contains this instancer (a LINKED session may nest on anything; a LOCAL session may only be nested when the instancer is inside the top LINKED session's copy); no open LINKED session on the same `(source_path, source_coll_name)`.
  - `can_start(context)` in `instance_edit.py` becomes: linked instancer → `can_start_linked`; else the phase-1 rules.
  - `append_collection_copy(source_path, coll_name) -> (collection, owned_ids: list[ID])`: `bpy.data.libraries.load(source_path, link=False)` with `data_to.collections = [coll_name]`; owned = every ID in `bpy.data` whose `library is None` and that did not exist before the call (snapshot `set(id.as_pointer())` per `bpy.data` collection before/after), excluding the editing file's own new nothing-else.
  - `unown_nested_same_file(copy_coll, owned_ids, source_path) -> list[ID]`: for each Empty in `copy_coll.all_objects` with `instance_type == 'COLLECTION'` whose `instance_collection` is an owned copy: find or link (`libraries.load(link=True)`) the linked collection of the same source name from `source_path`, re-point the Empty, collect the copied sub-collection's subtree IDs that have no other users, remove them, return the remaining owned list.
  - `start_linked(context, instancer) -> list[str] warnings`: records source path/mtime/size/coll name/library name; appends; unowns nested; renames the copy to `f"{name} [edit]"`; links it under `scene.collection`; fills `owned` rows (`id_type`, `source_name` = name at append time before any rename, `local_name` = current name, `ref`, `is_root`, transforms via `_record_transform`); builds `A`, moves roots (`matrix_world = A @ ...`, then `edit_basis`); hides the instancer only (`hide_set`, recorded in `instancers`); sets active layer collection (records previous); selects the copy, reveals in outliners; pushes the session with `kind = "LINKED"`, `frame`, `view_layer_name`; warns via phase 1's `warnings` and about library overrides of the collection in the current file.
  - Phase-1 `execute`: `if obj.instance_collection.library: warnings = start_linked(...)` else the existing path; same exception discipline (on failure after the push: `cancel_linked` then re-raise).

- [ ] **Step 1: Implement.** Keep `append_collection_copy` and `unown_nested_same_file` free of session state so Task 7 can test them alone.
- [ ] **Step 2: Headless verify** with a throwaway script that writes a source blend to the scratchpad (collection `C` with `Cube` + `Child`, material `SharedMat` also used by a second collection `Other`, nested collection `D` instanced by an Empty inside `C`), links `C` into a fresh file, adds an instancer at (10,0,0) rotated 90°, runs `bpy.ops.iops.instance_edit_start()`; assert: copy collection `"C [edit]"` under scene root, `Cube` copy at the instance (`frame @ world`), the inner Empty's `instance_collection.library` is set (D not owned), owned rows list objects/meshes/materials from `C` only, top session kind `LINKED`, instancer hidden, other instancers visible.
- [ ] **Step 3: Commit** `feat(instance-edit): linked Start appends the collection copy in place`.

---

### Task 4: Merge worker (`operators/instance_edit_merge_worker.py`)

**Files:**
- Create: `operators/instance_edit_merge_worker.py` (standalone; imports only `bpy`, `json`, `sys`, `os`, `traceback`; must not import the addon)
- Create: `tests/blender/test_instance_edit_merge_worker.py`

**Interfaces:**
- CLI: `blender --background --factory-startup --disable-autoexec <source.blend> --python instance_edit_merge_worker.py -- <temp.json> <plan|write> <result.json>`.
- `temp.json` schema: `{"temp_blend": str, "source_coll_name": str, "copy_coll_name": str, "owned": [{"index": int, "id_type": str, "source_name": str}], "update_shared": [[id_type, source_name], ...], "expected_plan": {...} | null}`.
- `result.json`: `{"ok": bool, "plan": {replaced, added, kept, shared, unlinked, deleted, shared_users: {"<id_type>:<name>": [other user names]}}, "source_blender_version": [maj, min, patch], "error": str | null}`.
- Algorithm (both modes; `write` mutates and saves): resolve `C` by `source_coll_name` (local); record parents (collections whose `children` contain it, scenes whose root contains it); record `C`'s subtree object set; append `copy_coll_name` from `temp_blend` (`link=False`); collect tagged IDs over every `bpy.data` collection (`"iops_commit" in id.keys()`), `del` the tag; compute `users_outside` for each owned source original via `bpy.data.user_map(subset=[old])` minus `C`'s subtree IDs; apply the rules (replace: `old.user_remap(new)` same type only, remove old, `new.name = source_name`; kept: `new.user_remap(old)`, remove new; added: `new.name = source_name`); untagged appended IDs → `added` with their final names; membership: old subtree objects not in the new one → unlinked, deleted when no users remain; relink the new `C` under the recorded parents; remove the temp `Library` datablock; set relative paths on appended images only; assert no `iops_commit` remains; in `write` mode `plans_match` against `expected_plan` (compare `replaced/added/kept`), `preferences.filepaths.save_version = 0`, `bpy.ops.wm.save_mainfile()`; write `result.json`; exit code 0 on `ok`, 1 otherwise. The plan computation reuses the rule table of Task 1 (the worker cannot import the addon, so it carries a 20-line copy of `merge_plan` marked `# mirrors utils/instance_edit_core.merge_plan`).

- [ ] **Step 1: Write the headless worker test** `tests/blender/test_instance_edit_merge_worker.py` (runs under the same `--python` recipe as `tests/blender/test_instance_edit.py`, enables nothing, spawns the worker via `subprocess` with `bpy.app.binary_path`): builds in a temp dir a `source.blend` (collection `C`: `Cube`+`CubeMesh`+`SharedMat`; collection `Other`: `Lamp` using `SharedMat`; scene links both) and a `temp.blend` (a copy `C` where `Cube`'s mesh has one vertex moved, `SharedMat` colour changed, a new object `Lamp` (!) added, tags set as the operator would), then:
  - `test_worker_plan_mode_writes_nothing`: plan mode → `result.ok`, `replaced` has Cube/CubeMesh, `kept` has SharedMat, `added` has `("objects","Lamp.001")`; source bytes unchanged.
  - `test_worker_write_replaces_and_keeps`: write mode with the plan as `expected_plan` → reopened source: `Cube`'s vertex moved, `SharedMat` colour unchanged, `Lamp` (Other) untouched, `Lamp.001` inside `C`, no `.iops_commit` library, no `iops_commit` tags, file version saved by this Blender.
  - `test_worker_shared_kept_relinks`: Cube's material in the reopened source is the source's `SharedMat` (single user count check).
  - `test_worker_ticked_shared_is_replaced`: `update_shared=[["materials","SharedMat"]]` → colour changed, `Lamp` in `Other` uses the new material.
  - `test_worker_user_collision_keeps_foreign_id`: as above, the foreign `Lamp` keeps its data.
  - `test_worker_exception_leaves_source_untouched`: `expected_plan` deliberately wrong → `ok: false`, exit 1, source bytes identical.
- [ ] **Step 2: Run** → FAIL (worker missing).
- [ ] **Step 3: Implement the worker.**
- [ ] **Step 4: Run** the worker test → all PASS, exit 0.
- [ ] **Step 5: Commit** `feat(instance-edit): background merge worker with plan/write modes`.

---

### Task 5: Commit, Cancel, Rollback operators and the plan dialog

**Files:**
- Modify: `operators/instance_edit_linked.py`, `__init__.py` (register `IOPS_OT_instance_edit_commit`, `IOPS_OT_instance_edit_cancel`, `IOPS_OT_instance_edit_rollback_source`)

**Interfaces:**
- `preflight(context, session) -> (ok, lines, writable)`: source exists; `source_changed` warning line; writable check with the optional `p4 edit` (`subprocess.run(["p4","edit",path], cwd=dir, timeout=30, creationflags=worker_creation_flags())`).
- `export_copy(context, session) -> (temp_blend, temp_json)`: `_ensure_object_mode`; for every current root of the copy: untouched (phase-1 rule against `edit_basis` + parent unchanged) → `_write_channels` from the owned row, else `matrix_world = inverse(A) @ matrix_world` (computed first, written after); tag owned IDs; `bpy.data.libraries.write(temp_blend, {copy_coll}, path_remap='ABSOLUTE', fake_user=False)`; write json; strip tags; move the roots back with `A` (untouched roots: `matrix_basis = edit_basis`).
- `run_worker(source_path, temp_json, mode, result_json, timeout) -> dict` using `bpy.app.binary_path`, `worker_creation_flags()`, `subprocess.run(..., timeout=timeout)`; returns the parsed result or `{"ok": False, "error": ...}`.
- `cancel_linked(context, session) -> list[str]`: remove the copy collection and every owned ID without other users (`bpy.data.<type>.remove` after `user_remap` is unnecessary: they are copies), delete temp files if present, unhide the instancer (phase-1 `restore_visibility` with the LINKED session: it restores instancers, prev active layer collection and view layer), pop, select the instancer.
- `class IOPS_OT_instance_edit_commit`: poll = top session `kind == "LINKED"`; `invoke`: preflight (CANCELLED with report when not writable), `export_copy`, `run_worker(plan)`, fill `wm.iops_ie_shared` from `plan.shared` + `shared_users`, store the plan JSON on `self`, `invoke_props_dialog(width=520)`; `draw`: warning lines, counts of replaced/added/unlinked/deleted, the shared list with checkboxes; `execute`: backup copy (`shutil.copy2`), write json again with `update_shared` from the ticked rows and `expected_plan`, `run_worker(write)`; on failure report + CANCELLED (session stays); on success `bpy.data.libraries[session.library_name].reload()`, `cancel_linked`-style cleanup (without the "cancel" wording), report the backup path. `bl_options = {"REGISTER"}` (no UNDO: a file write cannot be undone; say so in the description).
- `class IOPS_OT_instance_edit_cancel`: poll as Commit; `execute` = `cancel_linked`.
- `class IOPS_OT_instance_edit_rollback_source`: `source_path: StringProperty`; poll = backup exists; copies the backup over the source after the same writable check, reloads the library, reports.
- Phase-1 `_SessionOperator.poll` unchanged (LOCAL only).

- [ ] **Step 1: Implement.**
- [ ] **Step 2: Headless verify** (throwaway script, scratchpad temp dir): source + editing file as in Task 3; Start; move `Cube`; add a new object; `bpy.ops.iops.instance_edit_commit('EXEC_DEFAULT')` after calling the operator's internals so the dialog is skipped (expose `commit_linked(context, session, update_shared) -> dict` used by `execute`, and call it directly); assert: backup exists, reopened source has the moved `Cube` and the new object inside `C`, `SharedMat` unchanged (kept), editing file has no `"C [edit]"`, stack empty, instancer visible, the linked collection now shows the moved `Cube`. Then the `source_changed` warning case (touch the source mtime between Start and preflight) and the failure case (make the worker fail by passing a wrong `expected_plan`) keeping the session.
- [ ] **Step 3: Commit** `feat(instance-edit): Commit with dry-run plan dialog, Cancel and Rollback`.

---

### Task 6: UI for linked sessions

**Files:**
- Modify: `ui/iops_instance_edit_header.py`, `ui/iops_pie_edit.py` (library branch: add "Edit Linked Instance" in the first free slot or replace the trailing `draw_open_asset_in_pie_if_poll` placement consistently with the local branch), `docs/operators/op_instance_edit.md` (Task 8 does the full docs; here only the tooltip strings)

**Interfaces:**
- Header: idle on a linked instancer → `LINKED` icon running `iops.instance_edit_start` (poll-gated), tooltip via the Start operator's `description` classmethod: "Edit linked collection <name> (writes back to <file> on Commit)"; LINKED session on top → red `LINKED` icon = Commit, `X` = Cancel, depth label `f"{len(sessions)}"` when > 1; `LOOP_BACK` Rollback button when a `.iops_bak.blend` exists for any `bpy.data.libraries` entry (cache the check per draw with a 2 s `time.monotonic()` throttle to avoid stat-ing files every redraw).

- [ ] **Step 1: Implement.**
- [ ] **Step 2: Headless verify**: with a LINKED session pushed, `IOPS_OT_instance_edit_commit.poll` True and `IOPS_OT_instance_edit_stop.poll` False; the header draw function runs without error against a dummy layout (reuse `test_header_pair_in_every_mode`'s approach).
- [ ] **Step 3: Commit** `feat(instance-edit): header and pie entries for linked sessions`.

---

### Task 7: Headless integration test for the linked flow

**Files:**
- Create: `tests/blender/test_instance_edit_linked.py` (same runner shape as `tests/blender/test_instance_edit.py`; builds its source files in a scratch temp dir and deletes them; never touches repo files)
- Modify: `tests/smoke_register.py` (add `instance_edit_commit`, `instance_edit_cancel`, `instance_edit_rollback_source`)

- [ ] **Step 1: Write the tests**: `test_start_places_copy_and_hides_only_instancer`, `test_start_unowns_nested_same_file_collection`, `test_start_refuses_second_session_on_same_collection`, `test_cancel_removes_copy_and_restores`, `test_commit_round_trip_untouched_is_exact` (no edits → source bytes may differ by header, but every object's channels are bit-equal and `SharedMat` untouched), `test_commit_moves_and_adds` (Task 5 Step 2 assertions), `test_commit_warns_when_source_changed`, `test_commit_failure_keeps_session`, `test_nested_sessions_commit_inner_then_outer` (outer `C` from `src.blend`, inner `D` from the same `src.blend`; inner commit changes `D`; outer commit writes `C` with the Empty still linking `D`; reopened source shows both), `test_rollback_restores_backup`.
- [ ] **Step 2: Run** headless → all PASS, exit 0; smoke OK; pytest green.
- [ ] **Step 3: Commit** `test(instance-edit): linked start/commit/cancel/rollback scenarios`.

---

### Task 8: Docs

**Files:**
- Modify: `docs/operators/op_instance_edit.md`, `docs/preferences.md`, `docs/ui/ui_menus.md`, `docs/ui/ui_pies.md`, `README.md`

- [ ] **Step 1:** Document the linked flow: Start on a linked instancer, what the `[edit]` copy is, Commit's plan dialog (what replaced/added/kept mean, shared datablocks unticked by default), backup and Rollback, Perforce behaviour and the two prefs, nested sessions (close inner first), what is not merged (concurrent edits of the same collection), the "do not edit animated objects" warning, temp files next to the source.
- [ ] **Step 2: Commit** `docs(instance-edit): linked collections, Commit, Rollback`.
