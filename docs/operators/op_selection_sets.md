# Selection Sets

![Selection Sets](../img/ui/panels/panel_selection_sets.png)

Save a selection under a name and bring it back any time. Works for vertices, edges and faces in Edit Mode and for objects in Object Mode. Sets survive undo, topology edits and file reload — if you delete part of a set, the rest still recalls. Edit Mode sets and Object Mode sets are kept in separate lists.

**Hotkey:** Not bound by default — assign a key in *Preferences › iOps › Keymaps*. The panel lives in the sidebar: *N panel › iOps › iOps Selection Sets*, and a button in the middle of the 3D Viewport header (showing the active set's name) opens the same panel as a popover. The header button can be turned off in *Preferences › iOps*.

| Button | What it does |
| --- | --- |
| **+** | Save the current selection as a new set |
| **−** | Delete the active set |
| **Rename** | Rename the active set |
| **Refresh** | Rebuild the list (normally automatic) |
| **Delete All** | Remove every set in the current mode |
| **Select Set** | Select the set's members, switching to the select mode it was saved in |
| **Replace** | Overwrite the active set with the current selection |
| **Extend / Subtract / Intersect / Difference** | Combine the active set with the current selection; hold <kbd>Shift</kbd> to write the result back into the set instead |
| **Eye** icon on a row | Preview the set's members as an overlay without changing the selection |

## Tips
- Double-click a name in the list to rename it in place.
- The count column shows how many members a set still has; a warning icon means members were deleted since the set was saved. Use **Replace** to refresh it or delete it.
- Multi-object Edit Mode is supported — a set is saved on and recalled from every mesh being edited.
