# Render Asset Thumbnail

Renders a 500x500 PNG preview for the currently selected asset datablock (Collection, Object, Material, or Geometry Nodes) and assigns it as that datablock's custom asset preview. The operator drives Blender's viewport OpenGL render with an auto-framed camera and, when the selection covers multiple asset-marked collections, renders each one in turn with isolation so they do not overlap.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.assets_render_asset_thumbnail</span>
<span class="mode">Mode: Object</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview

Blender's built-in "Generate Preview" for asset datablocks uses a fixed camera angle and tight framing that often clips or under-fills the thumbnail, and it does not handle collection-instance empties well. This operator replaces that workflow with a configurable pass: pick a view direction (current 3D viewport, 3/4 right/left, front, side), a focal length, a framing margin preset, and let it render. Collection-instance empties are framed against the geometry they spawn via the dependency graph, not their tiny display gizmos.

When a selection spans several asset-marked collections, the operator enters a batch mode that isolates each collection (local view, falling back to per-object `hide_viewport`), renders, assigns the preview, and restores state — one thumbnail per asset in a single invocation. A header-text progress indicator runs on every 3D viewport during the batch.

The render output is a temporary PNG in the system temp dir under `iops_thumb/`; the file is unlinked after the preview is loaded onto the datablock.

## Usage

- Selection: at least one asset datablock reachable from the active selection. For COLLECTION mode this is asset-marked collections found from the selection (batch path) or `context.collection`. For OBJECT / MATERIAL / GEOMETRY modes the active object is used (MATERIAL / GEOMETRY additionally require a MESH).
- Context: must run from a VIEW_3D — the operator needs a 3D viewport for both framing and `render.opengl`.
- Invocation: no default keymap binding. Run via F3 search ("Render Active Asset Thumbnail"), the Assets pie (`iops.call_pie_assets`), or any custom binding you add.

Steps:

1. Select the asset(s) in the 3D viewport or outliner.
2. Run the operator.
3. Adjust `Render For`, `Camera View`, `Lens`, `Distance`, framing style, and alpha in the F6 redo panel — undo and re-execute as needed.

## Properties

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `render_for` | Enum | `COLLECTION` | Target type. Items: `OBJECT` (Object), `COLLECTION` (Collection), `MATERIAL` (Material), `GEOMETRY` (Geometry Nodes). |
| `camera_view` | Enum | `CURRENT` | View direction. Items: `CURRENT` (Current View — read from active 3D viewport `region_3d`), `THREE_QUARTER_RIGHT` (3/4 Right), `THREE_QUARTER_LEFT` (3/4 Left), `FRONT`, `SIDE`. |
| `thumbnail_lens` | Float | `90.0` | Focal length in mm. Min `1.0`, max `200.0`. Used directly for the temp camera and as the viewport `space.lens` during viewport render. |
| `persp_distance` | Float (FACTOR) | `1.0` | Camera distance multiplier on top of the auto-fit distance. Min `0.1`, max `5.0`, soft range `0.5`–`2.0`. |
| `use_framing` | Bool | `True` | Auto-frame the asset to fill the thumbnail. When off, the current viewport view is used as-is. |
| `framing_style` | Enum | `TIGHT` | Padding preset: `TIGHT` (5%, multiplier 1.05), `BALANCED` (16%, 1.16 — matches Blender asset style), `LOOSE` (30%, 1.30), `CUSTOM` (use `frame_margin`). |
| `frame_margin` | Float (FACTOR) | `0.16` | Custom margin multiplier added to 1.0. Min `0.0`, max `0.5`, soft range `0.05`–`0.35`. Only used when `framing_style = CUSTOM`. |
| `use_alpha` | Bool | `True` | Render with transparent background (RGBA + `film_transparent`). When off: RGB with solid background. |
| `toggle_overlays` | Bool | `True` | Hide viewport overlays during the render and restore afterward. |

## Notes

- Render is fixed to 500x500 PNG. Resolution / file format / color mode / `film_transparent` are saved before and restored after the render — your scene render settings are not modified persistently.
- Saved-and-restored viewport state per render: `view_perspective`, `view_distance`, `view_location`, `view_rotation`, `space.lens`, overlays, and `shading.show_background`.
- The viewport OpenGL path is tried first; if no 3D viewport `region_3d` is available the operator falls back to a temporary camera (`IOPS_Thumbnail_Cam`) plus `render.opengl(write_still=False)` with a `temp_override` onto the first VIEW_3D area.
- Save path tries three strategies in order: `Image.save_render`, `Image.save` after setting `filepath`, and finally a pixel-copy into a fresh `bpy.data.images.new` image that gets `.save()`'d. Output is unlinked from disk after `ed.lib_id_load_custom_preview` loads it onto the datablock.
- Batch COLLECTION mode (triggered when `find_asset_collections_from_selection` returns one or more asset-marked collections) isolates each collection via `view3d.localview`. If local view cannot be entered, per-object `hide_viewport` is used with a keep-alive set that includes the target collection plus, recursively, every collection referenced via a collection-instance empty inside it. `LayerCollection.exclude` / `hide_viewport` and eye-icon `hide_set` state are never touched.
- Linked datablocks (`datablock.library is not None`) are skipped silently in the non-batch path; the operator reports a warning if no local asset datablocks remain.
- Collection-instance empties are framed against depsgraph-spawned geometry via `compute_combined_bound_box` walking `depsgraph.object_instances`, falling back to raw bound boxes only when no framable geometry is found.
- Header text on all 3D viewports shows `IOPS Thumbnail i/N: rendering '<name>'...` during batch progress, plus a cursor progress bar through `wm.progress_begin`/`update`/`end`. Per-asset success/failure is also printed to the console with the `[IOPS Thumbnail]` prefix.
- `bl_options = {"REGISTER", "UNDO"}` — supports F6 redo, but the preview assignment side-effect is not undoable in the usual sense; rerunning the operator overwrites the preview.

## Related

- [Assets Pie](../ui/ui_pies.md)

