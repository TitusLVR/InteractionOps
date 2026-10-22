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
- *Preferences › iOps › Instance Edit › Button in 3D View Header* hides only the idle button. The red icon always shows while a session is open, in every mode, including after you reopen a file saved mid-edit.

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

The merge runs in a background Blender that loads the source file: the dry run once, **Write** once more (twice with shared datablocks ticked). Blender is blocked meanwhile, with a wait cursor and a status bar message; on a large source that takes as long as opening it two or three times, and needs about as much memory again as the source. *Preferences › iOps › Instance Edit › Worker Timeout* (default 300 s) limits each run.

During Commit these files exist next to the source and are removed afterwards: `<stem>.iops_commit-<run id>.blend`, `.json` and `.result.json` (a new run id per Commit) and the lock `<source>.iops_lock`, which keeps two Commits (or a Commit and a Rollback) on one source from running at once. Rollback writes through `<stem>.iops_commit-<run id>.tmp` next to the source. Backups are not kept next to the source (see below). A lock left by a crashed Blender counts as stale after the worker timeout and is replaced.

### Backup and Rollback

Before writing, Commit copies the source into the **backup folder**: *Preferences › iOps › Instance Edit › Backup Folder*, or, when that is empty, `iops/instance_edit_backups` in your Blender user config folder (on Windows `%APPDATA%\Blender Foundation\Blender\<version>\config\iops\instance_edit_backups`). The preference must be an absolute path: a relative one (such as `//backups`) is ignored, the default folder is used and Commit's dialog says so. Nothing lands next to the source, so backups never reach Perforce or an asset-library folder, and people sharing a network drive do not overwrite each other's backups. Each backup point is `<stem>-<hash>-<YYYYMMDD-HHMMSS>.blend`, the time in UTC so the names keep their order across daylight-saving and clock changes (for `D:\lib\Props.blend`: `Props-1a2b3c4d-20261022-143005.blend`; the 8-character hash of the source's full path keeps two `Props.blend` from different folders apart) with a `.json` next to it (the source's path, backup time, the file's state after the Commit, and which session committed). *Backups per File* (same section, default 3, 1 to 50) sets how many points are kept per source; after a successful write the oldest beyond that number are removed, never the backup just taken. When Commit fails without touching the source, it removes its backup again, so a failed Commit does not cost a point; when the merge failed after it may have written the source, the backup stays as the newest point so you can roll back to it. If the backup folder cannot be created or written (read-only, a file in the way, disk full), Commit stops before touching the source.

Do not point several machines at one backup folder: points are told apart by the source's path, so the same workspace path on two machines mixes their points. Changing the folder preference, or a Blender upgrade (the default folder is inside the per-version config folder), hides the points in the old folder; they are still on disk there.

In Object Mode with no session open, a **Rollback** icon (loop-back arrow) shows in the 3D Viewport header for each library of the file that has a backup point; its tooltip names the file. It opens a dialog with the file and a list of its backup points, newest first (`<date and time>  —  <backup name>`; the newest is preselected), and warns "`<file>` was modified after this backup" when the source changed after the Commit that took the chosen point (always the case for an older point, since later Commits changed it), or "Cannot tell whether `<file>` was modified after this backup" when the point's `.json` is missing or damaged, or its Commit failed midway. The list is taken when the dialog opens: a point another Blender adds meanwhile does not change your choice. **Rollback** copies that point over the source (through a temp file next to it, so the source is never half-written) and reloads the library. Rolling back keeps every point, so you can roll back to another one afterwards. Backups live on your machine only: Rollback is for "just now", Perforce keeps the history.

### Perforce

A read-only source is checked out automatically: Commit (and Rollback) run `p4 edit` on it and tell you so, in the plan dialog ("Checked out in Perforce: <file>") together with the `p4 edit` output. Start already warns when the source is read-only and will be checked out on Commit. If `p4` is not on PATH, the file is still read-only afterwards, or Perforce answers that it must be synced or resolved, is not on the client or does not exist, Commit stops with that line. Turn *Instance Edit: Perforce checkout* off (preferences, Instance Edit section) to check files out by hand instead; Commit then stops on a read-only source.

Keep the helper files next to the source out of Perforce with these `.p4ignore` entries (backups are written to the backup folder, not next to the source):

```
*.iops_commit*
*.iops_lock
```

### Nested sessions

An instancer inside the `[edit]` copy can be edited as its own session, from the same or another library. The header shows the depth number when sessions are nested. Commit and Cancel act on the innermost session; close inner sessions first.

### Not merged

Concurrent edits of the same collection by two people are not merged: the last Commit wins. The dialog warns when the source changed since Start but does not combine the two versions. Rollback restores an earlier one.
