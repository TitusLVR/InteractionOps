# Edit Instance

Edit the collection behind a collection instance right where the instance sits, without opening another file or hunting for the source collection. Start, change the objects, press Stop, and every instance of the collection shows the result.

**Hotkey:** Not bound by default. Use the collection icon in the 3D Viewport header (after the Selection Sets button) or **Edit Instance** in the [Edit Pie](../ui/ui_pies.md#edit-pie) when an instancer is selected. The header button can be turned off in *Preferences › iOps*.

## Start

Select an instancer Empty of a collection that lives in this file and press the collection icon (or **Edit Instance** in the pie). Object Mode only.

- The collection's original objects move onto the instance, become visible and selected (hidden and unselectable objects and collections included).
- The edited collection becomes the active collection, so new objects you add land inside the asset.
- The instancer, every other instancer of that collection and the instancers of its parent collections are hidden while you edit.

## Stop and Restore

While a session is open the icon turns red and a **Restore** icon appears next to it, in every mode (Edit, Sculpt, Paint and so on). Both buttons switch back to Object Mode themselves.

| Button | What it does |
| --- | --- |
| **Stop** (red collection icon) | Finish and keep every edit, moved and added objects included. The originals go back to their place, the instancers reappear, and collection visibility, exclusion and selectability are restored. Objects you did not touch get back exactly the location, rotation and scale values they had. |
| **Restore** (recover icon) | Emergency exit. Puts parents, transforms and visibility back exactly as they were at Start and discards transform edits made since. Geometry, modifier and material edits stay. |

Undo works across Start, Stop and Restore.

## Tips
- Only uniformly scaled instances can be edited. A non-uniformly scaled or sheared instancer (or one under such a parent), or one scaled to zero, keeps the button inactive; the tooltip says "Instance is non-uniformly scaled or sheared; edit a uniformly scaled instance".
- Objects you add during the edit stay where they are after Restore: inside the collection, at the instance's place.
- Saving the file mid-session saves the originals at the instance's place, so other files that link this collection see them displaced until you Stop and save again.
- If an object has transform animation, drivers or constraints, Start shows a warning. Do not edit those objects and do not change the frame while editing.
- Linked (library) collections, and local collections that contain library objects, are not supported yet; the button stays inactive and its tooltip says why.
- *Preferences › iOps › Statistics Overlay › Instance Edit in 3D View Header* hides only the idle button. The red icon always shows while a session is open, in every mode, including after you reopen a file saved mid-edit.
