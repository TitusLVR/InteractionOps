# Three Point Rotation

Modal operator that builds a temporary three-empty rig (origin + two aim targets) around the active mesh object and uses Damped Track constraints to drive its orientation. Move the dummies to define a new local frame, then confirm to bake the resulting transform onto the object.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.object_modal_three_point_rotation</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: yes</span>
<span class="hud">HUD: yes</span>
</div>

## Overview
Aligning an object to an arbitrary triplet of points (origin, primary axis target, secondary axis target) is awkward with built-in tools. This operator spawns three empties — `O_Dummy` (origin, single-arrow), `Y_Dummy` and `Z_Dummy` (sphere targets) — and pre-wires Damped Track constraints on the origin empty pointing at the two target empties. The user drags the dummies (optionally with snapping enabled) until the rig matches the desired frame, then parents the source object to the origin empty and bakes the result on confirm.

The operator stores and overrides the scene's snap settings during the session and restores them on exit, so the snap UI returns to its prior state regardless of whether the modal is confirmed or cancelled.

## Usage
- Requires a single active mesh object in Object Mode (VIEW_3D).
- No default keymap binding (registered placeholder is `Ctrl+Alt+Shift+F19` in `prefs/hotkeys_default.py`, intended to be remapped). Invoke via menu / F3 search / Pie.
- On invoke the three empties are created at the object location and sized relative to its bounding-box average. The origin empty (`O_Dummy`) becomes active.
- Move the dummies with `G` / `R`, optionally toggle snap with `S`, then press `1` to parent the object to the rig and `Space` to confirm.

## Modal Controls

| Key | Action |
| --- | --- |
| <kbd>LMB</kbd> | Selection click; only `O_Dummy` / `Y_Dummy` / `Z_Dummy` may become active. Other picks are reverted. |
| <kbd>MMB</kbd> / <kbd>WheelUp</kbd> / <kbd>WheelDown</kbd> | Pass-through for viewport navigation. |
| <kbd>F1</kbd> | Select `O_Dummy` and start `transform.translate`. |
| <kbd>F2</kbd> | Select `Y_Dummy` (internally targets `Z_Dummy` object — see Notes) and start `transform.translate`. |
| <kbd>F3</kbd> | Select `Z_Dummy` (internally targets `Y_Dummy` object — see Notes) and start `transform.translate`. |
| <kbd>A</kbd> | Select all three dummies. |
| <kbd>G</kbd> | Invoke `transform.translate` on current selection. |
| <kbd>R</kbd> | Invoke `transform.rotate` on current selection. |
| <kbd>S</kbd> | Toggle `tool_settings.use_snap`. |
| <kbd>F</kbd> | Swap locations of `Y_Dummy` and `Z_Dummy`. |
| <kbd>0</kbd> | Reset: unparent object, clear constraints on `O_Dummy`, remove proxy, restore the captured object world matrix. |
| <kbd>1</kbd> | Toggle parent object -> `O_Dummy` (keep transform). On enabling, also spawns a `Proxy_Dummy` cube empty parented to `O_Dummy`. On disabling, clears parents on all dummies and the object, and removes the proxy. |
| <kbd>2</kbd> | Toggle a single Damped Track constraint on `O_Dummy` tracking `Z_Dummy` (track axis Z). Switches `O_Dummy` display between SINGLE_ARROW and ARROWS. |
| <kbd>3</kbd> | Toggle two Damped Track constraints on `O_Dummy` (Y-axis -> `Y_Dummy`, Z-axis -> `Z_Dummy`). Clears constraints if either is already present. |
| <kbd>=</kbd> | Scale all three dummies by 1.5. |
| <kbd>-</kbd> | Scale all three dummies by 0.75. |
| <kbd>Space</kbd> | Confirm: parent-clear with keep-transform on the object, delete all dummies and proxy, restore snaps. |
| <kbd>Esc</kbd> | Cancel: delete dummies/proxy, restore the captured object world matrix, restore snaps. |
| <kbd>H</kbd> | HUD/help overlay toggle (handled by HUD layer; see HUD). |

## HUD
The modal draws two overlays bound to the active VIEW_3D region:

- A title HUD (`HUDOverlay` "three_point_rotation", title "3 Point Rotation").
- A help overlay (`HelpOverlay`) listing the key bindings above (Reset transforms, Toggle lock, Toggle 2/3 point, Select all dummies, Flip Y and Z, Toggle snaps, Translate/Rotate, Select O/Y/Z dummy, Scale dummies, Finish, Cancel, Help / Toggle HUD).

Both overlays support drag-positioning and parameter/help toggle events via the standard IOPS HUD theme. Colours are read from `preferences.addons["InteractionOps"].preferences.iops_theme`; if the theme is missing the HUD still draws but drag/toggle interactions are skipped.

## Notes
- The operator has no `bl_props`; all behaviour is driven by modal keys.
- F2/F3 wiring quirk: the `select_target` branches for `"Y_Dummy"` and `"Z_Dummy"` actually select and activate the *other* dummy (Y branch sets `Z_Dummy` active, Z branch sets `Y_Dummy` active). This is in the source as written; treat the F2/F3 labels in the help overlay accordingly.
- `invoke` overwrites `self.Z_Dummy` with `bpy.data.objects["Y_Dummy"]` (lines reassigning `self.Z_Dummy` twice); the operator works regardless because subsequent code addresses dummies by name via `bpy.data.objects[...]`.
- Snap settings touched during the session: `transform_pivot_point`, `snap_target`, `use_snap_self`, `snap_elements`, `use_snap_align_rotation`, `use_snap_translate`, `use_snap_rotate`, `use_snap_scale`, and `use_snap`. Originals are restored on Space or Esc.
- Dummy names are hard-coded (`O_Dummy`, `Y_Dummy`, `Z_Dummy`, `Proxy_Dummy`). Pre-existing objects with these names in the scene will collide and break the modal.
- Poll fails outside VIEW_3D / Object Mode, with empty selection, or if the active object is not a MESH.
- Cancel restores the cached `matrix_world` of the source object captured at invoke; confirm bakes whatever transform the rig produced via parent-clear keep-transform.

## Related
- [Object Rotate (axis ops)](op_object_rotate.md)
- [Mesh Align Origin to Normal](op_align_origin_to_normal.md)
- [Object Drag Snap](op_drag_snap.md)
