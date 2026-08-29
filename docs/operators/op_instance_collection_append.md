# Instance Collection Append

![Instance Collection Append](../img/ui/panels/panel_collection_append.png)

Pull extra collections out of a linked asset's source .blend without opening it. Select a linked collection instance in Object Mode, scan its source file, tick the collections you want and append them into the current scene. Handy when a library file holds variants or helper collections next to the one you linked.

**Hotkey:** Not bound by default — use the *Collection Append* panel in the 3D Viewport sidebar (<kbd>N</kbd>) › iOps tab.

## Panel steps

| Button | What it does |
| --- | --- |
| Scan Collections | Read the list of collections from the active instance's source file |
| Select All / Deselect All | Toggle every entry in the list |
| Append (N selected) | Append the ticked collections; ones already present are skipped |

## Tips

- The active object must be a collection instance from a linked library, otherwise the scan button stays greyed out.
