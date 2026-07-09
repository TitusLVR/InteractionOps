# Non-Planar Faces Overlay

Toggles a sticky viewport overlay that highlights every non-planar face of the active edit-mesh in real time. Fix a face — flatten it below the threshold — and its highlight disappears on the next redraw.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.mesh_nonplanar_overlay</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: yes</span>
</div>

## What it does

- Checks every visible quad/ngon of the active object (triangles are always planar and skipped). A face is non-planar when any corner's plane deviates from the face's best-fit plane by more than the **Non-Planar Angle** threshold.
- Non-planar faces are filled with the theme's error color. Fill intensity scales with the deviation: faces just past the threshold are faint, faces warped 15° or more draw at full strength.
- A `Non-Planar: N` counter in the top-left corner of the viewport shows the current count and confirms the mode is on even when everything is planar.
- The overlay is **sticky**: it survives object switches and mode changes (it only draws in Edit Mode) and stays active until toggled off.

## How to use

1. Enter Edit Mode on a mesh and run **Non-Planar Faces Overlay** (F3 search, or bind it to a hotkey).
2. Model. Highlights update live as you move vertices; deviation-heavy faces glow stronger.
3. Run the operator again to turn the overlay off.

## Settings

- **Preferences → Non-Planar Overlay → Non-Planar Angle** — threshold in degrees (default 0.5°). Faces below it count as planar. The full-intensity ceiling (15°) is fixed.

## Notes

- Only the active object is checked in multi-object edit sessions.
- Detection runs in world space, so non-uniform object scale is measured the way you see it.
- Hidden faces are ignored.
