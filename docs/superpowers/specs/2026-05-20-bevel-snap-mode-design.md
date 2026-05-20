# Bevel snap-point mode for Cursor Bisect

Date: 2026-05-20
Operator: `iops.cursor_bisect` ([operators/mesh_cursor_bisect.py](../../../operators/mesh_cursor_bisect.py))

## Goal

Add a second snap-point-generating mode alongside the existing **Inset (V)**. Where Inset places snap points along the *active edge* offset from its endpoints, **Bevel (B)** places snap points along the **resulting cut line**, offset perpendicular to it within the face plane. Snapping to those points shifts the next bisect cut parallel to the current preview — two such cuts produce a classic bevel.

## Behavior

- New key `B` (PRESS, no modifiers) toggles `self.bevel_active`.
- On activation:
  - Force-enable snap (`self.snapping_enabled = True`).
  - Seed `self.inset_input_string` from `self.inset_distance_bu` if empty.
  - Call `calculate_bevel_points()` immediately.
- On deactivation: clear `self.bevel_points`.
- Inset and Bevel are **independent** — either, both, or neither can be on. Snap points from both modes are appended to `self.snap_points`.
- Numeric input (`0-9`, `.`, `BACK_SPACE`) is captured when **either** mode is active and writes to the shared `self.inset_input_string` / `self.inset_distance_bu`. Both `calculate_inset_points()` and `calculate_bevel_points()` are re-run on each digit, gated by their respective `_active` flags.

## Geometry — `calculate_bevel_points`

Computes two snap points offset perpendicular to the cut line, in the face plane, at ±`inset_distance_bu` from the cursor position.

```
face_normal_world = (obj.matrix_world.to_3x3() @ face.normal).normalized()
axis              = Vector((1,0,0)) if normal_axis == 'X' else Vector((0,1,0))
rotation          = locked_rotation if lock_orientation else cursor.matrix.to_quaternion()
plane_no_world    = rotation @ axis        # bisect plane normal in world

# in-face direction perpendicular to the cut line:
perp_world = plane_no_world - face_normal_world * plane_no_world.dot(face_normal_world)
if perp_world.length < EPSILON: bail   # cut plane parallel to face — degenerate
perp_world.normalize()

cursor_world = context.scene.cursor.location
pt_world_a   = cursor_world + perp_world * inset_distance_bu
pt_world_b   = cursor_world - perp_world * inset_distance_bu

obj_inv = obj.matrix_world.inverted()
self.bevel_points = [
    ('bevel', obj_inv @ pt_world_a),
    ('bevel', obj_inv @ pt_world_b),
]
```

Bail conditions (return without modifying `self.bevel_points = []` set at top):
- not `bevel_active`
- not `hit_obj` / `hit_face_index < 0`
- `inset_distance_bu <= EPSILON`
- `perp_world.length < EPSILON` (cut plane parallel to face)
- any `IndexError`/`AttributeError`/`ReferenceError` from bmesh access

## State

New instance attributes:
- `self.bevel_active: bool = False`
- `self.bevel_points: list[tuple[str, Vector]] = []`

Save/load via `save_load_space_data` PropertyGroup:
- `cursor_bisect_bevel_active: BoolProperty(default=False)`

## Snap integration

In `update_snapping` (where inset points are extended onto `self.snap_points`):

```python
if self.inset_active:
    self.calculate_inset_points()
    self.snap_points.extend(self.inset_points)
if self.bevel_active:
    self.calculate_bevel_points()
    self.snap_points.extend(self.bevel_points)
```

## Modal handling

In `modal()`, replace the inset-only numeric-input gate:

```python
if (self.inset_active or self.bevel_active) and event.value == 'PRESS':
    if self._handle_inset_input(context, event):
        return {'RUNNING_MODAL'}
```

Inside `_handle_inset_input`, after `_update_inset_distance`:

```python
if self.inset_active:
    self.calculate_inset_points()
if self.bevel_active:
    self.calculate_bevel_points()
```

Add B toggle next to the existing V toggle:

```python
elif event.type == 'B' and event.value == 'PRESS' \
        and not (event.shift or event.ctrl or event.alt):
    self.bevel_active = not self.bevel_active
    if self.bevel_active:
        self.snapping_enabled = True
        if not self.inset_input_string:
            scale, _ = self._bu_to_display_units(context)
            self.inset_input_string = self._fmt(self.inset_distance_bu * scale)
        self.calculate_bevel_points()
    else:
        self.bevel_points = []
    self._sync_hud_state()
    self.update_status_bar(context)
    context.area.tag_redraw()
    return {'RUNNING_MODAL'}
```

## HUD / Help / Status

- `_build_hud` — add `HUDItem("Bevel Points", "B", state, default_state=ItemState.OFF)` next to the existing Inset Points item.
- `_sync_hud_state` — add `s("B", ItemState.ON if self.bevel_active else ItemState.OFF)`.
- `_sync_hud_header` — after the inset header line, when `self.bevel_active`, append `f"Bevel {val}{unit}"` using the shared `inset_distance_bu` value.
- `update_status_bar` — add `[B] Bevel({on/off})` block in the status string, by analogy with `[V] Inset(...)`.

## Drawing

In `draw_callback`, after the inset-points draw block, add an identical block for `self.bevel_points`. Same primitive style and role as inset for the first iteration — if a distinct color is wanted later, a new theme role can be introduced without changing this geometry code.

## Edge cases

- Points may fall outside the face — that's fine; they remain valid snap targets.
- `lock_orientation` is transparently handled because `rotation` already reads `locked_rotation` when locked.
- `fill_cut_mode` and `mark_edges_active` do not interact with bevel — bevel only contributes to `snap_points`.
- When B is toggled off while its value was the active inset_input source, the input string remains valid for V; we never clear it on B-off.

## Non-goals

- Independent distance values for V and B.
- A distinct draw style / theme color for bevel points (deferred).
- Auto-execution of two parallel cuts. User performs each cut manually by snapping.
