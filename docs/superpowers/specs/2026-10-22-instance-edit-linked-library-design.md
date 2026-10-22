# Instance Edit, Phase 2: Linked Collections with Write-Back — Design

Date: 2026-10-22
Status: approved 2026-10-22 (builder-checked against Blender 5.2)
Builds on: `2026-10-22-instance-collection-edit-in-place-design.md` (phase 1).

## Purpose

Phase 1 edits a *local* collection where one of its instances stands.
Phase 2 does the same for a collection **linked from another .blend**, and
on **Commit** writes the edited collection back into that source file, so
every file linking it sees the change after a library reload.

Source files are arbitrary production files: many assets, many collections,
possibly scenes, possibly under Perforce, possibly linked by other people
at the same time. The write-back therefore has to be a **surgical merge of
one collection**, never a whole-file overwrite, with a dry run the user
confirms before anything is written.

## Scope

In scope
- Start / Commit / Cancel on an instancer Empty whose `instance_collection`
  comes from a library.
- Nested sessions: a linked collection may contain instancers of other
  linked collections; each level is its own session writing to its own file.
- Perforce-friendly behaviour: read-only source → `p4 edit` attempt; never
  silently clear the read-only bit.

Non-goals
- Merging *concurrent* edits of the same collection by two people. The
  last Commit wins over the collection; the dry run and the "source changed
  since Start" warning make that visible, they do not resolve it.
- Library overrides as the editing mechanism. The local copy approach is
  used instead because overrides cannot be written back to the source file.
- Editing anything in the source file other than what came in through the
  session (see "owned set").

Anti-goals
- Touching, renaming or deleting anything in the source file that the
  session does not own.
- Writing the source file without a backup, or without the user seeing the
  merge plan.
- Leaving a half-written source file. Blender writes to a temp and renames,
  and the merge script saves exactly once, at its very end.

## Behaviour

### Start — `iops.instance_edit_start` (same operator, linked branch)

Poll (linked branch): Object Mode; active object is an instancer Empty whose
`instance_collection.library` is not None; the library file exists on disk;
no *local-phase* session is open on this scene (linked sessions may nest,
see Session stack).

Steps:
1. Record the source file path (absolute), its mtime and size, and the
   collection name in the library (`collection.name`, library-relative).
