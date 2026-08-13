# Selection Sets

Named, persistent selections for both Edit Mode (vertices/edges/faces) and
Object Mode (objects). A set is saved once and recalled any time after —
through topology edits, undo, redo and file save/reload — without the user
having to re-select anything by hand.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.ss_new / ss_recall / ss_replace / ss_bool / ss_delete / ss_delete_all / ss_union / ss_difference / ss_refresh / ss_rename / ss_preview / ss_preview_all</span>
<span class="mode">Mode: Object, Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview

Selection Sets remember *which elements were selected*, not a
snapshot of the mesh at save time. In Edit Mode the membership is stored
directly on the mesh, as hidden integer attributes on the elements
themselves:

```
.iops_ss_<D>_<name>      D in {V, E, F}
```

The leading dot hides the attribute from the Attributes panel; the domain
letter (`V`/`E`/`F`) keeps names unique, since Blender's attribute names
share one namespace across domains. A set can span more than one domain at
once (e.g. a set saved while both vertex and edge select modes are active
writes both a `V` and an `E` attribute) — the UI shows one icon per domain
the set covers.

Because membership lives on the elements, **selection sets survive**:

- **Undo/redo** — the attributes are regular mesh data, so Blender's normal
  undo stack carries them along with everything else.
- **Topology edits** — deleting vertices/edges/faces just removes those
  elements from every set that referenced them; nothing needs to be
  rebuilt or re-validated by hand. A set that lost some or all of its
  members simply recalls fewer (or zero) elements.
- **File save/reload.**

In Object Mode there is no per-element data to hang a set on, so sets are
instead stored as a list on the scene (`Scene.iops_selection_sets`), each
entry holding the object names that belonged to it when saved. A dead
reference (the object was deleted or renamed) is kept, not silently
dropped — the count column flags it (see Stale Sets below) and the user
decides whether to re-save or delete the set.

Edit-mode sets and object-mode sets are **completely separate namespaces**:
a set created while in Edit Mode is invisible in the Object Mode list and
vice versa, and the operators poll against whichever mode is active.

## The Panel

`View3D > Sidebar (N) > iOps > iOps Selection Sets` shows a `UIList` of
every set visible in the current mode:

- A checkbox column for multi-select (used by Union/Difference, see below).
- The set's name, editable in place (double-click / click-to-rename);
  renaming write-throughs to the underlying attribute/scene-list rename,
  it isn't just a UI label.
- One icon per domain the set covers (vertex/edge/face), or an object icon
  for object-mode sets.
- A live element count — `count` for edit-mode sets, `alive/total` for
  object-mode sets.

Buttons alongside the list:

| Button | Operator | Action |
| --- | --- | --- |
| `+` | `iops.ss_new` | Save the current selection as a new set (auto-named, deduplicated) |
| `-` | `iops.ss_delete` | Delete the active set |
| Rename | `iops.ss_rename` | Rename the active set via a dialog (names dedup with `.001`) |
| Refresh | `iops.ss_refresh` | Force-rebuild the list from the mesh/scene (normally automatic) |
| Select Set | `iops.ss_recall` | Select the active set's elements |
| Replace | `iops.ss_replace` | Overwrite the active set with the current selection |
| Union → New / Union → Active | `iops.ss_union` | Merge the checked sets |
| Difference (checked) / Difference vs Selection | `iops.ss_difference` | See Union/Difference below |
| Delete All | `iops.ss_delete_all` | Remove every set visible in the current mode |

The list itself is a **UI-only mirror** rebuilt from the real data (mesh
attributes / scene collection); it refreshes on depsgraph updates, undo,
redo and file load, and immediately after any Selection Sets operator
runs. It never *stores* anything — deleting the addon's window-manager
mirror data loses nothing, since it's regenerated from the mesh/scene on
the next redraw.

## The Header Button

A single button sits mid-header in the 3D Viewport (next to the editor
menus), labeled with the **active set's name** (or "Sets" when none). It
tracks the last recalled set. Clicking it opens the full Selection Sets
panel as a popover — the same UIList and buttons as the sidebar panel,
without opening the sidebar.

Toggle the button on/off in **Preferences > Selection Sets in 3D View
Header** (`iops_ss_header`, on by default).

## Select Set

