# Operators

Every iOps tool on one page. Most tools are reached through the F1–F5 keys, the pies or a hotkey you assign in *Preferences › iOps › Keymaps*; each page tells you how.

## Core System
- [iOps Dispatcher](operators/op_iops.md) — the brain behind F1–F5: does the right thing for the current object and mode.
- [Modes (F1–F5)](operators/op_modes.md) — what each F-key does per object type.
- [UI Toggles](operators/op_ui_toggles.md) — the help-legend and HUD-parameter toggle keys.
- [Draw Theme Preview](operators/op_draw_theme_preview.md) — preview every HUD colour in the viewport while tuning the theme.

## Object — Alignment
- [Align Between Two](operators/op_align_between_two.md) — put the active object halfway between two others.
- [Align Origin to Normal](operators/op_align_origin_to_normal.md) — rotate the origin to match a face normal.
- [Align Object to Face](operators/op_object_align_to_face.md) — pick a face and sit the object on it.
- [Object Aligner](operators/op_object_aligner.md) — match objects to a reference by shape, with ghost preview.
- [Drop It](operators/op_object_drop_it.md) — drop objects onto whatever is below them.

## Object — Transform
- [Three Point Rotation](operators/op_object_three_point_rotation.md) — rotate by picking pivot, start and end points.
- [Object Rotate (XYZ ±)](operators/op_object_rotate.md) — rotate by a fixed angle with the arrow keys.
- [Object Normalize](operators/op_object_normalize.md) — clear rotation and scale, keep the look.
- [Match Transform Active](operators/op_object_match_transform_active.md) — copy the active object's transform to the selection.
- [Change Scale](operators/op_object_change_scale.md) — scale the selection by a typed factor.
- [Cursor Rotate](operators/op_cursor_rotate.md) — spin the 3D cursor in steps.

## Object — Utilities
- [Auto Smooth](operators/op_object_auto_smooth.md) — smooth-by-angle shading for the selection.
- [KitBash Grid](operators/op_object_kitbash_grid.md) — lay kitbash pieces out on a grid or gather them at the centre.
- [Name from Active](operators/op_object_name_from_active.md) — rename the selection after the active object.
- [Select Similar Name](operators/op_object_select_similar_name.md) — select objects sharing the active object's name stem.
- [Replace](operators/op_object_replace.md) — swap selected objects for the active one.
- [UVMaps Add/Remove](operators/op_object_uvmaps_add_remove.md) — add or remove UV maps across the selection.
- [UVMaps Cleaner](operators/op_object_uvmaps_cleaner.md) — keep only the first N UV maps.
- [Visual Origin](operators/op_object_visual_origin.md) — set the origin to a bounding-box point by clicking it.
- [Object Color](operators/op_object_color.md) — viewport colour with a recent-colours row.
- [Radial Array](operators/op_object_radial_array.md) — array copies around the 3D cursor.

## Mesh — Selection
- [Z Ops (Loop/Ring, Connect, Delete, etc.)](operators/op_z_ops.md) — grow / shrink loops and rings, connect, line up, equalize, mirror, smart delete.
- [Mouseover Fill Select](operators/op_mouseover_fill_select.md) — flood-select the region under the mouse.
- [Convert Selection](operators/op_mesh_convert_selection.md) — switch vertex / edge / face selection with Alt+F1–F3.
- [Selection Sets](operators/op_selection_sets.md) — save and recall named mesh selections.

## Mesh — Editing
- [Mesh to Grid](operators/op_mesh_to_grid.md) — snap selected vertices to the grid.
- [Cursor Bisect](operators/op_mesh_cursor_bisect.md) — cut the mesh with a plane placed at the cursor.
- [Smart Inset](operators/op_mesh_smart_inset.md) — straight-skeleton inset that stays clean in corners.
- [Extrude (Keep Edge Data)](operators/op_mesh_extrude_ex.md) — extrude while keeping creases, bevel weights and seams.
- [Straight Bevel](operators/op_mesh_straight_bevel.md) — bevel with straight, even segments.
- [Shear](operators/op_mesh_shear.md) — shear the selection around a hinge you pick.
- [Hinge](operators/op_mesh_hinge.md) — rotate the selection around a picked edge.
- [Converge](operators/op_mesh_converge.md) — pull selected vertices together toward a target.
- [Vert Fuse](operators/op_mesh_vert_fuse.md) — merge vertices onto a picked vertex.
- [Mesh Snapshot](operators/op_mesh_snapshot.md) — copy selected faces into new objects in the iops_mesh_snapshot collection.
- [Quick Connect](operators/op_mesh_quick_connect.md) — connect selected vertices across faces.
- [Tris → Quads](operators/op_mesh_to_tris_to_quad.md) — triangulate and re-quad in one go.

