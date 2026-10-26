# Cursor Bisect — Delimiter and Cursor-Plane Axis — Design

**Date:** 2026-10-26
**Status:** Approved in chat (2026-10-26)

## Intent

Cursor Bisect today cuts either the selected faces or *every* visible
face of every selected edit-mode object. On a kitbashed or multi-part
mesh that is almost never what the user wants: the plane through one
panel also slices every other panel it happens to cross. The user has to
pre-select faces by hand (RMB / Shift+RMB) to contain the cut.

Two additions:

1. **Delimiter.** A toggle that confines the cut to the piece of mesh
   under the mouse. The walk from the hit face stops at a boundary of the
   chosen type (disconnected mesh, UV seam, sharp edge, UV island edge,
   material change, normal angle). Faces beyond the boundary are left
   untouched even where the plane crosses them.
2. **Cursor-plane axis (Z).** A third choice for the cut normal next to
   the cursor's X and Y: the cursor's Z. Because the cursor is aligned to
   the face under the mouse, this cuts in the plane of that face. With the
   orientation locked (A) the user can carry that plane to another part of
   the mesh and slice it there.

Both work together: hover a face, lock its plane, hover a different
island with the delimiter on, click, and only that island is cut. The
delimiter is a filter on whatever the operator would cut anyway: the
selected faces when there is a selection, every visible face otherwise.

## Goals

- Cut only the island under the mouse when the delimiter is on, for
  every cut kind the operator already has (single, bevel pair, fill cut).
- Boundary types the user can cycle through without leaving the modal.
- Cut in the plane of the hovered face by cycling the existing axis key.
- Preview lines show exactly the faces that will be cut.
- Settings persist between invocations like the other toggles.

## Non-goals

- Cutting with the plane of the *active* (selected) face. Discussed and
  dropped: the cursor already carries the hovered face's plane.
- Changing how face selection works. A selection still limits the cut;
  the delimiter only filters further inside it (see Rules below).
- Any change to Cursor Bisect's snapping, inset, bevel distances or HUD
  layout beyond the new entries.

## Anti-goals

- A delimiter that silently cuts more than the island under the mouse
  (e.g. because of a missed boundary type) is worse than no delimiter.
- A Z-axis cut that also tries to run Inset / Bevel / Fill Cut logic that
  only makes sense for a plane perpendicular to the face: that produces
  garbage. Those features are disabled in Z, not approximated.

## User-facing behaviour

### Delimiter

| Key | Action |
| --- | --- |
| <kbd>L</kbd> | Delimiter on / off |
| <kbd>Shift</kbd>+<kbd>L</kbd> | Cycle delimiter type |

Types, in cycle order, with the rule for "this edge is a boundary":

| Type | Edge is a boundary when |
| --- | --- |
| Mesh Island | never; only a disconnected mesh (or a hidden face) stops the walk |
| Seam | the edge is marked seam |
| Sharp | the edge is marked sharp |
| UV Island | the UV coordinates of the two faces' loops differ across the edge (no UV layer: treated like Mesh Island) |
| Material | the two faces have different `material_index` |
| Normal | the angle between the two face normals exceeds the *Delimit Angle* preference |

Default type: Mesh Island. Default state: off.

**Rules for which faces get cut** (per edit object). The delimiter is a
*filter*: it never adds faces, it only narrows the set the operator would
cut anyway.

