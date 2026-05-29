# Outliner Collection Ops

Bulk include/exclude collections from the active view layer directly from the Outliner. Acts on every collection selected in the Outliner and recursively applies the same include/exclude state to all of their child collections in one step.

## Include All (bl_idname: iops.collections_include)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.collections_include</span>
<span class="mode">Mode: any</span>
<span>Context: OUTLINER (uses `context.selected_ids`)</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

Sets `layer_collection.exclude = False` on every selected collection and all of its descendants in the current view layer.

## Exclude All (bl_idname: iops.collections_exclude)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.collections_exclude</span>
<span class="mode">Mode: any</span>
<span>Context: OUTLINER (uses `context.selected_ids`)</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

Sets `layer_collection.exclude = True` on every selected collection and all of its descendants in the current view layer.

## Overview

Blender's native Outliner toggle for the view-layer exclude checkbox only flips the clicked collection — child collections keep whatever state they had. These two operators walk the selection plus `children_recursive` and apply the same state down the whole subtree, which is what you usually want when staging or hiding large sets of nested collections.

Both operators are `REGISTER`/`UNDO` and produce a single undo step.

## Usage

- Select one or more collections in the Outliner.
- Invoke `iops.collections_include` or `iops.collections_exclude` via search (F3), a custom menu, or a user-defined shortcut.
- No default keymap binding — assign your own if you want a hotkey.

## Notes

- Operates on the active view layer's `layer_collection` tree; other view layers are untouched.
- Selection comes from `bpy.context.selected_ids` filtered to `bpy.types.Collection`. Running outside the Outliner (where `selected_ids` is empty or contains non-collection IDs) is a no-op.
- Matching inside `exclude_layer_col_by_name` is by collection name. Descendants are still covered because they are enumerated explicitly through `children_recursive` before the recursive search runs.
- No properties, no modal, no HUD; no Panel/Menu/PropertyGroup is registered alongside these operators.

## Related

- [Collection Manager Panel](op_outliner_collection_ops.md)
