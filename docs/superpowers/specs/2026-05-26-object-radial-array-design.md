# Object Radial Array

Date: 2026-05-26
Operator: `iops.object_radial_array` ([operators/object_radial_array.py](../../../operators/object_radial_array.py)) — new file.

## Goal

A modal operator that radially distributes copies of selected object(s) — including parent/child hierarchies and groups — around a pivot. Supports linked instances and full duplicates, full-circle and arc layouts (including arc defined by active→selected), configurable rotation axis and orientation, and a live GPU preview using the `iops_theme` palette. No real objects are created until the user applies; cancel leaves the scene untouched.

## Selection model

On `invoke()` resolve sources and pivot:

- **Pivot mode** (`pivot_mode`, cycles with `P`):
  - `ACTIVE` (default): pivot = `context.active_object.matrix_world.translation`.
  - `CURSOR`: pivot = `scene.cursor.location`.
  - `LAST_SELECTED`: pivot = last entry of `context.selected_objects` that is not the active.
- **Sources** = selected objects minus the pivot object (cursor mode: all selected).
- Each source carries its **full descendant tree** (`obj.children_recursive`). Relative transforms inside the tree are captured once at start (`local_matrices = [child.matrix_world.inverted() @ root.matrix_world for child in subtree]`-style relative offsets) and reapplied to every clone instance so parenting and group layout are preserved.
- Cancel conditions in `invoke()`:
  - No active object or area not VIEW_3D → `CANCELLED` with warning.
  - Sources list empty → `CANCELLED` with "Select at least one source object besides the pivot".

## Clone type

- `clone_mode` (toggle with `I`):
  - `DUPLICATE` (default): each clone is a deep copy. Root and every descendant get `obj.copy()` + `obj.data = obj.data.copy()`.
  - `INSTANCE`: linked-instance — `obj.copy()` only, `obj.data` shared with original. Modifiers and constraints follow Blender's `obj.copy()` semantics (referenced, not duplicated; same as Alt+D).
- Cloned subtree links into the **first user collection** of the corresponding source root. Additionally, every clone produced by the modal is linked into a working collection `_RadialArray_<sourceRootName>` created on apply (used so the user can grab the result quickly; not used for preview since preview creates no real objects).
- Parenting inside each clone subtree is rebuilt so that the clone-root is the parent and clone-children parent to it with `matrix_parent_inverse` matching the original.

## Arc / angle modes

`arc_mode` cycles with `A`:

- `FULL_360`: `step = 2π / count`. Source occupies index 0; clones occupy indices 1..count-1.
- `ARC_ANGLE`: explicit angle (`arc_angle`, radians). Step depends on `end_inclusive` (toggled with `E`):
  - inclusive: `step = arc_angle / (count - 1)`, clones at indices 1..count-1.
  - exclusive: `step = arc_angle / count`, clones at indices 1..count-1 (final position not occupied).
