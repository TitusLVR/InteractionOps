# Material Override

![Material Override](../img/ui/panels/panel_material_override.png)

A popup for the view layer's material override. Click any material in the list to render everything with it (clay, wireframe, UV checker…), and click *Clear* to return to the objects' own materials. Use it for lookdev passes or quick clay renders without touching your materials.

**Hotkey:** Not bound by default — assign a key in *Preferences › iOps › Keymaps*, or run *View Layer Material Override* from operator search.

## Panel

| Element | What it does |
| --- | --- |
| Current Override | Shows the active override material; *Clear* removes it |
| Material list | Click a name to set it as the override; the active one is ticked |
| Fancy Mode | Switch the list to a grid with large previews |
| Refresh Previews / Generate All Previews | Rebuild missing or stale material thumbnails |
| Clear Warning | Dismiss the notice shown after a render was started with an override active |

## Tips

- The override applies to the current view layer only, so you can keep a clay layer and a beauty layer side by side.
