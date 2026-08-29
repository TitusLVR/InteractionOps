# Asset Management

![Asset Management](../img/ui/pies/pie_assets.png)

A pie menu that gathers everyday Asset Browser chores in one place. Mark or clear assets, move them between catalogs, create and delete catalogs, switch the active asset library, render a thumbnail, or publish to your library — without leaving the 3D Viewport.

**Hotkey:** <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>A</kbd>. Also available: Asset Browser right-click menu › *Move Asset to Catalog*.

## Pie entries

| Entry | What it does |
| --- | --- |
| Mark as Asset › Object / Collection / Active Material / Active Image | Mark the selection (or its parent collection, active material, active image) as an asset |
| Clear Asset | Remove the asset flag from the selection |
| Move to | Pick a catalog (or *Search* by name) and move the selected assets into it. *New Catalog* creates one — use `/` in the path to nest, e.g. `Props/Furniture` |
| Delete Catalog | Remove a catalog by picking it or searching by name; *Delete Empty Catalogs* cleans up all unused ones |
| Render Thumbnail | Render a preview image for the active asset (see *Render Asset Thumbnail*) |
| Library Popup | Open the iOps library browser |
| Publish to Library | Send the active object, collection, material, shader group or geometry nodes to your library |
| Library box | Switch the active asset library (Current File or any configured library). *Select in Browser* filters the Asset Browser to the selected asset, *Clear Filter* resets it, *Refresh* reloads all open Asset Browsers |
| Open in Current Blender | Shown when the selection points to an external .blend — opens that file here |

## Tips

- Save the .blend first: catalogs live next to the file, so an unsaved file has nowhere to store them.
- Catalog search shows shortened names; hover to see the full path.
