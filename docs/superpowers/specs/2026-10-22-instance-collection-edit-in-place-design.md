# Instance Collection Edit In Place — Design

Date: 2026-10-22
Status: approved 2026-10-22

## Purpose

Edit the objects of a collection *where one of its instances stands*.
Blender has no "edit instance in place": the originals live wherever the
source collection happens to be, often in a hidden or excluded collection
far from the instance the user is actually looking at.

The user selects an instancer Empty, presses **Edit Instance**, and the
original objects of that collection appear exactly where the instance was,
selected and ready to edit (transform, Edit Mode, modifiers, materials,
adding/removing objects). **Stop** puts the originals back; the geometry
changes stay and show up in every instance.

The scene is the user's production data. Every move the feature makes must
be reversible by a single **Restore** button, whatever state things ended
up in (crash, undo confusion, closed file, deleted instancer).

## Scope

In scope (this spec): collections local to the current file.

Out of scope, deferred to a follow-up spec:
- Collections linked from a library (write-back to the source .blend on
  Stop). Phase 1 refuses to start on them. Note for the follow-up: the
  "hide other instances" rule does **not** apply there, because the linked
  originals in the editing scene do not move until the library is saved and
  reloaded.
- Hotkeys.

## Goals / non-goals / anti-goals

Goals
- Originals appear at the instance's exact world transform (instance matrix
  and `instance_offset` both honoured).
- One-click Stop; one-click Restore that works from any state.
- Survives undo, file save/reopen mid-edit, deleting the instancer mid-edit.
- Zero impact on scenes where the feature is not used.

Non-goals
- No proxy/override system, no copies: the user edits the real objects.
- No per-user option for hiding the other instances: they are always
  hidden while editing (their content would visibly drift otherwise).

Anti-goals (failure even if it "works")
- Any object ending up somewhere other than where it started after
  Stop/Restore.
- Leaving the scene in the edit state with no visible way out.
- Touching objects outside the edited collection.

## Behaviour

### Start — `iops.instance_edit_start`

Poll (the button is simply inactive when any of these fails):
- Object Mode, active object is an Empty with `instance_type ==
  'COLLECTION'`;
- its `instance_collection` is local (`library is None`);
- no object of `instance_collection.all_objects` is linked from a library
  (their transforms are read-only, they cannot be moved in place);
- no edit session is currently recorded in the scene.

Warning (not a refusal): when any root of the collection has animation
data or drivers on its transform channels, or a transform constraint, Start
proceeds but reports a WARNING naming those objects: "Animated/driven/
constrained objects: do not edit them and do not change the frame while
editing, they will not stay in place". Blender re-evaluates animation on
frame change and drivers on every depsgraph update, so such objects can
snap back to the native frame mid-session; this is the user's
responsibility, the feature does not try to compensate. Restore still
writes their snapshot basis like any other object.

Steps, in order, snapshot first:

1. Build the **edit frame** `A = M_instance @ Translation(-instance_offset)`.
   `A` must be a **similarity transform** (rotation x uniform scale x
   translation, non-zero scale): a non-uniformly scaled or sheared
   instancer, or one under a non-uniformly scaled parent, turns rotated
   originals into sheared matrices that `matrix_world` cannot represent, and
   Stop would silently corrupt the asset. Start refuses such an instancer
   (poll message: "Instance is non-uniformly scaled or sheared; edit a
   uniformly scaled instance"); a zero-scale instancer is refused the same
   way.
2. Collect `targets = collection.all_objects` (recursive: nested child
   collections are part of the instance's content). Split into **roots**
   (no ancestor, through any parent chain, is in `targets`) and children.
   A target reached through a non-target parent that itself hangs under a
   target is a child: moving it again would double the move.
3. Write the **snapshot** to `Scene.iops_instance_edit` (see Storage)
   *before any mutation*. Nothing is touched until the snapshot is complete.
4. Hide (view-layer `hide_set(True)`) the instancer itself and every other
   object in the scene with `instance_type == 'COLLECTION'` whose
   `instance_collection` is this collection **or any collection that
   contains it** (`children_recursive`): an instance of a parent collection
   would otherwise show the edited content drifting. Record each one's
   previous `hide_get()`. Instancers not in the current view layer are
   skipped (nothing to hide).
5. Make the source collection visible: if it is not reachable in the
   current scene's hierarchy, link it under the scene root collection and
   record that; find its `LayerCollection`(s) **and all their descendants**,
   record and clear `exclude` and `hide_viewport`; for the **ancestor**
   layer collections of each occurrence record and clear `hide_viewport`
   only (a hidden parent hides its children; an excluded parent is already
   mirrored onto the child's own `exclude`, and clearing the parent's
   exclude would reveal every sibling asset); record and clear
   `Collection.hide_viewport` and `hide_select` for it, its ancestors in
   the scene tree and its descendants; record and clear `hide_get()` /
   `hide_viewport` / `hide_select` on each target object (locked asset
   collections are common; "selected and ready to edit" must hold for them
   too).
6. For every **root**: `obj.matrix_world = A @ obj.matrix_world`. Children
   are not touched; they follow their parent. Roots whose parent lies
   outside the collection are also moved through `matrix_world` (the setter
   accounts for the parent).
7. Set `view_layer.active_layer_collection` to the edited collection's
   layer collection (record the previous one; Stop/Restore put it back) so
   objects the user adds with Shift+A land inside the collection, i.e.
   inside the asset. Deselect all, select all targets, make the first root
   active.

Operator is `REGISTER | UNDO`, so a plain Ctrl+Z after Start reverts both
the objects and the snapshot together.

### Stop — `iops.instance_edit_stop`

Poll: a session is recorded. If the user is in Edit Mode (or any non-Object
mode), switch to Object Mode first.

Stop **keeps every edit** the user made, transforms included. It does not
reset anything to the snapshot:

1. Every object in `collection.all_objects` that is a root *now* (snapshot
   roots and objects added during the session alike) goes back to the
   collection frame. A snapshot root whose parent is unchanged and whose
   `matrix_basis` still equals the post-Start basis (within 1e-6) was not
   edited: it gets its **snapshot channels written back verbatim**
   (`location`, `rotation_mode` + the matching rotation channel, `scale`),
   so an untouched object survives any number of Start/Stop cycles bit
   for bit, with its Euler values and negative scale untouched. Every other
   root gets `matrix_world = inverse(A) @ matrix_world` (its channels are
   re-derived from the matrix, which is unavoidable for an edited object).
   Children are not touched. An object moved by the user while editing
   therefore keeps its new place relative to the collection, and an added
   object lands in the collection's native frame; both show correctly in
   every instance.
   If the collection itself no longer exists, the alive snapshot roots are
   moved back the same way (edits kept) and the collection is reported.
2. Objects the user unlinked from the collection during the session are
   accepted silently: they are no longer in `all_objects`, so they are not
   transformed and not restored. (The snapshot pointer keeps them alive in
   `bpy.data` until the session is cleared.)
3. Call the shared **unhide** routine: everything the visibility part of
   Restore does (layer collections, collections, object and instancer
   visibility, unlinking the collection if Start linked it), then clear the
   session. Object visibility is restored only for snapshot objects that
   are still in the collection; an object the user moved elsewhere keeps
   whatever state it has now (step 2).
4. Select the instancer and make it active, if it still exists.

Stop and Restore share the visibility/cleanup routine, so that part of the
emergency path is exercised by every normal Stop. The transform part
differs on purpose: Stop preserves edits, Restore discards them.

### Restore — `iops.instance_edit_restore`

Poll: a session is recorded. Also drops to Object Mode first.

The emergency exit. It does not compute anything from the current state;
it puts things back exactly as the snapshot says. **Transform edits made
during the session are discarded** by Restore (geometry, modifier and
material edits are on the data and stay). The tooltip says so.

- For every snapshot object still alive: first its parent relation
  (`parent`, `parent_type`, `parent_bone`, `matrix_parent_inverse`), then
  its **transform channels** from the snapshot (`location`, `rotation_mode`,
  rotation channel, `scale`), never a decomposed matrix, so the result does
  not depend on processing order, on a stale depsgraph, or on matrix
  decomposition. Then restore its `hide_get` / `hide_viewport` /
  `hide_select`.
- Restore `exclude` / `hide_viewport` of the recorded layer collections and
  `hide_viewport` of the recorded collections; unlink the collection from
  the scene root if Start linked it.
- Restore `hide_get` of every recorded instancer (the edited one and the
  siblings).
- Objects named in the snapshot that no longer exist (or whose pointer is
  dead) are skipped and listed in the operator report.
- Objects in the collection that are not in the snapshot are left alone.
- Finally clear the snapshot. The snapshot is cleared **only** after the
  routine ran to completion; an exception leaves it in place so Restore can
  be pressed again.

### Guards

- Start refuses while a session exists (message: "Instance edit in
  progress: Stop or Restore first").
- Opening a file that carries a session: the header shows the red
  collection icon plus Stop and Restore (see UI), so the way out is always
  visible.
- Instancer deleted mid-edit: Stop/Restore still work from the stored
  matrices; Stop simply skips re-selecting it.
- Object renamed mid-edit: the pointer still resolves (see Storage).
- Object deleted mid-edit: skipped with a report line.
- Collection deleted mid-edit: Restore still restores the objects it can
  find by pointer and clears the session.

## Storage

`bpy.types.Scene.iops_instance_edit`: `PointerProperty` to
`IOPS_InstanceEdit_Stack`, whose `sessions` CollectionProperty holds
`IOPS_InstanceEdit_State` items; the last item is the active session.
Phase 1 only ever holds zero or one item (Start refuses while one exists),
but the container is a stack from day one because phase 2
(`2026-10-22-instance-edit-linked-library-design.md`) nests linked and
local sessions. Lives in the scene, so it is saved with the .blend and
participates in undo.

```
IOPS_InstanceEdit_State
  active            BoolProperty
  instancer         PointerProperty(Object)      + instancer_name StringProperty
  collection        PointerProperty(Collection)  + collection_name
  frame             FloatVectorProperty(size=16)  # A, row-major
  view_layer_name   StringProperty
  linked_to_scene   BoolProperty   # Start linked the collection under scene root
  objects           CollectionProperty(IOPS_InstanceEdit_ObjRef)
  instancers        CollectionProperty(IOPS_InstanceEdit_InstRef)
  layer_colls       CollectionProperty(IOPS_InstanceEdit_LayerRef)
  colls             CollectionProperty(IOPS_InstanceEdit_CollRef)

IOPS_InstanceEdit_ObjRef
  ref               PointerProperty(Object)
  name              StringProperty          # report text
  is_root           BoolProperty
  basis             FloatVectorProperty(size=16)   # pre-Start matrix_basis
  edit_basis        FloatVectorProperty(size=16)   # post-Start matrix_basis (roots)
  location          FloatVectorProperty(size=3)
  rotation_mode     StringProperty
  rotation_euler    FloatVectorProperty(size=3)
  rotation_quaternion FloatVectorProperty(size=4)
  rotation_axis_angle FloatVectorProperty(size=4)
  scale             FloatVectorProperty(size=3)
  parent            PointerProperty(Object)
  parent_type       StringProperty
  parent_bone       StringProperty
  matrix_parent_inverse FloatVectorProperty(size=16)
  hide_get          BoolProperty
  hide_viewport     BoolProperty
  hide_select       BoolProperty

IOPS_InstanceEdit_InstRef
  ref, name, hide_get

IOPS_InstanceEdit_LayerRef
  path              StringProperty   # names from the view layer root, joined
  ref               PointerProperty(Collection)  # fallback when a rename broke the path
  exclude, hide_viewport   BoolProperty

IOPS_InstanceEdit_CollRef
  ref (Collection), name, hide_viewport, hide_select

(Implementation names: `IOPS_IE_*`; the stack length replaces `active`;
`kind` and `prev_active_layer_path` are additional fields.)
```

Pointer properties to IDs in a PropertyGroup hold a user, so an object the
user "deletes" while editing stays in `bpy.data` and Restore can still put
it back; it just becomes unlinked from its collections (reported). Names
are kept as a fallback and for messages.

Lookup rule: use `ref`; when it is None the object was really deleted
(renames never break pointers), so skip + report. There is **no name
fallback**: a name match could only ever hit a different object that took
the name, and touching it would violate the anti-goal. The same holds for
the session collection. Layer rows resolve by path, then by their
collection `ref`.

## Pure core (testable without Blender)

`utils/instance_edit_core.py`, no `bpy`, numpy only (matches the existing
`tests/test_*_core.py` pattern):

- `edit_frame(instance_matrix, instance_offset) -> 4x4`
- `moved(frame, world) -> 4x4` (Start) and `unmoved(frame, world) -> 4x4` (Stop)
- `split_roots(names, parent_of) -> (roots, children)` where `parent_of`
  maps name -> parent name or None; a root is an object whose parent is
  None or outside the set.
- `layer_path(names_from_root) -> str` / `split_layer_path(str)`.
- `plan_restore(snapshot_rows, alive_names) -> (to_restore, missing)` so the
  "skip + report" bookkeeping is unit-tested.
- `warnings(roots_info) -> [lines]` where each root row carries
  `has_transform_anim`, `has_transform_constraint`; returns the warning
  lines (empty when nothing to warn about).

`tests/test_instance_edit_core.py` covers: frame with non-zero offset and
rotation/scale; round-trip `unmoved(moved(x)) == x`; root splitting with a
parent outside the collection and with chains inside; missing-object plan.

## UI

**3D View header**, appended to `VIEW3D_MT_editor_menus` right after the
Selection Sets block (same mechanism as `draw_iops_ss_header`; the draw
function is appended after the Selection Sets one so it lands to its right).
The idle button is shown in Object Mode and Edit Mode; the session pair
(red icon + Restore) is drawn in **every** mode, because it is the only way
out and Stop/Restore switch to Object Mode themselves. Gated by a new addon preference
`iops_instance_edit_header` (default on), next to `iops_ss_header`.

- **Idle**: one icon button, `OUTLINER_COLLECTION`, runs
  `iops.instance_edit_start`; greyed out when the poll fails (no instancer
  Empty active, or linked collection).
- **Session active**: the same slot shows the collection icon **red**
  (`row.alert = True`, `depress=True`) and runs `iops.instance_edit_stop`;
  its tooltip reads "Stop editing <collection> (instanced by <instancer>)".
  Next to it a `RECOVER_LAST` icon button runs `iops.instance_edit_restore`.
  The red icon is the only persistent signal that the scene is in the edit
  state, so it is drawn whenever the session is recorded, regardless of
  what is selected and regardless of the preference toggle (the toggle only
  hides the idle button).

**Pie** (`ui/iops_pie_edit.py`, the branch for instancer Empties): add an
"Edit Instance" entry too, so the feature is reachable from where Expand /
Make Real already live. Slot: builder's call.

No N-panel.

## Registration

Following the Selection Sets pattern in `__init__.py`: the PropertyGroups
register before `Scene.iops_instance_edit` is assigned; the pointer is
deleted on unregister; the header draw function is appended/removed next to
the Selection Sets one.

## Edge cases decided

- Nested collection instances inside the edited collection are ordinary
  objects of `all_objects`: they move with the roots.
- Child collections of the edited collection: their objects are targets
  (`all_objects`), their layer collections are un-excluded/un-hidden by
  Start and put back by Restore/Stop.
- The edited collection being a child of another instanced collection:
  instancers of the ancestors are hidden too (Start step 4).
- If step 5 or 6 raises (unexpected read-only data), Start calls the
  Restore routine itself before re-raising, so the scene never stays
  half-moved.
- Objects shared by several collections (also linked elsewhere) are moved
  too; this is visible in their other places during the edit and comes
  back on Stop. Acceptable; documented in the tooltip.
- The source collection is excluded in the view layer: Start clears
  `exclude`; objects then exist in the view layer so `hide_set` works.
  Order of operations in Start is fixed: layer/collection visibility first,
  object visibility second, transforms last.
- Several view layers: Start records the name of `context.view_layer`;
  Stop/Restore act on that view layer (resolved by name on the scene), not
  on whatever is current, so switching view layers mid-session cannot write
  visibility into the wrong layer. If it no longer exists they fall back to
  the current one and report it.
- Multiple instances selected: only the active one is edited.
- Multiple scenes: the session is per scene; Stop/Restore act on the scene
  that holds the snapshot.

## Left to the builder

- Exact pie slot.
- Report wording.
- Whether `hide_set` on instancers needs `context.view_layer.update()`
  before the transform step (verify in Blender).
