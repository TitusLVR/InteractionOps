# iOps Selection Sets — Design

Date: 2026-08-04
Status: approved

## Purpose

Save and recall named selections — verts/edges/faces in Edit Mode, objects in
Object Mode. Unlimited set count, boolean operations between sets and the
current selection, UIList panel + 3D View header integration.

## Prior art

`forgotten_tools/selection_sets` stores sets as bit masks packed into three
shared int attribute layers (max 30 sets) and encodes per-set metadata (select
mode, mask index) as a hex string in the layer *name*, because edit-mode undo
rolls back mesh data layers (including names) but not ID custom properties.
That makes it undo-safe and topology-robust, at the cost of: no set names, a
30-set cap, no UIList, edit-mode only.

We keep the core insight (persist membership *on the elements themselves*, put
metadata in the attribute name) and drop the bit-packing hack.

## Storage

### Edit Mode — attributes on the mesh (source of truth)

One hidden int attribute **per set per domain**, named:

```
.iops_ss_<D>_<name>        D in {V, E, F}
```

- Leading dot hides the attribute from the Attributes panel.
- One attribute per domain the set covers (Mesh attribute names share a
  single namespace across domains, so the domain letter is part of the
  name). The set's select mode is derived from which domain attributes
  exist — no separate metadata.
- `<name>` is the user-facing set name. Duplicate names get an auto `.001`
  suffix. Name length is bounded by Blender's attribute-name limit
  (~48 chars usable after the prefix).
- int (0/1) rather than bool layers — bmesh int layers are supported
  everywhere; forgotten_tools uses the same.

Properties: survives edit-mode undo (attributes are in the undo stack),
survives file save, degrades gracefully on topology change (deleted elements
simply leave the set; membership never goes stale like index lists do).

Elements may belong to any number of sets simultaneously (one bool layer
each). No set-count limit. Cost: 1 byte per element per domain per set.

### Object Mode — collection on the scene

`Scene.iops_selection_sets`: CollectionProperty of PropertyGroups, each with
`name: StringProperty` and a nested collection of object names.

Dead references (object deleted/renamed) are skipped silently on recall; the
UI shows an alive/total counter (e.g. `5/7`) when some objects are missing.

### UIList mirror (UI only, never persisted)

A CollectionProperty on `WindowManager` rebuilt from the source of truth
(mesh attributes of all meshes in edit, or the scene list) on every panel
draw. After undo the mirror resyncs automatically — UIList never fights the
undo stack. The mirror row carries: name, domain flags, element/object count,
a participation checkbox (for union/difference), and a "stale" indicator.

Multi-object edit: the mirror shows the union of set names across all meshes
in edit mode. Recall selects on every mesh that has the set; save writes a
layer on every mesh that has a selection.

## Operations

Context-sensitive: Edit Mode operates on elements per `mesh_select_mode`,
Object Mode on objects. Same operator set for both.

| Op | Behavior |
|----|----------|
| New Set | Save current selection as a new set (auto name `Set.001`, rename via UIList double-click) |
| Recall | Replace selection with set contents; restore the set's select mode. **Shift** = extend selection, **Ctrl** = subtract from selection |
| Replace | Overwrite set contents with current selection (re-captures select mode) |
| Add to Set | Add current selection to an existing set |
| Remove from Set | Remove current selection from an existing set |
| Union | Merge checked sets into a new set or into the active set |
| Difference | Between two checked sets, or between current selection and the active set → result becomes the selection |
| Delete / Delete All | Remove set attribute(s) / all `.iops_ss_*` attributes |

Recall converts set elements into the current select mode when they differ
(vert→edge→face homogenization, same semantics as forgotten_tools'
`homogenize_with_mode`). Hidden elements are never selected by recall.

## UI

### Panel

`iOps Selection Sets` — N-panel in VIEW_3D, category `iOps`, visible in both
Object and Edit mode with context-dependent content:

- `template_list` UIList: name (editable), domain icons (V/E/F) or object
  icon, element/object count, participation checkbox, warning icon for empty
  (count 0) or partially dead sets.
- Side column: New, Delete, Refresh. Sets are listed sorted by name —
  a persistent manual order has nowhere undo-safe to live in the
  attribute-name scheme, so reorder arrows are deliberately out (YAGNI).
- Bottom row(s): Recall / Replace / Add / Remove / Union / Difference /
  Delete All.

### Header

`VIEW3D_HT_header` append: dropdown menu listing sets (click = recall;
tooltip documents Shift/Ctrl modifiers) plus compact buttons: New, Add to,
Remove from, Replace. Hidden when the addon preference toggle is off
(toggle lives in iOps prefs).

## Errors and edge cases

- Set emptied by topology edits → row stays, count `0`, warning icon; the
  user decides to delete or re-save. Detection = the simple guard: missing
  elements/objects are just absent, nothing dangles.
- Recall of a set missing on some meshes in multi-edit → select where it
  exists, no error.
- Duplicate name on the same mesh → auto `.001` suffix.
- Non-mesh objects in edit mode → operators poll False.

## Module layout

- `utils/selection_sets_core.py` — pure, bpy-free helpers (attribute-name
  encode/decode, name sanitize/dedup, membership algebra); pytest target,
  same convention as `utils/smart_inset_core.py`.
- `operators/mesh_selection_sets.py` — bmesh/scene backend + operators +
  scene PropertyGroups.
- `ui/iops_selection_sets_panel.py` — Panel, UIList, header draw fn,
  WindowManager mirror PropertyGroups, resync app handlers (panel draw
  callbacks cannot write to ID data, so the mirror is rebuilt from
  depsgraph/undo/redo handlers, not in draw).
- Registration wired in root `__init__.py` alongside existing panels.

## Testing

- pytest (no bpy): attribute-name encode/decode round-trip, flag parsing,
  name sanitization/dedup, union/difference set algebra on plain index sets.
- MCP smoke in live Blender: create sets in both modes, edit topology, undo,
  recall/extend/subtract, union/difference, multi-object edit, header menu.
