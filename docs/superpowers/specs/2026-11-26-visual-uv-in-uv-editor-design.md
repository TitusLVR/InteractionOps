# Visual UV in the UV Editor, and the pivot picked on the gizmo

## Intent

`iops.mesh_visual_uv` (Visual UV) draws a transform gizmo for UV islands on the
mesh in the 3D viewport. Two additions:

1. **The same tool as a mode of the UV Editor.** Started in an Image Editor
   that shows the UVs of an edit-mode mesh, the gizmo is drawn in UV space
   around the selected islands and transforms them there, with the same keys.
2. **Choosing where a transform starts from.** A click on any of the nine
   gizmo points (four corners, four side midpoints, centre) makes that point
   the pivot; it is marked, and R / S (keys and the rotation knob) go from it.
   Both in the viewport and in the UV Editor.

## Decisions

### Pivot by click (both places)

- New pivot mode `ANCHOR` next to `CENTER` / `CURSOR`; the point's name is kept
  on the operator. Its UV position is read from the **active** island's
  bounding box when a transform begins, so it follows the island as it moves
  and moves to the new active island. A click on the centre point goes back to
  `CENTER` (the picked point is remembered for P).
- An LMB press on a gizmo point is no longer an immediate drag: it is pending
  until the mouse passes `preferences.inputs.drag_threshold_mouse`. Past it,
  the old behaviour starts (corner / side: scale from the opposite handle;
  centre: move), begun **as of the press position** and then applied with the
  current mouse, so the threshold adds no jump. Released before it: the point
  becomes the pivot.
- The screen centre that angles and scales are measured around is the
  projection of the actual UV pivot onto what the gizmo is drawn on (the mesh
  surface in the viewport, the UV layout in the UV Editor), for every pivot
  mode. The Cursor pivot used to measure around the island centre (rotation
  orbited around a point other than the pivot); it now measures around the
  cursor's point too.
- P cycles Center → Cursor → Anchor (Anchor only once a point was picked). The
  HUD names the pivot in full words ("Top Left Corner", "Left Side"). The
  picked point is drawn with the pivot marker (`Role.PIVOT`, the one the
  centre pivot uses) on its handle, as the C cursor anchor is drawn on its
  handle. Help: "Set Pivot — Click Gizmo Point".
- The pure parts (point positions, labels, cycling, click-or-drag) live in
  `utils/visual_uv_core.py` with pytest coverage.

### UV Editor mode (same operator class)

- `poll` also accepts an `IMAGE_EDITOR` area whose space has `show_uvedit`.
  `invoke` records `_uv_mode`; everything space-specific branches on it. In the
  viewport the behaviour is unchanged apart from the pivot work above (checked
  by replaying one event sequence on the old and the new operator).
- **One projection seam.** In the UV Editor each island's `geo3d` is built from
  the UV layout itself (`get_island_uv_layout_data`: positions `(u, v, 0)`,
  normal +Z) and `_projector` maps it through the editor's View2D. The mapping
  (`ViewMapping`) is fitted from two float `region_to_view` samples (the
  integer `view_to_region` would round the transform maths) and rebuilt on
  every call, so pan and zoom are always current. The gizmo box is the island's
  UV bounding box mapped to pixels (`uv_mode_handles`), `_u_dir` / `_v_dir` are
  exactly the projected bbox width and height; hit testing, handles and the
  transform maths then run through the existing code. No occlusion: every UV is
  visible, the BVH is not built.
- **Drawing.** Island fills and outlines are drawn in `POST_PIXEL` through the
  same projection, not in `POST_VIEW`. The repo's primitives draw whatever
  coordinates they get through the current GPU matrices, and every existing
  Image Editor overlay in the repo (Visual Cursor UV, Drag Snap UV, UV Info
  Rect) draws in `POST_PIXEL` from `view_to_region`; drawing through the one
  mapping the picking and the gizmo use keeps them in exact agreement and does
  not depend on how the editor sets up its view matrix (image aspect).
  Handlers are added to and removed from `SpaceImageEditor`.
- **Direction.** In the viewport the texture follows the mouse, so the UVs
  move, turn and scale the other way; in the UV Editor the island itself
  follows the mouse (grab offset, rotation angle and scale factor are not
  inverted there). The UV-Editor handle maths use the exact UV points while the
  drawn handles sit on a box padded by the Gizmo Padding preference (0 px by default); the press offset is taken out of
  the mouse so a scale starts at 1 and the box edge tracks the mouse.
- **Session islands** are the selected UV islands (`get_uv_selected_islands`,
  UV sync honoured), flooded only over the faces the editor shows (new
  `restrict_to` argument). With UV sync off the mesh face selection is what the
  editor shows, so it is never changed; the UV selection flags of the shown
  faces mirror the session. With sync on the mesh selection mirrors it, as in
  the viewport, and `uv_select_sync_valid` is cleared. Esc puts back the UV
  selection flags and the 2D cursor as well.
- **Picking** an island by click: the shown face whose UV polygon holds the
  mouse's UV position (`face_at_uv`, point-in-triangle in UV space); plain click
  selects only that island, Shift toggles it.
- **UV cursor** is the editor's 2D cursor (the Cursor pivot starts on it, C
  moves it); the editor draws it, so the tool does not draw its own crosshair.
- **First version scope.** Supported: island select / add / remove, G / R / S
  with X / Y, handles, pivot (click, P, C), scope, flip, fit, randomise,
  sensitivity, rotation step, undo / redo, confirm / cancel. Ignored (and left
  out of the help and HUD): Align to Edge, Stitch, pins, Unwrap and its
  options, Straighten Chain, Align View, Pause Modifiers, edge and
  vertex hover / selection. Clean View (Q) is on by default as in the
  viewport: it hides the island fills and outlines; the editor's overlays are
  never touched (hiding them would hide the UV wireframe).
- **Reachability.** The default hotkey lives in the "Mesh" keymap, which the
  Image Editor's main region never reads. A `MIRROR_KEYMAPS` table in
  `utils/functions.py` registers the binding a second time in "UV Editor"; the
  mirror is derived from the primary row, skipped when hotkeys are saved and
  not listed in the preferences. The IOPS UV Tools sidebar panel gets a Visual
  UV button.

## Approaches considered

- **Same operator with a projection seam (chosen).** One gizmo, one set of
  transform maths and keys; the UV Editor differs only in where geometry comes
  from, how it is projected and a few direction / scope switches.
- **A separate UV-editor operator duplicating the gizmo (rejected).** Two
  gizmos, two hit tests and two sets of transform maths to keep in sync; every
  later fix would have to land twice.
- **Extending Visual Cursor UV (rejected).** It places the 2D cursor on a
  bounding-box point and finishes; it is not a transform session (no islands,
  no undo stack, no gizmo), so it would have to grow into Visual UV anyway.

## Not covered by headless tests

The background test drives the real `invoke` / `modal` with a fake Image Editor
and a fake orthographic viewport, but nothing is drawn there, and the real
View2D, region and event routing of a UV Editor window are not exercised.