- `ARC_TWO_POINTS`: angle derived from second pivot-side reference object.
  - Requires `len(sources) >= 2` (cursor pivot) or `len(selected) >= 2` besides pivot (active/last-selected pivot).
  - The first source is the "start"; an `end target` is the last-selected non-pivot non-start object.
  - `arc_angle = signed_angle(start_vec, end_vec, axis)` where each vec is the projection of `(obj.matrix_world.translation - pivot)` onto the plane perpendicular to `rotation_axis`. Sign follows right-hand rule around `rotation_axis`.
  - Count distributes clones of the **start source only** between start and end positions (others are ignored as sources in this mode — they're geometry references). `end_inclusive` toggle applies the same way as `ARC_ANGLE`.

`count` (min 2, max 1024):

- `NUMPAD_PLUS` / `EQUAL` / wheel-up — increment.
- `NUMPAD_MINUS` / `MINUS` / wheel-down — decrement.
- `Shift` + wheel — step 1 (fine); plain wheel — step 1 too; `Ctrl` + wheel — step 10.

`arc_angle` in `ARC_ANGLE`:

- Numeric digit input (`0..9`, `.`, `BACKSPACE`) edits `arc_angle_input_string`. Commits on each digit.
- Drag mode: hold `G` then move mouse — angle tracks horizontal mouse delta (1 px = 0.5°). `Ctrl` snaps to 5°, `Ctrl+Shift` snaps to 15°.

## Axis & orientation

`axis_source` cycles via direct keys (each press sets the source and exits any pending pick):

- `X` / `Y` / `Z` — global axis (default `Z`).
- `L` — toggle global ↔ **local axis of pivot object** (for `CURSOR` pivot this toggle is a no-op; HUD shows "n/a").
- `V` — axis from **current view direction**: `region_3d.view_rotation @ Vector((0, 0, -1))`.
- `N` — enter **face-pick** mode. Next `LMB` does a raycast (`scene.ray_cast`) under cursor; if it hits, axis = world-space face normal. `Esc` while pending cancels the pick and reverts to previous axis.

Pivot point (for axis origin) always = the resolved pivot from "Selection model"; axis direction is the resolved `rotation_axis`.

`align_to_radius` (toggle `R`, default OFF): when ON, each clone is additionally rotated so its local **+X** points radially outward from the pivot in the rotation plane (the user-facing label is "Face outward"). When OFF, clones keep the source's original world orientation, only translated by the radial rotation.

## Count + tweaks

- `O` — toggle `skip_first` (in `FULL_360`: omit a clone at angle 0, useful when the source itself stays in place). Default OFF.
- `S` — toggle `start_offset_enabled`; when ON, a starting angle is applied to all clones (digit input feeds `start_offset_input_string` while `S` is the active numeric channel).

A single numeric input channel is active at a time. `G` → angle, `S` → start offset. The HUD shows which channel is active.

## Preview (GPU ghost)

No real objects exist during modal. A `POST_VIEW` draw handler renders, for each predicted clone of each source root subtree:

- **Wireframe ghost** of every mesh in the subtree, using each mesh's edge list batched once at start. The batch is drawn with the clone's world matrix as the model matrix (computed CPU-side; we pass positions in object-local space and a per-draw matrix via a uniform — or precompute world positions if simpler — pick the simpler approach in implementation).
- For non-mesh children (empties, lights, curves) — draw a small axis cross at the clone position.

In addition, draw once per frame:

- **Rotation axis** as a line through pivot, length = `2 * max(source_radius)`.
- **Rotation plane circle/arc**: a polyline circle/arc in the plane perpendicular to the axis, radius = distance from pivot to first source root, centered at pivot.
- **Pivot marker**: small 3D cross at pivot.
- **Arc fill**: semi-transparent triangle fan covering the active arc range (only in `ARC_ANGLE` / `ARC_TWO_POINTS`).

All colors pulled from `iops_theme`:

- Ghost wires: `iops_theme.preview_color` (existing) at full alpha.
- Axis line: `iops_theme.axis_color` (existing in theme).
- Circle/arc outline: `iops_theme.guide_color`.
- Pivot marker: `iops_theme.pivot_color` (add to theme if missing — see "Theme additions" below).
- Arc fill: same as guide color with alpha 0.15.

A `_dirty` flag is set whenever any parameter changes; ghost batches are rebuilt only then. Per-frame draws (axis/circle/pivot/arc-fill) are cheap and rebuilt every redraw.

### Theme additions

If `iops_theme` does not already have `axis_color`, `guide_color`, `pivot_color`, add them in the theme prefs panel under the existing HUD shared-style section. Reuse existing keys if equivalent names already exist (verify in `ui/draw/theme.py` during implementation).

## HUD / Help

Build `HUDOverlay("object_radial_array")` and `HelpOverlay("object_radial_array")` following the pattern in [easy_mod_array.py](../../../operators/easy_mod_array.py):

HUDParams (always-on):

- Pivot mode (Active / Cursor / Last-Selected)
- Clone type (Duplicate / Instance)
- Arc mode (Full 360 / Arc Angle / Arc 2-Points)
- Axis source (X / Y / Z / Local / View / Normal)
- Align to radius (on/off)
- Skip first (on/off)
- End inclusive (on/off, only meaningful in Arc Angle / 2-Points)
- Count (int)
- Angle (deg, only in Arc Angle)
- Start offset (deg, only when enabled)

Help section enumerates all keys above plus `LMB/Enter/Space` apply and `Esc/RMB` cancel and `H` toggle help.

## Apply / Cancel

- Apply (`LMB`, `ENTER`, `SPACE`):
  1. Remove GPU handler.
  2. For each source root subtree, for each clone index `i in 1..count-1` (and `0` if `skip_first` is OFF and we're not in modes that keep the source in place):
     - Compute rotation matrix `R = Matrix.Rotation(start_offset + i * step, 4, rotation_axis_local_to_pivot)`.
     - Compose pivot transform: `M_clone_root = T(pivot) @ R @ T(-pivot) @ M_source_root` (in world); apply `align_to_radius` extra rotation if enabled.
     - Duplicate or instance subtree per `clone_mode`. Apply `M_clone_root` to clone root; descendants follow via parenting (their original relative transforms come along automatically).
     - Link into source's primary collection and into `_RadialArray_<sourceRootName>` collection.
  3. Select all created roots; active = first new clone root. Return `{"FINISHED"}`.
- Cancel (`ESC`, `RMB`): remove GPU handler, return `{"CANCELLED"}`. Nothing in the scene was created.

## Edge cases

- Source == pivot object: skip with HUD-flash warning, do not create clones from it.
- Cursor pivot coincides with a source origin (distance < 1e-6): allow but show "Pivot coincident with source — clones overlap" hint.
- `align_to_radius` with `radius == 0`: undefined direction; fall back to source orientation.
- `ARC_TWO_POINTS` start and end project to the same direction (angle ≈ 0 or ≈ 2π): treat as full circle (`arc_angle = 2π`).
- `ARC_TWO_POINTS` with only one selected object besides pivot: HUD warning, behave as `ARC_ANGLE` until a valid end target appears.
- Mesh data ghost build for a mesh with 0 verts: skip mesh, no batch.
- Subtree with hidden children: included in ghost and clone (visibility preserved per object).

## File / registration

- New file: [operators/object_radial_array.py](../../../operators/object_radial_array.py).
- Register `IOPS_OT_Object_Radial_Array` in the addon's operator registration list (find via `__init__.py` / `operators/__init__.py` during implementation).
- Add a default keymap entry in the addon's keymap registration (verify location during implementation; keep behind preferences if the addon does so for other modal ops).

## Out of scope

- No "apply as modifier stack" path (Blender lacks a true radial-array modifier; geometry-nodes generators are out of scope here).
- No on-curve distribution (that's covered by `iops.modifier_easy_array_curve`).
- No nested/recursive radial arrays.
