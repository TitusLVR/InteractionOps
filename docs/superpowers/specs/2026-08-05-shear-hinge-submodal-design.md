# Shear Hinge Sub-Modal (Q) — Design

Date: 2026-08-05
Status: approved

## Goal

Add a hinge action to `iops.mesh_shear` on the **Q** key: rotate the
selected faces around the **active edge** (from `select_history`),
like `forgotten_tools` `mesh.hinge`, but interactive and integrated
into the shear modal chain.

## Selection model

- Geometry: all selected faces in `self.bm` (the real bmesh
  selection, not shear records — hinge needs no rails).
- Axis: the active `BMEdge` from `bm.select_history`. Center = edge
  midpoint, axis = normalized edge vector (object space).
- No active edge or no selected faces → `report({'INFO'})`, stay in
  shear, nothing changes.
- If all `link_faces` of the axis edge are selected (a "flap" being
  bent, not extruded off a body), deselect the edge and its verts
  before the confirm-time spin, mirroring forgotten hinge, so spin
  doesn't drag the hinge line itself.

## Interaction

Sub-modal in the style of `_extrude_active`:

- `_hinge_active` flag + `_hinge_data` dict; `_modal` routes to
  `_hinge_modal` while active.
- **Angle: numeric only** — digits / `.` / `-` / Backspace using the
  same `input_str` pattern as shear. No mouse-drag angle.
- **Ctrl + wheel**: segment count (steps), clamped 1..64.
- **D**: flip angle sign.
- **A**: raycast face under cursor (reuse `_raycast_face_under_cursor`
  + the transient-BVH pattern from `_toggle_align_highlight`); set the
  angle to the signed angle that makes the hinged selection's plane
  coplanar ("flush") with the picked face's plane, rotating about the
  hinge axis.
- **Enter / Space**: confirm (see below).
- **Esc / RMB**: restore original vert coords, exit back to shear.

## Rotation mechanics

- Live preview is pure math: on Q entry capture `orig_cos` for all
  verts of the selected faces; each angle change restores and applies
  `Matrix.Rotation(angle, 4, axis)` about the edge midpoint. No
  geometry is created during preview.
- Segments are applied **once at confirm**: restore `orig_cos`, run
  `bmesh.ops.spin(geom=selected faces(+edges+verts), cent, axis,
  angle, steps=N, use_merge=False)`, then
  `bmesh.ops.remove_doubles` on the last-step verts with a fixed
  merge distance (~0.001), using forgotten hinge's
  `prepare_doubles`-style neighbor walk (or a simpler radius gather of
  affected verts).
- After the spin, select the resulting cap geometry (`geom_last`,
  filtered by `is_valid`) so the user continues on the moved faces.

## Confirm → back to shear

Like `_confirm_extrude`: after spin + merge, rebuild shear records on
the resulting cap faces (principal-axis default). If rebuilding fails
(no rails etc.), finish the operator cleanly with `undo_push` +
`{'FINISHED'}` instead of leaving a broken shear state.

## Drawing

- Ghost outlines of the original face positions (same 0.45-gray as
  shear ghosts).
- Current rotated outlines via `Role.ACTIVE_LINE`.
- Hinge axis drawn along the edge via `Role.LOCKED_LINE` (amber).
- Arc indicator around the edge midpoint in the plane perpendicular
  to the axis, radius from the selection's max distance to the axis
  (scaled down), with tick marks at each segment boundary
  (`steps` ticks), so angle and steps are readable at a glance.
- HUD: "Hinge" section in the help overlay; status text shows angle,
  steps, and key hints.

## Undo / safety

- All inside the already-running shear modal; the single
  `ed.undo_push("Shear")` at shear confirm covers hinge too.
- The existing `ReferenceError` wrapper in `modal()` covers the hinge
  branch.
- `_finish` clears `_hinge_active` / `_hinge_data` alongside the
  other sub-modal state.

## Out of scope (parked)

- R "unfold to neighbor plane" (dihedral snap) — separate follow-up.
- Mouse-drag angle control.
- Per-invoke merge-distance UI.
