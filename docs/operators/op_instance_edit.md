# Edit Instance

Edit the collection behind a collection instance right where the instance sits, without opening another file or hunting for the source collection. Start, change the objects, press Stop, and every instance of the collection shows the result.

**Hotkey:** Not bound by default. Use the collection icon in the 3D Viewport header (after the Selection Sets button) or **Edit Instance** in the [Edit Pie](../ui/ui_pies.md#edit-pie) when an instancer is selected. The header button can be turned off in *Preferences › iOps*.

## Start

Select an instancer Empty of a collection that lives in this file (for a collection linked from another .blend see [Linked collections](#linked-collections)) and press the collection icon (or **Edit Instance** in the pie). Object Mode only.

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
- Linked (library) collections have their own flow, see [Linked collections](#linked-collections). Local collections that contain library objects are not supported; the button stays inactive and its tooltip says why.
- *Preferences › iOps › Statistics Overlay › Instance Edit in 3D View Header* hides only the idle button. The red icon always shows while a session is open, in every mode, including after you reopen a file saved mid-edit.

## Linked collections

Select an instancer of a collection linked from another .blend and press the same button (the icon is a chain; the pie entry is **Edit Linked Instance**). Edit the collection here, then **Commit** writes it back into its source file. Object Mode only.

### Start

- The collection is appended as a local copy named `<name> [edit]`, linked under the scene's root collection, and its objects move onto the instance. The copy becomes the active collection.
- Only the instancer is hidden. Other instancers of the collection keep showing the old library data until Commit reloads the library.
- Objects the copy pulls in from a third library cannot be moved: they stay linked and hidden while you edit, and Start lists them in a warning.
- A library override of the collection gets a warning: it may break after Commit.
- Only uniformly scaled instances can be edited: a non-uniformly scaled or sheared instancer keeps the button inactive, with the reason in its tooltip.
- Do not edit animated, driven or constrained objects (Start warns), as in the local flow.
- Saving the editing file mid-session is fine; the copy is local.

### Commit and Cancel

While the session is open the header shows a red **Commit** icon (chain) and a **Cancel** icon (X).

| Button | What it does |
| --- | --- |
| **Commit** | Dry run, plan dialog, and on **Write**: backup of the source, write, library reload, copy removed. Cannot be undone with Ctrl+Z. |
| **Cancel** | Discards the copy and every change made to it. The source is not touched. |

The dialog lists what Commit would do to the source:

- **Replaced**: datablocks that exist in the source and are overwritten by your version.
- **Added**: new datablocks created in the source.
- **Kept**: the source keeps its version.
- **Shared**: datablocks also used outside the collection, each with a checkbox, **off by default**. Tick one to overwrite the source's version. Datablocks used only by ticked ones are updated with them (listed as *Updated with the ticked ones*).
- **Discarded**: datablocks you added into a kept shared collection that would be dropped, so nothing would use them.
- **Removed from the collection** and **Deleted from the source**: objects you unlinked or deleted in the copy.

The collection's view-layer flags and asset metadata (asset mark, catalog, description, author, tags) in the source are preserved, and relative paths (textures, caches, texts, other libraries) stay relative. The dialog also warns when the source changed since Start (the merge runs on its current content) and when the source was saved by an older Blender (Commit saves it in the current format). When a line of the dialog is cut after eight names, the full plan is printed to the system console.

Commit refuses, with the reason in the report, when:

- objects of the copy use a material or mesh linked from the source: "Make `<name>` local first";
- drivers in the copy reference a scene;
- the source file is read-only, or Perforce says it must be synced or resolved (see Perforce below);
- the source was saved by a newer Blender than the one running (saving would down-version it);
- another Commit on the same source is running, from this or another Blender: "another Commit is running on `<file>`";
- the session was committed already and came back through Ctrl+Z: "This session was already committed; Cancel it";
- the source changed between the dry run and **Write**, or the merge result differs from the plan: "Commit again".

The merge runs in a background Blender that loads the source file: the dry run once, **Write** once more (twice with shared datablocks ticked). Blender is blocked meanwhile, with a wait cursor and a status bar message; on a large source that takes as long as opening it two or three times, and needs about as much memory again as the source. *Preferences › iOps › Statistics Overlay › Instance Edit: worker timeout* (default 300 s) limits each run.

During Commit these files exist next to the source and are removed afterwards: `<stem>.iops_commit-<run id>.blend`, `.json` and `.result.json` (a new run id per Commit) and the lock `<source>.iops_lock`, which keeps two Commits on one source from running at once. A lock left by a crashed Blender counts as stale after the worker timeout and is replaced.

### Backup and Rollback

Before writing, Commit copies the source to `<source>.iops_bak` (for `Props.blend`: `Props.blend.iops_bak`; no `.blend` extension, so asset libraries never pick it up) and writes `<source>.iops_bak.json` (backup time, file state, and which session committed). In Object Mode with no session open, a **Rollback** icon (loop-back arrow) shows in the 3D Viewport header for each library of the file that has a backup. It asks for confirmation naming the backup time, and warns when the file was modified after the backup. Confirming copies the backup over the source (through a temp file, so the source is never half-written) and reloads the library. Only the last Commit's backup is kept.

### Perforce

A read-only source makes Commit stop. With *Instance Edit: Perforce checkout* on (same preferences section), Commit runs `p4 edit` on it first and shows its output in the plan dialog. If the file is still read-only afterwards, or Perforce answers that it must be synced or resolved, is not on the client or does not exist, Commit stops with that line. Rollback does the same.

Keep the helper files out of Perforce with these `.p4ignore` entries:

```
*.iops_bak*
*.iops_commit*
*.iops_lock
```

### Nested sessions

An instancer inside the `[edit]` copy can be edited as its own session, from the same or another library. The header shows the depth number when sessions are nested. Commit and Cancel act on the innermost session; close inner sessions first.

### Not merged

Concurrent edits of the same collection by two people are not merged: the last Commit wins. The dialog warns when the source changed since Start but does not combine the two versions. Rollback restores the previous one.
