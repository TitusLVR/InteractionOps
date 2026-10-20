# Cursor Place — Surface-Snapped, Oriented 3D Cursor — Design

**Date:** 2026-10-20
**Status:** Approved in chat (2026-10-20); revised the same day to a single Shift+RMB binding with nearest-element auto snap

## Intent

Blender's Shift+RMB puts the 3D cursor on a surface but gives no useful
orientation and no snapping to mesh elements. Nearly every iops pivot
tool (Object Rotate, Mirror Rotate, Three Point Rotation, Drag Snap
Cursor, Cursor Bisect) starts from the cursor, so a cursor that lands
exactly on a vertex / edge midpoint / face centre with an axis along the
normal and an axis along the nearest edge removes a whole class of
"align the cursor first" steps.

## User-facing behaviour

### Invocation

One hotkey: **Shift + RMB**, press-hold-release, in the 3D viewport,
object mode and mesh edit mode alike. Press starts a modal with a live
preview; while the button is held the preview follows the mouse.
**Release** commits the cursor. **Esc** cancels (cursor untouched). The
default Blender Shift+RMB binding is shadowed by the addon keymap; the
binding is user-rebindable through the iops Keymaps prefs (idname
`iops.cursor_place`).

### Picking

Edit mode snaps to the **evaluated** mesh (modifier result), same as
object mode — not the cage. This is what "with modifiers" means here and
keeps one picking path. (My call.)