1. Candidate set: the selected visible faces of this object if any are
   selected, otherwise all visible faces (today's behaviour, no cap).
2. Delimiter off → cut the candidate set.
3. Delimiter on and the hit face belongs to this object and is in the
   candidate set → cut the faces reached from the hit face by walking
   shared edges that are not boundaries, **never leaving the candidate
   set**. Hidden faces are never entered. So with a selection, the walk
   runs inside the selection; without one, inside the whole visible mesh.
4. Delimiter on otherwise (not the hit object, or the hit face is not
   selected while a selection exists) → this object is not cut.

If after the loop nothing was cut at all and the delimiter is on, report
`Delimiter: no face under the cursor` (or `Delimiter: face under the
cursor is not selected` when the hit face exists but was filtered out by
rule 4).

**Which face is "under the mouse".** The face tracked on mouse move
(`hit_obj` / `hit_face_index`), the same one the preview uses. LMB does
not raycast again, so preview and cut always start from the same face.
Today that tracked face is never cleared when the ray misses (hold-snap
relies on it staying), so the builder adds a separate hover-valid flag
set on a hit and cleared on a miss; the delimiter only uses the tracked
face while that flag is set, so a stale face cannot drive a cut after the
mouse left the mesh. The 8-corner fallback
raycast is not used for the delimiter: a click beside the mesh must not
resolve to an island at the edge of the viewport.

The delimiter applies to every cut the operator performs: the single
plane, both planes of Bevel mode, and every plane of Fill Cut.

**Preview.** With the delimiter on, the LINES preview is computed over the
same face set the cut will use (the walk result), replacing the
depth-limited connectivity walk used today, so preview and cut always
agree. The *Preview Depth* and *Fallback Limit* preferences keep
governing the preview only when the delimiter is off. The island walk is
**not capped**: it is bounded by the island itself, and a partial cut
would violate the anti-goal above. (Today the limit only ever applied to
the preview; the cut was never capped.) To keep mouse-move cheap, the walk
result is cached and recomputed only when the hit face, the delimiter
state or type, the face selection (RMB / Shift+RMB / Z) or the mesh
changes (a cut invalidates it).

**Status / HUD.** Status bar gains `[L] Delimit(ON Seam)` style text. HUD
gains two items: `Delimiter` on `L` (ON/OFF) and `Delimit Type` on
`Shift+L`; the HUD header shows the current type while the delimiter is
on, like it shows the mark type while M is on.

### Cursor-plane axis

<kbd>X</kbd> now cycles the cut normal **X → Y → Z** over the cursor's
axes (today it alternates X / Y). Z means the cut plane is the cursor's
XY plane: with the cursor aligned to the hovered face, that is the face's
own plane. Snapping still positions the cursor; the plane passes through
the snapped point.

In Z mode:

- The hovered face is coplanar with the cut and is not split by
  `bisect_plane`; neighbouring faces crossing the plane are.
- **Inset (V), Bevel (B) and Fill Cut (F) are unavailable.** They are built
  on "the cut line across the hovered face", which does not exist when the
  plane *is* the face. Switching to Z turns them off; pressing their keys
  while in Z reports `Not available with Z axis` and does nothing. Their
  HUD items show as disabled.
- The plane preview (P) draws the cursor's XY square. The lines preview
  works unchanged (plane ∩ faces).
- World align (W) aligns the cursor's Z to the chosen world axis, the same
  way it aligns X or Y today.
- Alt+Wheel rotation keeps rotating about the same axis it does today
  (the builder confirms which cursor axis that is and keeps it; the user
  did not ask for a change).

The distance info (I) along the edge is still shown; it describes the
cursor position on the edge, which is still meaningful.

### Persistence

New scene props next to the existing `cursor_bisect_*` ones:
`cursor_bisect_delimit` (bool), `cursor_bisect_delimit_type` (enum, the
six types above). `cursor_bisect_normal_axis` gains the `Z` item. New
addon preference `cursor_bisect_delimit_angle` (float, degrees, default
30°, 0–180) shown in the Cursor Bisect preferences block next to the
coplanar angle, and included in the prefs JSON save/load like the others.

## Constraints

- Edit-mode bmesh only (`bmesh.from_edit_mesh`), as the operator does
  today. Face indices from the raycast refer to the evaluated mesh; the
  operator already assumes they match the edit bmesh, keep that.
- The walk runs on every mouse move when the delimiter is on (for the
  preview). It must be cheap: O(faces in island) with plain Python sets.
  No per-move rebuild of lookup tables beyond `ensure_lookup_table`.
- The island walk is pure logic and goes into a bpy-free module
  (`utils/cursor_bisect_core.py`), following the repo's `*_core.py`
  pattern, so it is pytest-covered (`tests/test_cursor_bisect_core.py`).
  The operator feeds it adjacency and boundary predicates built from the
  bmesh.
- Keep the existing undo push per cut.
- Docs: update `docs/operators/op_mesh_cursor_bisect.md` (controls table,
  a short *Delimiter* section, the X key description) and the Cursor
  Bisect line in `docs/preferences.md` for the new angle preference.

## Decided

- Keys: L / Shift+L (both free in the modal). X cycles three axes rather
  than adding a new key.
- Delimiter is a filter on top of the candidate set (selection if any,
  else all visible faces); it never widens the cut.
- Island walk starts from the hover-tracked face, which is reset on a
  ray miss; no click-time raycast and no corner fallback for the delimiter.
- Island walk is uncapped; *Fallback Limit* stays a preview-only setting
  for the delimiter-off case.
- Multi-object: each object is handled by the rules above independently.
  With the delimiter on only the hit object is ever cut, island-walked
  inside its own candidate set; every other object is left alone.
- Delimiter type list and defaults as in the table. Normal angle is its
  own preference, not the coplanar-select angle (5° is too tight for a
  "stop at hard corners" boundary).
- Z disables Inset / Bevel / Fill Cut instead of adapting them.

## Left to the builder

- Exact HUD wording and ordering of the two new items.
- How the UV Island boundary test is written (compare loop UVs on both
  sides with a small epsilon; the builder picks the epsilon).
- How the cached walk result is invalidated after a cut (the existing
  int-layer snapshot pattern is a good fit for island membership across
  the two bevel planes / the fill-cut planes).
