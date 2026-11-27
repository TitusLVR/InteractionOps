# Materials

A small list of materials: pick one and it is assigned. Works in Object Mode and Edit Mode without switching anything in the panel. Objects that cannot hold materials (Empty, Camera, Light, linked library data) are skipped quietly and counted in the report, never an error.

**Hotkey:** `F16` opens the panel as a popup (`iops.call_panel_materials`, rebindable in *Preferences › iOps › Keymaps*). The panel also lives in the sidebar: *N panel › iOps › Materials*.

## Assigning

| Action | What it does |
| --- | --- |
| Click a material | Assign it to the selected objects (the active object when nothing is selected; in Edit Mode, every object being edited). Each object ends up with only this material, on all faces. Objects sharing one mesh are handled once. |
| <kbd>Alt</kbd>+click | Assign it to the selected faces of the meshes: an existing slot holding it is reused, then an empty slot that no unselected face uses, otherwise a slot is added. In Object Mode the faces selected last time in Edit Mode are used; with no selected faces nothing changes. |
| <kbd>Ctrl</kbd>+click | Only make it the panel's active material (used by *Select Objects Using Material* and *Mark as Asset*), nothing is assigned. Clicking the empty part of a list row does the same. |

The result is reported in the status bar, for example *Assigned Steel to 2 objects, 1 skipped (Empty)*. Linked library materials can be assigned too; assigning never copies a material. Every assignment is one undo step.

## Panel

| Element | What it does |
| --- | --- |
| **New** | Create a material (Principled BSDF) named *Material*, *Material 2*, … and make it the active one. <kbd>Shift</kbd>+click also assigns it to the selection, <kbd>Shift</kbd>+<kbd>Alt</kbd>+click to the selected faces. |
| Functions menu (arrow button) | The material functions below. |
| List / Gallery | Switch between a list and a grid of previews. |
| Search | Show only materials whose name contains the typed words. |
| **Scene / Selected / File** | Show the materials used by objects in the scene, by the selected objects, or every material in the file. |
| *N empty slots* **Remove** | Shown only when the objects a click would assign to have empty slots; **Remove** runs *Remove Empty Slots* on them. |

Each list row shows the preview, the name, a **×N** badge when numbered duplicates are stacked, and the number of users (red at 0; a fake user does not count). The gallery shows larger previews with the name under each, a page of rows at a time with arrows to page through.

Previews render in the background the first time a material is shown, the same way as in Blender's own material lists.

## Duplicates

Copies made by Blender get numbered names: *Steel.001*, *Steel.002*. With **Stack Numbered Duplicates** on (default), the list shows such a family as one row, *Steel ×3*, standing for the original; clicking the row assigns the original, clicking the **×3** badge merges the family.

**Merge Duplicates and Relink** (Functions menu) merges every family:

- The original is the material named exactly *Steel*; without one, the lowest-numbered copy is the original and is renamed to *Steel* afterwards. A lone *Steel.001* is renamed to *Steel* when that name is free.
- A copy merges only when it is the same material: same node setup (node types, settings, input values, links) and the same material settings (blend, shadow, backface culling, displacement, viewport display, …). Moving nodes around does not count as a difference. Its users are relinked to the original and the copy is deleted.
- Copies that differ are kept and listed in the report; turn on **Force** in the operator's redo panel to merge them anyway.
- Linked library materials are never renamed or deleted.
- Afterwards the slots are cleaned up on every object that used a merged copy and on the selected objects (in Edit Mode: the objects being edited): slots holding the same material collapse into the first one, and empty slots are removed. Faces move along: faces of a collapsed slot go to the slot it collapsed into, faces of an empty slot go to the first remaining slot. Slots with other materials keep their faces. Slots *M, M, (empty), M.001, Other* end as *M, Other*. Objects with object-linked slots are left alone and counted in the report.

Each part can be switched off in the *Adjust Last Operation* panel (<kbd>F9</kbd>): **Merge Duplicates**, **Force**, **Collapse Duplicate Slots** and **Remove Empty Slots**. With **Merge Duplicates** off the operator is a plain slot cleanup of the selected objects. The report says what each part did, for example *Merged 2 duplicates, collapsed 3 slots, removed 1 empty slot*.