- One `scene.ray_cast` per mouse move against the evaluated depsgraph.
  Hits include collection instances and modifier results (the ray hits
  evaluated geometry; the returned object + matrix are the instance's).
- The hit polygon is the search domain. The cursor snaps to the nearest
  **candidate point in screen space** among:
  - every vertex of the polygon
  - the midpoint of every polygon edge
  - the polygon centre (evaluated `polygon.center`)
  The winner decides the element kind (VERT / EDGE / FACE); no
  thresholds, no modifier keys — "nearest wins".
- **Miss** (ray hits nothing): no element preview. Release places the
  cursor the way Blender does — at the mouse on the view-aligned plane
  through the current cursor location — and keeps the cursor rotation.
  (My call.)

### Orientation

Two axes are mapped, the third follows by right-hand rule:

- **Normal axis** (pref, default **Z**): points along the element normal
  - face: polygon normal
  - edge: hit-polygon normal (one polygon is all the raycast gives for
    free; averaging with the opposite face would need an edge→poly map
    over the whole mesh — rejected for speed)
  - vertex: evaluated vertex normal
- **Edge axis** (pref, default **Y**): parallel to the reference edge,
  projected into the plane orthogonal to the normal axis, oriented so it
  points from the element toward the edge endpoint nearest the mouse.
  Reference edge:
  - face: polygon edge nearest the mouse
  - edge: the edge itself
  - vertex: of the two polygon edges incident to the vertex, the one
    nearer the mouse

Normal axis and edge axis are different by construction (prefs
validate; choosing the same letter for both swaps them).

In-modal overrides (not persisted): **X / Y / Z** set the normal axis;
if that collides with the edge axis they swap. **F** flips the normal
axis (the frame stays right-handed, so the edge axis is kept and the
third flips). **Wheel** cycles the edge axis through the two remaining
letters.

### Preview

Drawn with the iops draw framework and theme roles:

- Element under the mouse:
  - vertex: point, `Role.CLOSEST_POINT`
  - edge: segment, `Role.CLOSEST_LINE`
  - face: polygon outline `Role.CLOSEST_LINE` + translucent fill
    `Role.GHOST_CLOSEST`
- Cursor ghost at the snap position: three axis lines in Blender's
  `axis_x/y/z` theme colours (`ui.draw.theme.axis_color`), the normal
  axis and edge axis full length, the derived third axis at 60 %, plus
  the letters at the tips. Length = `cursor_place_axis_size` pixels
  (pref, default 42), converted to world units at the snap point so the
  gizmo is screen-constant.
- Depth test off (always visible). Small HUD/Help via `ui.hud`, same
  pattern as `drag_snap_cursor` (H toggles).

### Commit

`scene.cursor.matrix = Matrix.Translation(pos) @ frame.to_4x4()` — this
respects whatever rotation mode the cursor uses. `bl_options
{REGISTER, UNDO}`; FINISHED pushes one undo step; CANCELLED pushes none.

## Preferences

In `IOPS_AddonPreferences` (new "Cursor Place" block near the
cursor-bisect settings):

- `cursor_place_normal_axis` Enum X/Y/Z, default Z
- `cursor_place_edge_axis` Enum X/Y/Z, default Y (update callbacks keep
  them distinct by swapping)
- `cursor_place_axis_size` Int px, default 42, 10..400
- `cursor_place_axis_letters` Bool, default True (draw X/Y/Z at the tips)

Highlight colours / widths come from the theme; no new theme fields.

## Performance constraints

- No bmesh. Read the evaluated `Mesh` directly: `polygons[i].vertices`,
  `vertices[j].co`, `vertex_normals[j].vector`, `polygons[i].normal /
  center`. At most one polygon's worth of vertices is touched per event.
- Per-modal cache keyed by the evaluated object pointer → `(mesh,
  matrix)` so repeated hits on the same object do no lookups.
- Screen projection only of the polygon's vertices (≤ N-gon size).
- `region.tag_redraw()` only when the preview result changed (element
  identity, position, or frame).
- Draw callback builds batches from a precomputed small list; no scene
  queries inside the draw handler.

## Code layout

- `operators/iops_cursor.py`: the modal `IOPS_OT_CursorPlace`
  (`iops.cursor_place`, `is_bindable = True`).
- `utils/cursor_place_core.py`: pure math — pick element in polygon,
  build frame from (normal, edge dir, axis letters, flip). Unit-testable
  without a viewport (fake region projection callable).
- `utils/functions.keymap_name_for_idname`: `iops.cursor_place*` →
  "3D View" (RMB must not live in the Window keymap).
- `prefs/hotkeys_default.py`: one default entry, Shift + RIGHTMOUSE PRESS.
- Register in `__init__.py`.

## Non-goals

- No persistent tool / gizmo; this is a one-shot modal.
- No snapping to curves, metaballs, text or non-mesh evaluated types
  (ray_cast only returns mesh hits anyway).
- No "cursor to selection" or multi-element averaging.
- Edge normal averaging across adjacent faces (see above).

## Open to the builder

- Exact HUD content.
- Whether the face fill uses the two-pass depth trick from Mirror
  Rotate or a plain alpha fill (depth is off, so plain is expected).

## Revision 2026-10-20 (after review + user request)

- **Slide mode (user request):** while **Shift is held** the cursor follows
  the mouse continuously: projected onto a polygon edge when within the
  snap threshold (`cursor_bisect_snap_threshold`, the addon's canonical
  px tolerance) of one, otherwise free on the face at the raycast hit
  point. Shift released (RMB still down) = the snap behaviour above. The
  modal starts in slide mode because Shift is down at invoke.
- **Vertex orientation (user request):** the normal axis on a vertex
  comes from the face under the mouse (hit polygon normal), not the
  averaged vertex normal; the edge axis from the nearer incident edge.
- Review fixes: the freshest pick is always kept (signature only gates
  the redraw) so the edge axis follows the mouse within one element;
  confirm key = whatever invoked the operator (rebinding works); release
  outside the region keeps the last in-region preview; Shift+RMB passes
  through for right-click-select keymaps; non-mesh hits (curves, text)
  and hit polygons that do not contain the hit point fall back to a FACE
  pick at the raw ray hit; `raycast_from_mouse(owner_cache=...)` memoises
  instance ownership per modal; face fill is tessellated once per pick;
  zero normals fall back instead of raising; key auto-repeat is ignored.
- **Ctrl / Alt in the modal (user request, same day):** Ctrl held locks
  the position and element at the first Ctrl move and aims the edge axis
  at the mouse (mouse ray intersected with the tangent plane, projected
  perpendicular to the normal; `aim_edge_dir`). Alt held keeps the
  position following the mouse but freezes (normal, edge_dir) from the
  first Alt move; X/Y/Z/F/wheel still remap the frozen frame. Ctrl wins
  over Alt. Releasing the modifier returns to normal following.
