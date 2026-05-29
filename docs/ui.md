# UI Overview

InteractionOps ships its UI as a mix of pop-up panels, sidebar panels, pie menus and a dedicated floating window for modifiers. Most surfaces are bound to a `Call_*` operator so they can be invoked from a keymap entry rather than living permanently in the N-panel.

This section is the hub. Detailed reference is split across two pages:

- [Menus, Panels and Windows](ui/ui_menus.md) — the IOPS TPS pop-up, the Data panel, the Transform panel, the Collection Append panel, the Object Color sidebar panel, the Vertex Color sidebar panel and the floating Modifier window.
- [Pie Menus](ui/ui_pies.md) — the main IOPS pie, the Edit pie (object-type aware), the Asset Management pie and the Area Split pie.

## Top-level surface categories

<div class="iops-meta" markdown="1">
<span class="key">Addon: InteractionOps</span>
<span class="mode">Context: VIEW_3D, IMAGE_EDITOR, UV</span>
<span>Tab: iOps (for docked sidebar panels)</span>
</div>

| Category | Surface kind | Entry operator |
|---|---|---|
| Transformation / Pivot / Snap | Pop-up panel | `iops.call_panel_tps` |
| Object Data (UV/Color/VG/Mat) | Pop-up panel | `iops.call_panel_data` |
| Object Transform | Pop-up panel | `iops.call_panel_tm` |
| Collection Append from linked | Sidebar panel | `iops.call_panel_collection_append` |
| Object Color picker + recents | Sidebar panel | (N-panel, iOps tab) |
| Vertex Color helpers | Sidebar panel | (N-panel, iOps tab) |
| Floating Modifier window | Native window | `iops.window_modifiers` |
| Main IOPS pie | Pie menu | `iops.call_pie_menu` |
| Edit-mode / type-aware pie | Pie menu | `iops.call_pie_edit` |
| Asset management pie | Pie menu | `iops.call_pie_assets` |
| Area split pie | Pie menu | `iops.call_pie_split` |

All `iops.call_*` operators are bound by default — see the per-page meta blocks for exact chord. The default keymap is in `prefs/hotkeys_default.py`.

## Conventions used in the reference pages

- `bl_idname` values for every surface and for any operator wired into it.
- Cardinal slots (N/NE/E/SE/S/SW/W/NW) for every pie.
- Object-type / mode behaviour for surfaces that change based on `context.object.type` or `context.mode`.
- Default keymap binding sourced from `prefs/hotkeys_default.py` (or "no default binding" when nothing matches).
