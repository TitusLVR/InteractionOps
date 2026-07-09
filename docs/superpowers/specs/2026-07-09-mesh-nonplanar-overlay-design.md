# Non-Planar Faces Overlay — Design

**Date:** 2026-07-09
**Status:** Approved

## Purpose

Edit-mesh overlay mode that highlights non-planar faces in real time.
Fixing a face (making it planar) removes its highlight on the next
redraw. Helps users chase down warped quads/ngons while modeling.

## Operator & Lifecycle

- `IOPS_OT_mesh_nonplanar_overlay`, `bl_idname = "iops.mesh_nonplanar_overlay"`.
- Non-modal **toggle**: first call enables the overlay, second call
  disables it. No event capture, no modal loop.
- Module-level state: one POST_VIEW draw-handler handle (registered via
  `ui.draw.safe_handler_add`) plus the geometry cache.
- **Sticky**: the handler persists across object switches and mode
  switches. The draw callback simply draws nothing unless the active
  object is a mesh in edit mode.
- Addon `unregister()` removes the handler and clears module state —
  touches only this addon's handlers (hotkey-system rule).
- `poll`: active object is a mesh in edit mode (required only to
  *enable*; disable works from anywhere the operator can run).

## Detection

- Scope: **active object only**.
- Triangles are always planar — skipped.
- For each quad/ngon: compute the angle between each corner's triangle
  normal (`v_prev, v, v_next`) and the face normal (`f.normal`). The
  face's **deviation** is the max such angle. Deviation > threshold →
  non-planar.
- Threshold: `nonplanar_angle` FloatProperty on addon preferences,
  in degrees, default `0.5`, min `0.001`, max `90`. Exposed in the
  addon-preferences UI following the existing section pattern
  (like `cursor_bisect_coplanar_angle`).

## Draw

- POST_VIEW handler in the 3D viewport, world-space triangles.
- Non-planar faces get a semi-transparent fill:
  - Hue: a single color from the iOps theme (Danger/Warning-style
    red-orange role; exact role picked from the existing theme roles at
    implementation time, with a hardcoded fallback constant).
  - **Intensity shading**: per-face alpha scales with deviation.
    Linear ramp from α ≈ 0.15 at the threshold to α ≈ 0.6 at 15°
    deviation, clamped above 15°. The ceiling is a fixed constant
    (not a pref) so the read is consistent across meshes.
  - Alpha is baked per-vertex into the batch, so intensity costs
    nothing at draw time.
- Fill verts are offset along the face normal by ~0.002 to avoid
  z-fighting (same technique as Visual UV).
- Ngon fills are tessellated with `mathutils.geometry.tessellate_polygon`
  (handles concave ngons).

## Cache & Invalidation

- The draw callback redraws a prebuilt GPU batch — orbit/pan/zoom
  redraws do no bmesh work.
- A dirty flag forces a lazy rebuild (inside the draw callback, from
  `bmesh.from_edit_mesh`) when set by:
  - `depsgraph_update_post` — fires on every edit-mesh change, which is
    what makes the highlight vanish in real time when a face becomes
    planar;
  - `undo_post` / `redo_post`;
  - threshold pref change;
  - active-object change (detected by comparing a stored object pointer
    in the draw callback).
- App handlers are registered while the mode is on and removed when it
  is toggled off / addon unregisters.

## Feedback

- Small viewport corner label while the mode is on: `Non-Planar: N`
  (N = current non-planar face count). Confirms the mode is active even
  when the count is 0.
- Toggle-on reports the initial count via `self.report`.

## Files

- `operators/mesh_nonplanar_overlay.py` — new; operator, detection,
  draw, cache.
- `prefs/addon_preferences.py` — `nonplanar_angle` property + UI row.
- `prefs/iops_prefs.py` — default entry for the new pref.
- Operator registration list (wherever operators are collected).
- `docs/operators/op_mesh_nonplanar_overlay.md` — user docs.

## Error Handling

- Draw callback wrapped by `safe_handler_add`'s ReferenceError guard;
  additionally, any exception during rebuild clears the batch and draws
  nothing rather than raising every redraw.
- `bmesh.from_edit_mesh` is only touched when in edit mode with a valid
  mesh; otherwise the callback returns early.

## Testing

- Unit-style checks (headless Blender via the B:\test harness pattern):
  detection math on known-planar and known-warped quads/ngons across
  thresholds; triangle skip; count correctness.
- Manual: toggle on cube (0 highlights), move one vert of a quad
  (highlight appears, alpha grows with deviation), flatten it
  (highlight disappears), undo/redo, object switch, mode switch,
  toggle off, addon reload.
