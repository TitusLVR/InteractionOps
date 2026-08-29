# UVMaps Cleaner

Removes UV maps from all selected meshes in one click, starting at a chosen slot. Pick the button for the first UV map you want gone: **All** wipes every UV map, **2+** keeps only the first, **3+** keeps the first two, and so on up to **8**, which removes only the eighth. Great for cleaning imported assets that carry stray or duplicate UV channels. Object Mode.

**Hotkey:** Not bound by default — assign a key in *Preferences › iOps › Keymaps*, or run it from the iOps pie / operator search. Also available: the *IOPS TPS* sidebar panel, UVMaps row (buttons All, 2+, 3+ ... 8).

## Tips
- Only visible meshes with faces are processed; hidden objects and non-meshes are skipped.
- The removal is destructive to UV data, but a single Ctrl+Z brings everything back.