`iops.ss_recall` with its default `SET` action deselects everything else
first, then selects the set. On an Edit Mode set it also restores the
select mode the set was saved under — recall a face-domain set while in
vertex select mode and Blender switches back to face select mode as part
of the same operation, so the recalled faces show up highlighted rather
than only their corner vertices. Extend/subtract/intersect live on the
boolean-mode buttons below the list (no modifier keys involved).

## Boolean Modes (current selection vs the active set)

A labeled button column in the panel (`iops.ss_bool`) applies the active
set against the *current* selection, mirroring Blender's own select-tool
mode icons. By default the result becomes the selection; holding
<kbd>Shift</kbd> reverses the direction — the selection is applied to the
*set's stored content* instead (on the domains the set already stores):

| Icon | Mode | Default (→ selection) | Shift (→ set) |
| --- | --- | --- | --- |
| `SELECT_EXTEND` | Extend | Selection ∪ set | Set ∪= selection |
| `SELECT_SUBTRACT` | Subtract | Selection − set | Set −= selection |
| `SELECT_INTERSECT` | Intersect | Selection ∩ set | Set ∩= selection |
| `SELECT_DIFFERENCE` | Difference | Selection XOR set | Set XOR= selection |

Intersect expands set membership downward first — a member face counts
its edges and verts as members too — so intersecting a face-domain set
against a vertex selection keeps the face corners instead of nothing.

`iops.ss_union` (merge whole sets into a new/target set) remains
available via operator search for scripted use.

## Set Preview

Every list row carries an eye toggle (`HIDE_ON`/`HIDE_OFF`,
`iops.ss_preview`): it highlights that set's members in the viewport as
a GPU overlay drawn in the iOps theme's preview colors — verts as
points, edges as lines, faces as translucent fills; object-mode sets
show their objects' bounding boxes. The overlay changes no selection;
one set previews at a time, and clicking the open eye turns it off.

## Stale Sets

The count column doubles as a staleness indicator:

- **Edit Mode:** the mirror always sets `total` equal to the live `count`
  for edit-mode rows (there's no separate "count at save time" to compare
  against), so the warning icon only fires when `count` reaches `0` —
  complete loss of the set's members through topology edits. Partial loss
  (some but not all members deleted) is not flagged in Edit Mode; the set
  is still valid to recall either way, it just selects whatever remains.
  `iops.ss_new` itself refuses to save an empty selection (poll fails),
  but a set can still end up empty later through topology edits.
- **Object Mode:** shown as `alive/total` — `alive` counts references
  still present in the scene, `total` is the count at save time. A
  mismatch means one or more member objects were deleted or moved to
  another scene; the warning icon flags it the same way.

Neither case auto-deletes or auto-prunes the set — the user decides
whether to `Replace` it with a fresh selection or delete it outright.

## Notes

- Multi-object Edit Mode is supported: `iops.ss_new` / `ss_replace` /
  Shift-`ss_bool` write to every mesh currently in edit mode that has a
  selection, and `iops.ss_recall` applies to all of them; a set present on
  only one of several edited meshes recalls fine on that mesh and is a
  no-op on the others.
- Renaming a set from the panel dedupes against existing names the same
  way `iops.ss_new` does (`Name` → `Name.001` on collision).
- `iops.ss_delete_all` removes every set in the *current mode's*
  namespace only — object-mode sets are untouched while in Edit Mode and
  vice versa.
- The pure name/membership helpers (attribute naming, sanitizing, dedup,
  union/diff) live in `utils/selection_sets_core.py` and have no `bpy`
  dependency; they're unit-tested directly under
  `tests/test_selection_sets_core.py`.
- The data-mutating operators (`ss_new`, `ss_recall`, `ss_replace`,
  `ss_bool`, `ss_delete`, `ss_delete_all`, `ss_union`, `ss_difference`)
  use `bl_options = {"REGISTER", "UNDO"}`, so they integrate with
  Blender's normal undo stack like any other mesh edit. `iops.ss_refresh`
  only rebuilds the UI mirror and carries no `bl_options` — there's no
  mesh/scene data for it to push onto the undo stack.

## Related

- [Mesh Convert Selection](op_mesh_convert_selection.md)
- [Mouseover Fill Select](op_mouseover_fill_select.md)