2. Warn if the current file holds a library override of this collection
   (it may break on the post-Commit reload) and if any root of the
   collection has transform animation / drivers / constraints (phase 1
   rule: proceed, warn, user's responsibility).
3. **Append** the collection from the source file (`bpy.data.libraries.load
   (path, link=False)`), with every dependency Blender pulls in. Record the
   **owned set**: every ID that arrived through this append, of every type
   (objects, meshes, materials, images, node groups, actions, child
   collections, the collection itself), as rows of
   `(id_type, source_name, local_name)`. `local_name` may carry a `.001`
   suffix when the current file already had something of that name; the
   row is how Commit gets the source name back.
   Verified in Blender 5.2: `link=False` makes a **local copy of every ID
   reachable from the collection inside the source file**, including
   nested collections that instancers inside it point at. Nothing from the
   source file arrives as a link; only IDs from *other* libraries stay
   linked. Hence the post-append fix-up below.
3b. **Nested same-file collections are not owned.** For every instancer
   Empty in the appended subtree whose `instance_collection` is an appended
   copy of a collection that is *also still linked* from the source in the
   current file (or can be linked on demand): re-point the Empty at the
   linked collection, remove the copied sub-collection and every ID only it
   used, and drop those IDs from the owned set. The session then owns
   exactly the collection the user opened; a nested instancer is an
   ordinary linked instancer and gets its own LINKED session (writing to
   the same source file) if the user wants to edit it. This is the author's
   call: it keeps every Commit surgical, one collection per session.
4. Link the appended collection under the scene root collection, name it
   `<name> [edit]` locally (so it never collides with the linked one in the
   outliner), and apply phase 1's placement: edit frame `A = M_instance @
   Translation(-instance_offset)`, roots moved by `matrix_world = A @
   matrix_world`.
5. Hide the instancer (view-layer `hide_set`). **Do not hide other
   instancers** of this collection: they keep showing the unchanged linked
   data, which is correct until the library is reloaded.
6. Set `view_layer.active_layer_collection` to the copy collection
   (record the previous one) so objects the user adds land inside the
   edited collection by default. Push the session onto the stack (see
   Storage). Select the copy, make the first root active.

### Commit — `iops.instance_edit_commit`

Poll: top-of-stack session is a linked session. Drops to Object Mode.

1. **Preflight** (no mutation yet):
   - source file still exists; if its mtime/size differ from Start, add a
     "source changed since Start" line to the plan dialog (merge still runs
     on top of the current content, the warning is for the human);
   - source file writable? If read-only and the `iops_instance_edit_p4`
     preference is on: run `p4 edit <file>` (capture output). If still
     read-only: report the reason, leave the session open, return
     CANCELLED. The user checks the file out and presses Commit again.
2. **Export**: in the current file, for every owned root
   `matrix_world = inverse(A) @ matrix_world` (new roots included).
   **Tag** every owned ID with a transient custom property
   `id["iops_commit"] = <row index>`; this is the only matching key the
   worker uses, names are never matched (suffix shifts, a foreign source
   ID occupying a copy's name, the 63-byte name limit and leftovers from
   earlier runs all break name matching). Write
   the copy collection with `bpy.data.libraries.write(temp_blend,
   {collection}, path_remap='RELATIVE', fake_user=False)` where
   `temp_blend = <source dir>/<source stem>.iops_commit-<run id>.blend`
   (next to the source so relative paths of other libraries, caches and
   texts resolve identically; `RELATIVE` keeps them relative, the worker
   only relativises paths that were absolute because the editing file was
   unsaved). The run id is a per-Commit uuid so two Commits on one source
   never share temp files; an `O_EXCL` lock file `<source>.iops_lock`
   (stale after the worker timeout) serialises Commits on one source; write
   `<temp>.json` with the owned set (row index → `id_type`,
   `source_name`), the source collection name and the local collection
   name. Then, in the same operator, **strip** the tags from every owned ID
   and move the roots back with `A` (the user is still editing until the
   merge succeeds). The tag never survives the operator in the editing
   file, whatever happens later.
3. **Dry run**: run the merge worker (below) in plan mode. It returns the
   plan as JSON. Show it in a confirmation dialog: replaced / added /
   unlinked / deleted IDs, the "source changed" warning, Blender version of
   the source file if older than the running one. **Shared IDs** (owned
   IDs whose source original also has users outside `C`'s subtree: other
   assets' materials, meshes, node groups, images) are listed in their own
   block, each with an "update" checkbox and the names of the other users.
   Defaults: exclusive IDs are always updated (no checkbox); shared IDs
   default to **unchecked**, i.e. the source keeps its version and the
   session's copy is discarded. Touching another asset therefore takes an
   explicit tick in a dialog that shows who else uses the datablock. The
   ticked set goes to the worker as `update_shared: [(type, source_name)]`.
   **Sharing propagates to dependencies:** an ID is shared when any of its
   users is outside `C`'s subtree *or is itself shared* (iterated to a fixed
   point), so the mesh of a kept shared object, or the node group of a kept
   shared material, is kept too and no edit leaks into another asset
   without a tick. The dialog also lists **discarded** IDs: objects the user
   added inside a kept shared child collection (and anything else that
   would end up without users), so nothing is dropped silently; ticking the
   collection keeps them.
   Cancel = nothing written, session stays open.
4. **Write**: back up the source to `<source>.blend.iops_bak` (no `.blend`
   extension, so asset libraries and this addon's master-file detection
   never index it; one backup per source, overwritten) with a sidecar
   `<source>.blend.iops_bak.json` (backup time, post-write source stat,
   the committing session's uuid), then run the worker in write mode. A
   session carries a uuid from Start; Commit refuses a session whose uuid
   the sidecar already names ("this session was already committed; Cancel
   it"), which closes the Ctrl+Z-after-Commit double merge. A source saved
   by a **newer** Blender than the running one is refused (the worker
   would silently save the whole library down-version). The `p4 edit`
   output is shown in the dialog and a "must sync/resolve" answer refuses.
   The UI is blocked while the worker runs (wait cursor + status text; the
   docs say so). Non-zero
   exit or a plan/result mismatch → report, session stays open, source
   untouched (the worker saves only at its very end).
5. **Reload**: `library.reload()` for this source's Library datablock.
6. **Cleanup**: remove the copy collection and every owned ID that has no
   other users (a fake user counts as a user for IDs that existed before
   Start: the user's own local assets are never removed); delete the temp
   blend/json; unhide the instancer; pop the session; select the
   instancer. Report the backup path.

### Cancel — `iops.instance_edit_cancel` (linked sessions' "Restore")

Poll: top-of-stack session is a linked session. Same as Commit step 6
without reload, and never touches the source file.

### Rollback — `iops.instance_edit_rollback_source`

Copies `<source>.blend.iops_bak` over the source (after the same writable
check as Commit; via a temp file and `os.replace`, never in place) after an
explicit confirmation naming the backup time, and reloads the library. Available from the header while a
backup exists for any library of the current file. One level deep only.

### Session stack

`Scene.iops_instance_edit.sessions` is a CollectionProperty; the last item
is the active session. Phase 1 (local) sessions are items of kind `LOCAL`,
linked sessions are kind `LINKED`.

Rules:
- Only the top session can be Committed / Stopped / Cancelled / Restored.
  Buttons for deeper levels are disabled with the tooltip "Close the inner
  session first".
- A LOCAL session may be opened on top of a LINKED one (the copy contains
  a local sub-collection instancer) and a LINKED one on top of either.
- A LOCAL session blocks nothing beneath it except the LIFO rule.
- The header shows the top session's collection name and depth (`2/2`).

### Merge worker — `operators/instance_edit_merge_worker.py`

Run as `blender --background --factory-startup --disable-autoexec
<source.blend> --python merge_worker.py -- <temp.json> <plan|write>
<result.json>` through the same `subprocess` conventions as
`operators/library/common.py` (`worker_creation_flags`, timeout). It never
imports the addon.

Algorithm (both modes compute the plan; only `write` mutates and saves):

1. Load the json. Resolve the target collection `C` by source name; it must
   be local to the file. Record its parents: every `Collection.children`
   that contains it and every `Scene.collection` that contains it directly.
2. Append the copy collection from the temp blend (`link=False`). Track the
   appended IDs per type via `data_to`.
3. Matching pass. Appended IDs arrive with whatever suffix Blender gave
   them; that is irrelevant. For every `bpy.data` collection of IDs, every
   ID carrying `iops_commit` is an appended owned ID; `del id["iops_commit"]`
   and look up its row (`id_type`, `source_name`). Then:
   - `old = getattr(bpy.data, id_type).get(source_name)`, local to the
     file and not the appended ID itself. If `old` exists and (the ID is
     exclusive, or it is in `update_shared`): copy asset metadata when
     `old.asset_data` exists and `new.asset_data` is None (`asset_mark`,
     catalog id, description, author, copyright, license, tags, asset
     IDProperties: appending an already-linked collection drops them),
     then `old.user_remap(new)` (same ID type only, the call is a silent
     no-op across types), remove `old`, `new.name = source_name`. Record
     `replaced`, plus `shared` when `old` had users outside `C`'s subtree.
   - if `old` exists, the ID is shared and **not** in `update_shared`:
     `new.user_remap(old)`, remove `new`. The source keeps its version.
     Record `kept`.
   - if no `old`: `new.name = source_name`. Record `added`.
   Appended IDs without the tag were created by the user during the
   session: they keep whatever name Blender gave them; a collision with an
   existing source ID is resolved by Blender's suffix, never by
   replacement. Record `added` (with the final name, so the dialog shows a
   suffix if one was needed).
   After the pass, assert that no ID in the file still carries
   `iops_commit`; if one does, fail without saving.
4. Remove the `Library` datablock the append created for the temp blend
   (`bpy.data.libraries.remove`), otherwise the source would carry a
   dangling library pointing at a file we delete.
5. Membership: objects that were in the old `C` subtree and are not in the
   new one are already unlinked by the remap (old collection removed);
   those left without any collection and without other users are deleted,
   others are kept. Record `unlinked` / `deleted`.
6. Re-link the new `C` under every recorded parent (children / scene
   collections). Child collections of `C` were handled by the rename pass.
   Per-view-layer state is preserved: before the merge the worker records,
   for every scene and view layer, `exclude`, `hide_viewport`, `holdout`
   and `indirect_only` of the layer collections of `C` and its child
   collections (by source name) and the base hide state of the subtree's
   objects, and re-applies them after the relink (removing the old `C`
   discards its layer collections and bases; fresh ones carry default
   flags).
7. Path remap for appended images / libraries: `bpy.ops.file.make_paths_
   relative()` is file-wide, so instead set `filepath` relative only on the
   appended IDs (`bpy.path.relpath`).
8. Write `result.json` with the plan and `ok: true`. In `write` mode, after
   the plan is computed and matches the previous dry-run plan (same sets of
   names), set `preferences.filepaths.save_version = 0` (factory startup
   defaults to 1 and would drop a `.blend1` next to the source) and
   `bpy.ops.wm.save_mainfile()` once; then write the result. Any
   exception → result with `ok: false` and the traceback, no save.

The plan JSON is the contract between worker and operator and is covered
by pure tests (`utils/instance_edit_core.py` gains `merge_plan(...)`
operating on name/type tuples, no bpy).

### Guards

- Start refuses if the source file is already the subject of an open
  linked session in this scene (one session per source collection).
- Commit refuses while an inner session is open.
- If Blender is closed with a linked session open: on reopen the stack is
  still there, the copy collection too; the user Commits or Cancels. The
  temp blend/json from an interrupted Commit are regenerated, never
  reused.
- Worker timeout (configurable preference, default 300 s): report, session
  stays open.

## Storage

Phase 1's `IOPS_InstanceEdit_State` becomes the session item; the scene
property becomes:

```
Scene.iops_instance_edit : IOPS_InstanceEdit_Stack
  sessions   CollectionProperty(IOPS_InstanceEdit_Session)

IOPS_InstanceEdit_Session  (phase 1 fields, plus)
  kind              EnumProperty LOCAL | LINKED
  source_path       StringProperty  (absolute)
  source_mtime      FloatProperty
  source_size       IntProperty
  source_coll_name  StringProperty
  copy_collection   PointerProperty(Collection) + copy_collection_name
  owned             CollectionProperty(IOPS_InstanceEdit_OwnedRef)

IOPS_InstanceEdit_OwnedRef
  id_type           StringProperty  ("objects", "meshes", ...; the bpy.data attr)
  source_name       StringProperty
  local_name        StringProperty
  ref               PointerProperty(ID)
```

## Preferences

Next to `iops_ss_header`:
- `iops_instance_edit_header` (phase 1)
- `iops_instance_edit_p4` BoolProperty, default off: try `p4 edit` on a
  read-only source before Commit.
- `iops_instance_edit_worker_timeout` IntProperty, default 300.

## UI

Header block from phase 1, extended:
- Idle on a linked instancer: the collection icon with a link overlay
  (`LINKED`), tooltip "Edit linked collection <name> (writes back to
  <file> on Commit)".
- Linked session active: red `LINKED` icon = Commit (opens the plan
  dialog), `X` = Cancel, depth label when the stack is deeper than one.
- Rollback: `LOOP_BACK` icon shown while a `.blend.iops_bak` exists for
  any library of the current file; tooltip names the file.

Pie entry (phase 1) gains the linked branch automatically through the
shared operator.

## Pure core additions

`utils/instance_edit_core.py`:
- `merge_plan(owned_rows, tagged, untagged_added, existing_source_names,
  users_outside, update_shared)` → dict of `replaced / added / shared /
  kept / unlinked / deleted`; owned IDs are keyed by their tag index, never
  by name; every shared ID not in `update_shared` lands in `kept`.
- `plans_match(a, b)` for the dry-run vs write comparison, over
  `replaced / added / kept / unlinked / deleted / discarded`.
- `source_changed(recorded, current)` for the mtime/size check.

`tests/test_instance_edit_core.py` gains cases for: owned name with and
without collision, user-created name colliding with an existing source ID
(must be `added`, never `replaced`), shared ID detection, a tagged ID
whose source original was deleted meanwhile (`added`), plan equality
ignoring order.

## Edge cases decided

- Appended copy carries actions of animated objects; the user was warned
  not to touch them; they round-trip untouched.
- The user assigns a material linked from a *third* library to a copy
  object: `libraries.write` keeps it as a link; the merge appends the
  object with that link intact (paths are relative to the source dir
  because the temp file lives there). Verified in Blender 5.2.
- The worker never self-links: nothing from the source file stays linked
  after Start's append, so the temp blend holds only local copies plus
  third-library links.
- The source file links the edited collection from itself through an
  override or a scene instancer: handled by the parent re-link step, the
  instancers keep pointing at the renamed new `C`.
- Two instancers of the same linked collection selected: only the active
  one starts a session; the other keeps showing linked data.
- Source saved by an older Blender: the plan dialog says so; saving will
  upgrade the file format. The user decides.

## Left to the builder

- Exact dialog layout for the plan (a `template_list` with the shared
  block's checkboxes, or labels + a small CollectionProperty on the
  WindowManager).
- Whether the worker reuses `worker_session.py` or a one-shot
  `subprocess.run`; one-shot is enough.
- `p4 edit` invocation details (cwd = source dir, timeout 30 s).
