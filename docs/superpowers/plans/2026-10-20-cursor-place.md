# Cursor Place Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Shift+RMB press-hold-release places the 3D cursor on the nearest vertex / edge midpoint / face centre of the evaluated surface under the mouse, oriented normal-axis + edge-axis, with a live themed preview.

**Architecture:** Pure-python picking/frame math in `utils/cursor_place_core.py` (pytest-covered, no bpy). One modal operator in `operators/iops_cursor.py` does one `scene.ray_cast` per mouse move, feeds the hit polygon's vertices to the core, caches the result for the draw callbacks, and writes `scene.cursor.matrix` on release.

**Tech Stack:** bpy modal operator, `utils.picking.raycast_from_mouse`, `ui.draw` primitives + `Role` theme, `ui.hud` overlays, pytest for the core.

**Spec:** `docs/superpowers/specs/2026-10-20-cursor-place-design.md`

## Global Constraints

- No bmesh anywhere in the hot path; read the evaluated `Mesh` directly.
- Per mouse move: one raycast, one polygon's vertices projected, nothing else.
- `region.tag_redraw()` only when the pick result changed.
- Theme roles only: `Role.CLOSEST_POINT`, `Role.CLOSEST_LINE`, `Role.GHOST_CLOSEST`, `axis_color()`; no new theme fields.
- Default binding exactly: `("iops.cursor_place", "RIGHTMOUSE", "PRESS", False, False, True, False)`.
- Prefs: `cursor_place_normal_axis` (Z), `cursor_place_edge_axis` (X), `cursor_place_axis_size` (60 px, 10..400).
- Commit via `scene.cursor.matrix`; `bl_options = {"REGISTER", "UNDO"}`.
- Repo conventions: commit on master, English code/comments, one squash before push.

## Review Focus

1. Degenerate reference edge (coincident polygon verts): frame must still build (fallback perpendicular), never raise into the modal. → Task 1 `test_build_frame_degenerate_edge_falls_back`.
2. Ray misses everything: release places the cursor on the view plane through the old cursor and keeps its rotation; preview shows nothing. → Task 3 MCP check.
3. Hit on a collection instance: position/normal use the instance matrix, not the source object's. → Task 3 MCP check with an offset instance.
4. Mouse released outside the region / window deactivated: operator must finish or cancel and remove draw handlers. → Task 3 handles `RIGHTMOUSE RELEASE` anywhere and `WINDOW_DEACTIVATE` as cancel; MCP checks handler count returns to baseline.
5. Negative-scale object: normals via inverse-transpose, frame stays right-handed. → Task 1 `test_build_frame_projects_edge_and_is_right_handed` + Task 3 `nmat` transform + MCP mirrored-cube check.

---

### Task 1: Core math (`utils/cursor_place_core.py`)

**Files:**
- Create: `utils/cursor_place_core.py`
- Test: `tests/test_cursor_place_core.py`