In the gallery the **×N** button next to a name merges that family, as the badge does in the list.

## Functions menu

- **Merge Duplicates and Relink** — see above.
- **Remap Materials…** — a two-column table: every material used in the chosen scope (**Selected Objects**, **Scene** or **File**) on the left, the material it changes to on the right (empty: unchanged; an arrow marks the rows that change). Switch between **List** (names and pickers) and **Thumbnails** (previews of both columns). Long tables are paged. **Remap** applies every row at once from the original state: *A → B* with *B → C* turns A into B and B into C, *A → B* with *B → A* swaps them. In Selected Objects and Scene the slots of those objects switch (shared meshes once); in File every user switches, except for linked library materials, which are skipped and counted. The source materials stay in the file. Afterwards **Collapse Duplicate Slots** (on by default) and **Remove Empty Slots** (off by default) clean the slots of the changed objects.
- **Copy Materials from Active** — give the other selected objects the material slots of the active object.
- **Select Objects Using Material** — select the objects that use the active material (Object Mode).
- **Remove Unused Slots** — remove the slots of the selected objects that no face uses, and the empty slots. Faces of a removed empty slot move to the first remaining slot.
- **Remove Empty Slots (Selected)** / **(Scene)** — remove every empty slot (a slot without a material) of the selected objects or of every object in the scene. Faces on a removed slot move to the first remaining slot. Objects sharing one mesh are handled once; objects with object-linked slots are left alone and counted.
- **Clear All Materials (Selected)** — remove every slot of the selected objects.
- **Clear All Materials (Scene)…** — remove every slot of every object in the scene, after a confirmation.
- **Delete Unused Materials…** — delete the materials no object or other data uses (a fake user does not count), after a confirmation that shows how many. Linked materials are left alone.

## Shelf

Set *Preferences › iOps › Materials › Interface* to **Shelf** to work from the iOps shelf: a strip along the bottom of the 3D Viewport, drawn in the iOps theme, with the same materials and tools as the panel (the same search, source filter, duplicate stacking and active material, so the two never disagree). The sidebar panel is hidden then, and the Materials hotkey (<kbd>F16</kbd> by default) shows or hides the shelf in every 3D Viewport. It shows in Object Mode and Edit Mode. Clicks, the wheel and drags on the strip belong to the shelf; everywhere else the viewport works as usual.

The tools are small icons, by default in a row centred above the materials: **New** (plus), **Search** (magnifier; opens a small search field), the sources **Scene** (sphere on a ground line), **Selected** (selection corners) and **File** (sheet), then, only while the selected objects have empty slots, a red slot icon with their count (click: remove them), and last **Functions** (three lines; the Functions menu, with the preview size at its top). The current source, and Search while a search is set, are tinted. Rest the mouse on an icon for a moment to see its name. *Preferences › iOps › Materials* sets the icons in a **Row** above the materials or a **Column** beside them, at the **Left**, **Center** or **Right**.

| Action on a material | What it does |
| --- | --- |
| Click | Assign to the selected objects, whole object |
| <kbd>Alt</kbd>+click | Assign to the selected faces |
| <kbd>Ctrl</kbd>+click | Make it the active material, nothing assigned |
| Click the **×N** badge (top left) | Merge that family of numbered duplicates |
| Click the user count (top right) | Select the objects using it |
| Drag onto an object in the viewport | That object (selected or not) gets it, whole object; the object is outlined while dragging |
| Drag with <kbd>Alt</kbd> held at release | Only the face under the cursor gets it (the face is filled while dragging) |
| Hover | The faces using it are highlighted in the viewport (Highlight On Hover) |

Releasing a drag over the shelf or over empty space does nothing. Drag the shelf's top edge to make it taller or shorter: the materials wrap into as many rows as fit, and the wheel over the shelf scrolls when they do not all fit. <kbd>Ctrl</kbd>+wheel over the shelf changes the preview size. Height and preview size are kept in the preferences.

