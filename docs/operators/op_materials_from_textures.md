# Materials from Textures

Build ready-to-use materials straight from image files. Pick one or more textures in the file browser; each becomes a new material with the image plugged into Base Color. Matching normal (`_nm`) and mask (`_mk`) maps sitting in the same folder are hooked up automatically.

**Hotkey:** Not bound by default — assign a key in *Preferences › iOps › Keymaps*, or run it from the iOps pie / operator search. Also available: iOps Pie › tools column › *Materials from Textures*.

## Options

- **Import all textures** — also pick up matching normal and mask maps from the folder (on by default).

## Tips

- Material names come from the filename with the prefixes/suffixes listed in *Preferences › iOps* stripped, so `T_Wood_d.png` can become `Wood`. Blender adds `.001` on name clashes.
- Images and materials are protected from purge, so they survive until you assign them.
