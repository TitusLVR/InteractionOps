# Visual UV — Interactive Preview Modes — Design

**Date:** 2026-09-08
**Status:** Draft

## Problem

Visual UV (`iops.mesh_visual_uv`) has two kinds of actions. The transforms
(G / R / S, handle drags) are interactive: the result follows the mouse,
LMB commits, RMB restores. Everything else fires immediately on the key
press: Align (A), Match dimensions (D), Straighten (T), Randomize (N), and
texel density matching (two blind clicks). The user cannot see what will
happen before it happens, and a wrong guess costs an undo step.

Stitch (E) was recently built as a third pattern: a pick state, then a
live-drag state wired ad hoc through `_modal_transform`. Adding more
interactive actions this way means one more bespoke state per key.

## Goal

One interaction model for every non-transform action:

1. Press the key — the operator enters a **preview mode** for that action.
2. Move the mouse — the target under the cursor (island, edge, handle,
   edge chain) is highlighted and the action is applied **live** to the
   mesh as a preview.
3. **LMB / Enter** commits the preview (one undo step) and returns to
   IDLE. The modal keeps running.
4. **RMB / Esc** restores the pre-preview UVs and returns to IDLE.
5. Pressing the same key again while in its mode cancels it.

Transforms are not touched: G / R / S and the handle drags keep their
current code and behaviour.

## Framework

A single new state `STATE_PREVIEW` replaces the per-action pick states
(`ALIGN_EDGE`, `DENSITY_REF`, `DENSITY_TGT`, `STITCH_SRC`,
`STITCH_DRAG`). The active action is `self.preview_mode`, one of the
mode objects below.

```
class PreviewMode:
    key: str                      # hotkey that starts / cancels it
    label: str                    # HUD text
    def begin(op, context) -> bool          # may refuse (nothing to act on)
    def pick(op, context, mx, my, event)    # find + store target, return truthy if found
    def apply(op, context, event)           # act on op.bm from the restored state
    def on_click(op, context, event)        # 'COMMIT' | 'CONTINUE' | 'IGNORE'
    def draw_3d(op, context)                # highlight target
    def hud_text(op) -> str
```

Operator plumbing, shared by every mode:

- `_begin_preview(mode)`: calls `mode.begin`; on success snapshots
  `pre_drag_cache = cache_all_uvs(...)`, sets `state = STATE_PREVIEW`,
  runs one `_tick_preview` so the preview is visible before the first
  mouse move.
- `_tick_preview(context, event)`: `restore_uvs(pre_drag_cache)` →
  `mode.pick(...)` → if a target exists `mode.apply(...)` →
  `_update_mesh_live`. Runs on MOUSEMOVE and on Shift / Ctrl press or
  release so modifier-driven variants update without moving the mouse.
- Commit: `undo_stack.append(pre_drag_cache)`, `redo_stack.clear()`,
  `_update_mesh`, back to IDLE. Nothing else to do — the mesh already
  holds the previewed result.
- Cancel: `restore_uvs(pre_drag_cache)`, `_update_mesh`, IDLE.
- `MOUSEMOVE`, `MIDDLEMOUSE` and wheel navigation pass through exactly as
  in the transform states so the user can orbit while previewing.
- `draw_3d_callback` calls `mode.draw_3d` when in `STATE_PREVIEW`; the
  clean-view gate hides island fills only, never the preview highlight.
- HUD header shows `[Preview: <label>]`; `_draw_transform_feedback`
  shows `mode.hud_text`.

LMB in `STATE_PREVIEW` is routed to `mode.on_click(...)`. Single-pick
modes return `'COMMIT'` whenever a target is under the cursor and
`'IGNORE'` otherwise. Modes that need **two picks** (stitch: source edge,
then target) return `'CONTINUE'` on the first click, store the pick, and
`'COMMIT'` on the second.

The modes live in a new module `operators/visual_uv_modes.py`; the
operator file only keeps the framework and the transforms. Pure math that
does not need `bpy` goes to `utils/*_core.py` and gets pytest coverage,
following `uv_stitch_core.py`.

## Modes

### E — Stitch (existing behaviour, moved onto the framework)

- Step 1: hover highlights an edge of any session island; LMB picks it as
  the source and makes its island active.
- Step 2: the island follows the mouse, snapping its source edge to the
  nearest edge of any other island (session or unselected, the pool built
  in step 1). Shift held = same side. LMB commits.
