# Auto Smooth

Applies Blender's *Shade Auto Smooth* (the Smooth by Angle modifier) to every selected mesh in one go, at the angle you choose. Any old Auto Smooth / Smooth by Angle modifier is removed first, and the fresh one is moved to the top of the stack — so a batch of mixed objects never piles up duplicates. Works in Object Mode; meshes that are in Edit Mode are handled too.

A companion tool, **Clear Custom Normals**, strips custom split normals from the selected meshes. Custom normals override auto smoothing, so clear them first on imported geometry if auto smooth seems to do nothing.

**Hotkey:** Not bound by default — assign a key in *Preferences › iOps › Keymaps*, or run it from the iOps pie / operator search. Also available: the *IOPS TPS* sidebar panel has 30 / 60 / 90 / 180 buttons for Auto Smooth and a button for Clear Custom Normals.

## Options
- **Angle** — the smoothing angle in degrees (default 30). Change it in the redo panel after running.

## Tips
- Non-mesh objects in the selection are simply skipped.
- Clear Custom Normals only shows up when at least one selected mesh actually has custom normals.