The shelf stays clear of the toolbar, the sidebar, the headers and an asset shelf. In a quad view it sits in the bottom-right view. Previews are made the first time a material is shown (a gray square until Blender has rendered it). The hover highlight covers at most 300,000 triangles; on heavier scenes it is partial.

## Library Shelf

Set **Interface** to **Library Shelf** to use Blender's own asset shelf along the bottom of the 3D Viewport (like the brush shelf in Sculpt Mode, but with materials): it shows the material assets of an asset library. The sidebar panel is hidden then, and the Materials hotkey shows or hides that asset shelf in the viewport under the mouse. The shelf shows in Object Mode and Edit Mode.

The shelf shows material assets: those of the chosen **Library** plus the material assets of the current file. Materials that are not marked as assets do not appear; mark the panel's active material with **Mark as Asset** in the Functions menu (a preview is generated), and remove the mark again with **Clear Asset**. Nothing is marked automatically.

| Action | What it does |
| --- | --- |
| Click | Assign to the selected objects, whole object, as in the panel |
| <kbd>Alt</kbd>+click | Assign to the selected faces |
| <kbd>Ctrl</kbd>+click | Make it the panel's active material, nothing assigned (a library asset is imported for that) |
| Drag onto an object | Blender's own material drop |
| Right-click | Assign to Object, Assign to Selected Faces, Make Active Material, Select Objects Using It (when the material is already in the file) and the Functions menu |

A library asset is imported when it is first used, by **Import**: *Append (Reuse)* appends a local copy and reuses that copy the next time the same asset of the same library file is used (no *Name.001* pile-up; the copy remembers where it came from in a custom property, `iops_asset_source`); *Link* links it from the library file. A missing or unreadable library file gives a warning, nothing else.

The shelf's own **Display Settings** popover (in the shelf header) holds **New**, the **Functions** menu and the **Library** choice with its folder button: the shelf API has no place for buttons in the header itself.

## Options

In *Preferences › iOps › Materials*:

- **Interface** — Panel (sidebar panel and popup), Shelf (the iOps shelf) or Library Shelf (Blender's asset shelf for asset libraries). A saved Shelf setting from before the iOps shelf existed becomes Library Shelf.
- **Shelf Height**, **Shelf Thumbnail Size** — the iOps shelf's height and preview size in pixels (also changed by dragging its top edge and by <kbd>Ctrl</kbd>+wheel over it).
- **Highlight On Hover** — highlight the faces of the material under the mouse in the iOps shelf (default on).
- **Shelf Tools** — Row (default): the icons in one row at the top of the shelf, the materials below using its full width; Column: the icons in one column at the left or right edge, wrapping into another column when the shelf is too short for all of them.
- **Shelf Width** — width of the shelf as a share of the viewport width (20–100 %); a narrower shelf is centred.
- **Shelf Materials Alignment** — Left, Center (default) or Right: where each row of materials sits in the shelf.
- **Shelf Tools Position** — Left, Center (default) or Right. A column goes to the left edge with Left, to the right edge with Center or Right.
- **Library** — the Blender asset library whose materials the shelf shows; empty shows all libraries. The folder button picks a folder and registers it as an asset library (this changes your Blender Preferences, *File Paths › Asset Libraries*); a folder already registered is only selected.
- **Import** — Append (Reuse) or Link, for library assets the shelf assigns.

- **Default View** — List or Gallery until the panel's own toggle is used.
- **Popup Width** — width of the Materials popup in interface units (default 12); the Remap Materials dialog is 1.8 times as wide.
- **List Rows** — the most rows the list shows before it scrolls (default 8); a shorter list is only as tall as its materials.
- **Thumbnail Size** — size of a gallery preview in interface units (default 4); also the default preview size of new asset shelves (units × 20 pixels).
- **Gallery Rows** — rows per gallery page (default 3); the number of columns follows from the panel width and the thumbnail size.
- **Stack Numbered Duplicates** — list numbered duplicates as one row with a count badge (default on).