## Mesh — Utilities
- [Copy Edges Angle](operators/op_mesh_copy_edges_angle.md) — copy the angle between two edges onto others.
- [Copy Edges Length](operators/op_mesh_copy_edges_length.md) — make edges the same length as the active one.
- [Bevel Edge Data Fix](operators/op_bevel_edge_data_fix.md) — repair bevel weights and sharp marks after edits.
- [Quick Snap (Mesh)](operators/op_mesh_quick_snap.md) — snap mesh elements point to point.
- [UV Channel Hop](operators/op_mesh_uv_channel_hop.md) — cycle the active UV map on the selection.
- [Assign Vertex Color](operators/op_assign_vertex_color.md) — paint the selection with a colour or alpha.
- [Mesh Visual UV](operators/op_mesh_visual_uv.md) — draw the UVs on the mesh in the viewport.
- [UV Visual Cursor](operators/op_uv_visual_cursor.md) — place the 2D cursor on a bounding-box point.
- [Non-Planar Overlay](operators/op_mesh_nonplanar_overlay.md) — highlight faces that are not flat.
- [UV Shortest Mark](operators/op_mesh_uv_shortest_mark.md) — mark seams along the shortest path.

## Snap & Transform
- [Drag Snap](operators/op_drag_snap.md) — move objects vertex to vertex.
- [Drag Snap Cursor](operators/op_drag_snap_cursor.md) — the same, driven by the 3D cursor.
- [Drag Snap UV](operators/op_drag_snap_uv.md) — move UVs vertex to vertex.
- [Snap Combos](operators/op_snap_combos.md) — eight memory slots for snap settings.

## Grid
- [Grid from Active](operators/op_grid_from_active.md) — snap objects to a grid sized by the active object.

## Modifiers
- [Easy Mod — Array](operators/op_easy_mod_array.md) — capped arrays and array-along-curve in a few keys.
- [Easy Mod — Curve](operators/op_easy_mod_curve.md) — wire a Curve modifier between a mesh and a curve.
- [Easy Mod — Shwarp](operators/op_easy_mod_shwarp.md) — shrinkwrap the selection to the active object.

## Curve
- [Spline Type](operators/op_curve_spline_type.md) — Poly / Bezier / NURBS with F1–F3.
- [Subdivide](operators/op_curve_subdivide.md) — subdivide bezier segments with a live preview.

## Interface
- [Split Screen Area](operators/op_split_screen_area.md) — open and close a paired editor (legacy version).
- [Split Screen Area (New)](operators/op_split_screen_area_new.md) — the current area toggler behind the Split pie.
- [Save/Load Space Data](operators/op_save_load_space_data.md) — remember and restore how an editor is trimmed.
- [Active Object Scroll](operators/op_ui_prop_switch.md) — cycle the active object through the selection.
- [Maya Isolate](operators/op_maya_isolate.md) — isolate the selection Maya-style.

## Collection
- [Outliner Collection Ops](operators/op_outliner_collection_ops.md) — exclude, remove-keep-objects and other Outliner shortcuts.
- [Instance Collection Append](operators/op_instance_collection_append.md) — make linked collections local.

## Assets
- [Asset Management](operators/op_assets_management.md) — mark, clear, catalog and library switching.
- [Open Asset in Current Blender](operators/op_open_asset_in_current_blender.md) — open the asset's source file here.
- [Open Asset in New Blender](operators/op_open_asset_in_new_blender.md) — open it in a second Blender.
- [Render Asset Thumbnail](operators/op_render_asset_thumbnail.md) — render a preview for the active asset.

## Material & Texture
- [Material Override](operators/op_material_override.md) — view layer material override from a list.
- [Materials from Textures](operators/op_materials_from_textures.md) — build materials from texture names.
- [Image Reload](operators/op_image_reload.md) — reload every image in the file.
- [Library Reload](operators/op_library_reload.md) — reload every linked library.

## Scripting
- [Executor](operators/op_executor.md) — run your own scripts from a popup list.
- [Run Text](operators/op_run_text.md) — run the active Text Editor script.
