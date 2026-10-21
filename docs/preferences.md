# Preferences

Open *Edit › Preferences › Add-ons › InteractionOps*. The settings are split into four tabs; the two icon buttons next to the tabs save your settings to a file and load them back, so they survive reinstalling the addon.

## Preferences tab
Collapsible sections, top to bottom:

- **General** — name of the sidebar tab (default *iOps*).
- **Statistics Overlay** — master toggle and per-row toggles for the top-left statistics block (file name, dimensions, position, material, modifiers, instances, parent, units, empty mesh).
- **Visual UV** — surface offset and the eight island colours for [Mesh Visual UV](operators/op_mesh_visual_uv.md).
- **Cursor Bisect** — preview depth, snap distance, subdivisions, merge distance and rotation step for [Cursor Bisect](operators/op_mesh_cursor_bisect.md).
- **Cursor Place** — default normal axis (Z) and edge axis (Y), preview axis size (pixels) and whether the X / Y / Z letters are drawn, for [Cursor Place](operators/op_cursor_place.md).
- **Non-Planar Overlay** — thresholds for the [non-planar face overlay](operators/op_mesh_nonplanar_overlay.md).
- **Snap Combo** — which modifier key saves a slot in [Snap Combos](operators/op_snap_combos.md).
- **Modifier Window** — how the floating modifier window is created.
- **Modifiers Panel** — grid layout, per-type defaults and stack options for the [Modifiers panel](ui/ui_menus.md#modifiers).
- **Split Pie Layout** — editor, alternate editor, side and size for each slot of the [Split pie](ui/ui_pies.md#split-pie).
- **Shading Pie Layout** — up to eight viewport shading presets for the [Shading pie](ui/ui_pies.md#shading-pie).
- **Edit Pie Layout** — custom tools for the diagonal slots of the [Edit pie](ui/ui_pies.md#edit-pie).
- **Script Executor** — the scripts folder, columns and name length for the [Executor](operators/op_executor.md).
- **Textures to Materials** — name prefixes and suffixes to strip in [Materials from Textures](operators/op_materials_from_textures.md).
- **Library** — master file and preview size for the iOps asset library.
- **Debug** — verbose console output.

## Keymaps tab
Every iOps hotkey, grouped by area (Main F-keys, Cursor, Object Mode, Mesh, UV Editor, Panels, Pie Menus, Scripts, UI Toggles). Edit a key in place, then use **Save User's Hotkeys** to keep it, **Load User's Hotkeys** to reapply your file, or **Load Default Hotkeys** to reset everything. Tools listed without a key are not bound by default — give them one here.

## Widgets tab
Compose GPU viewport widgets from JSON definitions and assign their toggle hotkeys. See the [Widgets panel](ui/ui_menus.md#widgets).

## Theme tab
Colours, text sizes, panel background, shadow, font, HUD placement, help-legend animation and *Auto-hide after* for the [HUD](ui/ui_hud.md). Auto-hide applies to the help legend of every iOps modal: -1 collapses it right away, 0 keeps it open until <kbd>H</kbd>, a positive value (default 1 s) collapses it after that many seconds; the collapse plays the configured help animation. Pick a bundled preset (Default, Dark+, Light+, Monokai, Blender Default, Solarized Dark), **Save As** your own, **Use Blender Theme HUD Colors** to match your Blender theme, or **Theme Preview** to see every element live in the viewport.

Your settings, hotkeys and themes are stored in your Blender user scripts folder under *presets/IOPS*.
