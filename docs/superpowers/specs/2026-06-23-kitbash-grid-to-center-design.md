# KitBash Grid — "to Center" mode

## Goal
Add a way to collapse all selected units (objects or whole collections) to the
world origin `(0,0,0)`, honoring the existing per-axis alignment options.

## Design
New `arrange_mode = 'CENTER'` on `IOPS_OT_KitBash_Grid`.

- `center_as_group` (bool, default on) selects between two behaviors:
  - **As Group**: the whole selection moves as one rigid unit — the combined
    bbox alignment point is shifted to origin by a single delta, preserving
    relative layout (matches collection-mode intuition for a group).
  - **Off**: every unit's own alignment point (`align_x/align_y/align_z`,
    min/center/max per axis) is moved to world origin `(0,0,0)` — units stack.
- Reuses `get_unit_bbox()` and `apply_unit_placement()`, so `operate_on`
  (OBJECTS vs COLLECTIONS) works unchanged; collections move as a single unit
  with shared-object dedup via `moved_objects`. The group path moves objects via
  `matrix_world.translation` so multiple collections shift by the same delta.
- No gaps, no cursors, no sorting effect.

### Alignment behavior
- `align Z = MIN` → all units sit on the Z=0 plane.
- all `CENTER` → bbox centers coincide at origin.
- `MAX` → top/right/front edges coincide.

### UI
- `draw()`: in CENTER mode hide irrelevant props (columns, primary axis,
  gaps, sort); keep Unit + Alignment.
- `invoke()`: grid-columns autocalc is already gated on `GRID`, so CENTER does
  not trigger it.
- Pie menu: add a dedicated **"to Center"** button that opens the same operator
  with `arrange_mode` preset to `'CENTER'`.

### Report
`"Centered N objects/collections to world origin."`