- No behaviour change; `_build_stitch_pool`, `_project_stitch_pool`,
  `_nearest_pool_edge` move into the mode object as is.

### T — Straighten chain

- Target: the **UV edge chain** through the hovered edge of the hovered
  island. The chain walk is fixed at the same time:
  - it extends from both ends only through UV vertices of valence 2
    (a boundary or a quad-strip seam); it stops at any vertex with 3+
    UV edges or when it returns to the start (closed loop → no
    straightening, the mode reports and shows nothing);
  - every loop sharing a chain UV point is moved, not just the first one
    found, so interior chains no longer tear the island.
- Preview: chain drawn as `PREVIEW_LINE`, endpoints as handles; the
  straightened result is applied live. Ctrl held = keep the original
  spacing ratios instead of equal spacing (matches the Z-ops Line Up
  semantics).
- LMB commits.

### A — Align

- Hovering a **handle** of the active island previews the current handle
  alignment: the scope targets (see I) minus the active island are
  bbox-aligned to that handle's line. Hovering an **edge** previews the
  hovered island rotated so the edge becomes axis-aligned (the existing
  `align_island_to_edge_uv`).
- The two sub-behaviours already exist; they are only re-plumbed so the
  result is visible before the click. LMB commits, no change of active
  island on edge alignment unless the hovered island differs (then it
  becomes active, as today).

### D — Match dimensions

- Target: the hovered island is the **reference**. Scope targets other
  than it are resized to its dimensions (`match_island_dimensions`).
  Hovering nothing shows the restored state.
- Shift held = match width only, Ctrl held = height only (drops out of
  the current uniform behaviour; both off = current behaviour).

### M — Match texel density (replaces the two-click flow)

- Target: hovered island is the reference; scope targets other than it
  get its texel density (`match_texel_density`). Hovering nothing shows
  the restored state. LMB commits.
- Key: `M` is free (`Y` is avoided because it is the axis lock inside
  the transforms); the old density state constants go away.

### N — Randomize

- On enter, one roll is applied and shown. Wheel up / down re-rolls.
  Shift / Ctrl select U-only / V-only as today, evaluated on every tick.
- LMB commits the roll currently shown.

### Stays immediate

F (flip — binary), U (unwrap), C / P (cursor, pivot), Q / V (view), I
(scope), Tab (active island), Ctrl+Z / Ctrl+Shift+Z.

## Undo

A committed preview is exactly one undo step (the pre-preview snapshot).
A cancelled preview leaves the undo stack untouched. Ctrl+Z during a
preview is ignored (as in the transform states).

## Drawing and HUD

- Only the mode's own highlight is added in `STATE_PREVIEW`; the generic
  hover edge is not drawn on top of it (avoids two colours on one edge).
- Help overlay rows stay per key; the label text is updated to name the
  preview (`"Straighten chain (preview)"` etc.).
- Status bar report on enter: `"<Label>: hover target, LMB apply, RMB
  cancel"` plus the mode's modifier hints.

## Non-goals

- No change to G / R / S / handle drags.
- No new alignment or density math; only the chain-walk fix in T.
- No persistence of preview settings between sessions.

## Implementation phases

1. **Framework + Stitch.** Add `STATE_PREVIEW`, `PreviewMode`,
   `_begin_preview` / `_tick_preview` / commit / cancel. Port stitch. Remove
   `STITCH_SRC` / `STITCH_DRAG`. Behaviour identical; verify by hand.
2. **T Straighten.** New `uv_chain_core.py` (pure: chain walk over an
   adjacency dict, valence stop, closed-loop detection, ratio-preserving
   distribution) with pytest. Mode object on top of it.
3. **A Align, D Match dimensions.** Re-plumb existing helpers.
4. **M Density, N Randomize.** Remove the density pick states.
5. Docs table and help overlay text per phase; one commit per phase.

## Testing

- pytest: `uv_stitch_core` (existing), `uv_chain_core` (new: open chain
  both directions, stops at valence 3, closed loop returns None, equal vs
  ratio spacing, degenerate two-point chain).
- Blender MCP on a detached `bmesh` (never the user's scene): the
  loops-based wrappers for chain collection and straightening.
- Manual in the viewport per mode: enter, hover, modifier toggle, commit,
  cancel, same-key cancel, orbit while previewing, undo after commit.