**Interfaces:**
- Consumes: `utils.three_point_core._orthonormal`, `_any_perpendicular`, `_normalized`, `_cross`, `_dot`, `_sub`, `_add`, `_scale`, `DegenerateFrame` (import; do not duplicate).
- Produces:
  - `AXES = ("X", "Y", "Z")`
  - `Pick = namedtuple("Pick", "kind index position normal edge_dir edge")` — `kind` in `("VERT", "EDGE", "FACE")`; `index` = vertex slot (VERT) / edge slot (EDGE; edge i = verts[i]→verts[(i+1)%n]) / None (FACE); `position`, `normal`, `edge_dir` 3-tuples in the caller's space; `edge = (a, b)` endpoints of the reference edge.
  - `dist2(p, q) -> float`
  - `point_segment_dist2(p, a, b) -> float`
  - `pick_element(verts3d, verts2d, mouse, *, poly_normal, poly_center, poly_center2d, vert_normals) -> Pick` — nearest candidate in 2D among vertices, edge midpoints (`(verts2d[i]+verts2d[i+1])/2`) and `poly_center2d`; ties: vertex beats edge beats face. Reference edge: VERT → of the two incident polygon edges the one with smaller `point_segment_dist2` to the mouse, `edge_dir` from the vertex along it; EDGE → the edge, `edge_dir` toward the endpoint nearer the mouse; FACE → polygon edge with smallest `point_segment_dist2`, `edge_dir` toward the endpoint nearer the mouse. Normal: VERT → `vert_normals[i]`, else `poly_normal`.
  - `other_axis(a, b) -> str`
  - `set_normal_axis(normal_axis, edge_axis, new) -> (normal_axis, edge_axis)` (swap on collision)
  - `cycle_edge_axis(normal_axis, edge_axis) -> str` (the other free letter)
  - `build_frame(normal, edge_dir, normal_axis, edge_axis, *, flip=False) -> (rowX, rowY, rowZ)` — rows are the world directions of local X/Y/Z; det +1; `normal_axis` row = normal (negated when `flip`), `edge_axis` row = edge_dir projected ⟂ normal, third row = ± cross for right-handedness. Degenerate edge (`DegenerateFrame`) → `_any_perpendicular(normal)`.

- [ ] **Step 1: Write the failing tests** `tests/test_cursor_place_core.py`

```python
import math
from utils.cursor_place_core import (pick_element, other_axis, set_normal_axis,
                                     cycle_edge_axis, build_frame)

SQ3 = [(0,0,0),(1,0,0),(1,1,0),(0,1,0)]
SQ2 = [(0,0),(100,0),(100,100),(0,100)]
NRM = [(0,0,1)]*4
C3, C2 = (.5,.5,0), (50,50)

def _approx(a, b, tol=1e-6): return all(abs(x-y) < tol for x, y in zip(a, b))
def _det(m): ...  # 3x3 determinant of rows
def _pick(mouse, vn=NRM):
    return pick_element(SQ3, SQ2, mouse, poly_normal=(0,0,1), poly_center=C3, poly_center2d=C2, vert_normals=vn)

def test_nearest_is_vertex():
    p = _pick((95, 8)); assert p.kind == "VERT" and p.index == 1 and _approx(p.position, (1,0,0))
def test_nearest_is_edge_midpoint():
    p = _pick((97, 50)); assert p.kind == "EDGE" and p.index == 1 and _approx(p.position, (1,.5,0))
    assert _approx(p.edge, ((1,0,0),(1,1,0)))
def test_nearest_is_face_center():
    p = _pick((55, 48)); assert p.kind == "FACE" and p.index is None and _approx(p.position, C3)
def test_face_edge_dir_points_to_nearer_endpoint():
    assert _approx(_pick((60, 30)).edge_dir, (1,0,0))     # bottom edge, toward (1,0,0)
    assert _approx(_pick((40, 30)).edge_dir, (-1,0,0))
def test_edge_dir_points_to_nearer_endpoint():
    assert _approx(_pick((97, 58)).edge_dir, (0,1,0))
    assert _approx(_pick((97, 42)).edge_dir, (0,-1,0))
def test_vertex_uses_vertex_normal_and_nearer_incident_edge():
    vn = [(0,0,1),(0,0,1),(0,0.6,0.8),(0,0,1)]
    p = _pick((98, 80), vn)
    assert p.kind == "VERT" and p.index == 2 and _approx(p.normal, (0,0.6,0.8))
    assert _approx(p.edge_dir, (0,-1,0))                  # right edge nearer than top edge
def test_axis_helpers():
    assert other_axis("Z", "X") == "Y"
    assert set_normal_axis("Z", "X", "X") == ("X", "Z")
    assert set_normal_axis("Z", "X", "Y") == ("Y", "X")
    assert cycle_edge_axis("Z", "X") == "Y" and cycle_edge_axis("Z", "Y") == "X"
def test_build_frame_default_mapping():
    m = build_frame((0,0,1), (1,0,0), "Z", "X")
    assert _approx(m[2], (0,0,1)) and _approx(m[0], (1,0,0)) and _approx(m[1], (0,1,0))
def test_build_frame_projects_edge_and_is_right_handed():
    m = build_frame((0,0,1), (1,0,1), "Y", "X")
    assert _approx(m[1], (0,0,1)) and _approx(m[0], (1,0,0)) and math.isclose(_det(m), 1.0, abs_tol=1e-9)
def test_build_frame_flip_keeps_edge_axis():
    m = build_frame((0,0,1), (1,0,0), "Z", "X", flip=True)
    assert _approx(m[2], (0,0,-1)) and _approx(m[0], (1,0,0)) and math.isclose(_det(m), 1.0, abs_tol=1e-9)
def test_build_frame_degenerate_edge_falls_back():
    m = build_frame((0,0,1), (0,0,0), "Z", "X")
    assert math.isclose(_det(m), 1.0, abs_tol=1e-9) and _approx(m[2], (0,0,1))
```

