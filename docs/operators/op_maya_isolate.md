# Maya Isolate

Maya-style isolate-selection for the 3D Viewport. In Object Mode it toggles Blender's Local View on the current selection; in Edit Mesh mode it hides unselected geometry and then enters Local View, so the active mesh is focused both at the object and component level in a single step.

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.view3d_maya_isolate</span>
<span class="mode">Mode: Object, Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

## Overview
Blender already has Local View (numpad slash) for objects, but in Edit Mode focusing on a subset of geometry requires a separate Hide step. This operator combines both: one shortcut isolates the active selection regardless of whether you are working at the object or mesh-component level, mirroring Maya's "Isolate Select" workflow.

Running it again in Object Mode toggles Local View off via the standard `view3d.localview` operator. In Edit Mesh mode the hidden geometry persists until you unhide (`Alt+H`); re-running the operator stacks another hide pass and toggles Local View again.

## Usage
- Requires a VIEW_3D area, Object or Edit Mesh mode, an active mesh object, and at least one selected object.
- No default keymap binding. Invoke via F3 search ("IOPS Maya Isolate") or bind it manually in Preferences > Keymap.
- Object Mode: select objects and run to enter/exit Local View on them.
- Edit Mesh: select verts/edges/faces and run to hide the rest and enter Local View.

## Notes
- Edit-Mesh path calls `mesh.hide(unselected=True)` then `view3d.localview(frame_selected=False)`. Hidden components remain hidden after exiting Local View until explicitly unhidden.
- Object path only calls `view3d.localview(frame_selected=False)` — the view is not re-framed on the selection.
- Poll requires the active object to be a MESH; with a non-mesh active object the operator is disabled even if mesh objects are selected.
- Registered as a single class (`IOPS_OT_MayaIsolate`); no panel, menu, or PropertyGroup is registered alongside it.

## Related
- Sibling viewport-focus and visibility operators live under `operators/` — browse the Interface group in the docs nav for neighbours.