- [ ] **Step 2: Run** `python -m pytest tests/test_cursor_place_core.py -q` → FAIL (ModuleNotFoundError).
- [ ] **Step 3: Implement** `utils/cursor_place_core.py` per Interfaces. Return plain float tuples.
- [ ] **Step 4: Run** the test file → all PASS.
- [ ] **Step 5: Commit** `feat(cursor-place): Pure picking and frame math`.

---

### Task 2: Prefs, keymap routing, default binding

**Files:**
- Modify: `prefs/addon_preferences.py` (props near `cursor_bisect_snap_threshold` ~L711; UI next to the cursor-bisect row ~L1117)
- Modify: `utils/functions.py:680-697` (`keymap_name_for_idname`)
- Modify: `prefs/hotkeys_default.py` (after the `object_drag_snap_cursor` line)
- Modify: `tests/smoke_register.py`

**Interfaces:**
- Prefs `cursor_place_normal_axis`, `cursor_place_edge_axis` (EnumProperty X/Y/Z, defaults Z / X), `cursor_place_axis_size` (IntProperty 60, 10..400, subtype PIXEL). Update callbacks: if the two letters collide after a change, the untouched prop takes the letter the changed prop just gave up (module-level `_guard` flag prevents recursion).
- Keymap: `idname.startswith("iops.cursor_place")` → `"3D View"`, inserted before the `iops.object` clause.
- Binding line in `keys_default`: `("iops.cursor_place", "RIGHTMOUSE", "PRESS", False, False, True, False)`.

- [ ] **Step 1:** Append to `tests/smoke_register.py`: `assert hasattr(bpy.ops.iops, "cursor_place")`; `for p in ("cursor_place_normal_axis", "cursor_place_edge_axis", "cursor_place_axis_size"): assert hasattr(prefs, p)`. (The op assert passes only after Task 3.)
- [ ] **Step 2:** Add the three props + swap callbacks + a "Cursor Place" row in the prefs UI (normal axis, edge axis, axis size).
- [ ] **Step 3:** Add the routing clause and the `keys_default` line.
- [ ] **Step 4:** Verify over MCP (blender-mcp skill): reload addon; `prefs.cursor_place_normal_axis = "X"` → `prefs.cursor_place_edge_axis == "Z"`; `keymap_name_for_idname("iops.cursor_place") == "3D View"`.
- [ ] **Step 5: Commit** `feat(cursor-place): Prefs, keymap routing and default binding`.

---

### Task 3: Modal operator (`operators/iops_cursor.py`) + registration

**Files:**
- Create: `operators/iops_cursor.py`
- Modify: `__init__.py` (import + register next to `IOPS_OT_DragSnapCursor`)

**Interfaces:**
- Consumes: Task 1 API; `utils.picking.raycast_from_mouse(context, (mx, my))` → `(hit, loc, nrm, face_index, obj, matrix)`; `ui.draw.primitives.points/edges_3d/tris/polyline`, `ui.draw.draw_scope`, `ui.draw.theme.get_theme/axis_color/Role`, `ui.draw.safe_handler_add/remove`; `ui.hud` pieces as in `drag_snap_cursor.py`; `bpy_extras.view3d_utils.location_3d_to_region_2d`, `region_2d_to_location_3d`; `blf` for axis letters.
- Produces: `IOPS_OT_CursorPlace` — `bl_idname = "iops.cursor_place"`, `bl_label = "IOPS Cursor Place"`, `is_bindable = True`, `bl_options = {"REGISTER", "UNDO"}`.

- [ ] **Step 1: Skeleton.** `poll`: `context.area.type == "VIEW_3D"` and `context.mode in {"OBJECT", "EDIT_MESH"}`. `invoke`: read prefs into `self._normal_axis / _edge_axis / _axis_px`; `self._flip = False`; `self._mesh_cache = {}`; `self._pick = None`; `self._sig = None`; `self._mouse = (event.mouse_region_x, event.mouse_region_y)`; add POST_VIEW `_draw_3d` and POST_PIXEL `_draw_hud` with `safe_handler_add`; `_update(context, event)`; `modal_handler_add`.
- [ ] **Step 2: `_update(context, event)`.** Raycast at the mouse. On hit: `key = obj.as_pointer()`; cache `(mesh, nmat)` per key where `mesh = obj.data` (obj is evaluated; if `not obj.is_evaluated`, use `obj.evaluated_get(depsgraph).data`) and `nmat = matrix.inverted_safe().transposed().to_3x3()` — recompute `nmat` per hit since instance matrices differ per hit even for one mesh (cache only `mesh`). `poly = mesh.polygons[face_index]`; `verts3d = [matrix @ mesh.vertices[i].co for i in poly.vertices]`; `verts2d` via `location_3d_to_region_2d`, a `None` projection becomes `(1e9, 1e9)`; `poly_center = matrix @ poly.center`, `poly_center2d` likewise; `poly_normal = (nmat @ poly.normal).normalized()`; `vert_normals = [(nmat @ mesh.vertex_normals[i].vector).normalized() for i in poly.vertices]`. `pick = pick_element(...)`; `frame = build_frame(pick.normal, pick.edge_dir, self._normal_axis, self._edge_axis, flip=self._flip)`; `px_world = (region_2d_to_location_3d(region, rv3d, (mx+1, my), pos) - pos).length`. Store `self._pick = (pick, frame, verts3d, px_world)`; on miss `None`. Signature `(key, face_index, pick.kind, pick.index, normal_axis, edge_axis, flip, round(px_world, 6))` → `region.tag_redraw()` only when it changed.
- [ ] **Step 3: `modal`.** HUD/help toggle handling first (copy from drag_snap_cursor). Then: `MOUSEMOVE`/`INBETWEEN_MOUSEMOVE` → `_update`; `X/Y/Z` PRESS → `set_normal_axis`, `_update`; `F` PRESS → toggle `_flip`, `_update`; `WHEELUPMOUSE`/`WHEELDOWNMOUSE` PRESS → `cycle_edge_axis`, `_update` (consumed); `RIGHTMOUSE RELEASE` → `_commit` → `FINISHED`; `ESC` PRESS or `WINDOW_DEACTIVATE` → `_cleanup` → `CANCELLED`; else `RUNNING_MODAL`.
- [ ] **Step 4: `_commit(context)`.** Hit: `R = Matrix((rowX, rowY, rowZ)).transposed()` (rows are local-axis world dirs → columns of the rotation); `scene.cursor.matrix = Matrix.Translation(pos) @ R.to_4x4()`. Miss: `pos = region_2d_to_location_3d(region, rv3d, self._mouse, scene.cursor.location)`; `scene.cursor.matrix = Matrix.Translation(pos) @ scene.cursor.matrix.to_3x3().to_4x4()`. Then `_cleanup` (remove handlers, `tag_redraw`).
- [ ] **Step 5: `_draw_3d`.** Only reads `self._pick`. Inside `draw_scope(blend="ALPHA", depth="NONE", face_culling="NONE")`: FACE → `tris` fan of `verts3d` with `Role.GHOST_CLOSEST` + closed `polyline` outline `Role.CLOSEST_LINE`; EDGE → `edges_3d([a, b])` `Role.CLOSEST_LINE`; VERT → `points([pos])` `Role.CLOSEST_POINT`. Axis ghost: `L = self._axis_px * px_world`; for each letter draw `edges_3d([pos, pos + row * L * (1.0 if letter in (normal_axis, edge_axis) else 0.6)], color=axis_color(letter), width="axis_gizmo")` plus a 6 px tip point. `_draw_hud`: letters at the projected tips via `blf` in the axis colour, then help/HUD.
- [ ] **Step 6: HUD/Help.** `HUDOverlay("cursor_place")` title "Cursor Place"; help rows: Normal axis "X / Y / Z", Flip normal "F", Edge axis "Wheel", Confirm "Release RMB", Cancel "Esc", Help "H". HUD params: Snap (VERT/EDGE/FACE/—), Normal axis, Edge axis, Flip.
- [ ] **Step 7: Registration** in `__init__.py`.
- [ ] **Step 8: Verify over MCP** (blender-mcp skill; FakeOp/fake-event pattern from memory `project_three_point_rotation`): reload addon; scene with a cube at (3,0,0) rotated 30° about Z, a mirrored copy (`scale.x = -1`), and a collection instance of the cube at (0,5,0); `temp_override` on a VIEW_3D region; drive `invoke`/`modal` with fake events whose `mouse_region_x/y` come from `location_3d_to_region_2d` of known target points:
  - near a vertex → `cursor.location ≈ vertex`, cursor Z ≈ world vertex normal, X ⟂ Z.
  - near an edge midpoint → location ≈ midpoint, X ∥ edge.
  - near a face centre → location ≈ centre, Z ≈ face normal.
  - instance → location in the instance's world space (offset by (0,5,0)).
  - miss (mouse on empty background) → location changed, `cursor.matrix.to_3x3()` unchanged.
  - mirrored cube → `cursor.matrix.to_3x3().determinant() ≈ +1`.
  - `FINISHED` and `CANCELLED` both leave `SpaceView3D` draw-handler count at baseline.
- [ ] **Step 9:** `blender --background --factory-startup --python tests/smoke_register.py` (env per file docstring) → exit 0.
- [ ] **Step 10: Commit** `feat(cursor-place): Surface-snapped oriented cursor modal`.

---

### Task 4: Docs

**Files:**
- Create: `docs/operators/op_cursor_place.md` (format of `op_drag_snap_cursor.md`; image `../img/ops/op_cursor_place.png` to be captured later with the screenshot harness)
- Modify: `docs/operators.md` (bullet after Drag Snap Cursor), `docs/index.md:74`, `mkdocs.yml:155`, `docs/preferences.md` (Cursor Place: three settings)

- [ ] **Step 1:** Write the page: intro, **Hotkey** Shift+RMB (hold), Controls table (X/Y/Z, F, Wheel, release, Esc, H), Tips (nearest-wins snapping; shadows Blender's own Shift+RMB; evaluated surface incl. instances).
- [ ] **Step 2:** Nav/index links and the prefs paragraph.
- [ ] **Step 3: Commit** `docs(cursor-place): Operator page and prefs`.

---

### Task 5: Squash

- [ ] Use `squash-feature-commits` to fold the spec/plan commits and Tasks 1–4 into one `feat(cursor-place): Surface-snapped, oriented 3D cursor on Shift+RMB`. Do not push.

---

### Task 6 (added after review): Fix pass + slide mode

Done inline per the ledger: `slide_element` in core (tests `test_slide_*`), vertex normal = hit face normal (`test_vertex_uses_hit_face_normal_and_nearer_incident_edge`), zero-normal guard (`test_build_frame_zero_normal_falls_back`); operator: always-fresh pick, trigger key, out-of-region release, RMB-select pass-through, raw-hit fallback, owner cache, tessellated fill, `is_repeat`; docs updated. Verified over MCP + smoke + pytest.
