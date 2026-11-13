# UV Pipe and UV Stripe Cup Break Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a click-to-break "Cup" sub-mode to the UV Stripe modal, and a new modal operator UV Pipe that unwraps tubes into a straight-perimeter wall, straight cap-ring strips and cap disks.

**Architecture:** Both features sit on the existing UV Stripe layering: a pure-Python core (no bpy) that works on `verts: {vid: (x, y, z)}` / `faces: {fid: (vid, ...)}` dicts, a thin bmesh bridge, and a modal operator with snapshot / re-layout / restore. Cup adds one core function (open a ring at a rung) and a pick sub-mode. Pipe adds a new core (`utils/uv_pipe_core.py`: loop walker, ring-seam detection, part classification, wall and disk layouts), a bridge and an operator, and reuses UV Stripe's ring layout and placement code.

**Tech Stack:** Python, Blender `bpy` / `bmesh` (the user runs 5.3), pytest for pure tests, headless Blender scripts for operator tests, `uvx ruff@0.12.0` for lint.

**Spec:** `docs/superpowers/specs/2026-11-13-uv-pipe-and-stripe-cup-design.md` — read it first; the reference results and acceptance list there are binding.

## Global Constraints

- Core modules (`utils/uv_*_core.py`) import no `bpy`, `bmesh` or `mathutils`.
- Edge key everywhere: the convention of `uv_stripe_select_core._edge` (reuse that function, do not redefine it).
- Positions handed to the cores are world space (`matrix_world @ co`), as UV Stripe does.
- Viewport previews go through `ui/draw` primitives and `Role` only; no raw `gpu` calls.
- UI labels use full words, no abbreviations.
- No change in UV Stripe's layout of open strips or of rings without a picked break. Smart Inset and Smart Edge Slide tests must pass untouched.
- Do not modify `operators/mesh_uv_shortest_mark.py`.
- Nothing committed may contain internal drive paths, studio asset names or the user's mesh data. Fixtures are synthetic.
- The repo has mixed line endings: before editing an existing file run `git ls-files --eol <file>` and keep its ending. New files use LF.
- Lint before each commit: `uvx ruff@0.12.0 check <changed files>`.
- Pure tests: `python -m pytest tests -q`.
- Headless tests: `blender --background --factory-startup --python-exit-code 1 --python tests/blender/<file>.py`, run from PowerShell, with every `BLENDER_USER_*` environment variable pointed at a scratch directory. The checkout directory must be named `InteractionOps` (a feature worktree goes in `.claude/worktrees/InteractionOps`).
- Commit locally per task. Do not push. Before any push the Cup commits are squashed into one and the Pipe commits into one.
- Defaults fixed by the spec: Loop Angle 120°, Sharp Angle 60°, Bend Angle 45°, Split at Bends off, Split at Seams off (Pipe), Pack on, Pipe mode Fit 0–1, Pipe layout Rectangle, loop source Geometry.

## Review Focus

Inputs the spec implies but its acceptance list does not exercise. Each has a test in the task named.

1. **Tube with 4 or 5 sides** — the rim's corner is sharper than Loop Angle 120°, so no ring seam closes. Expected: no exception; the capped box comes out as one FREE part with a warning; lowering Loop Angle to 80° finds the rims. (Task 7)
2. **Tube with open ends (no caps)** — the ends are mesh boundaries, not seams. Expected: one WALL with an automatic seam, laid out as a rectangle. (Task 7)
3. **Closed tube with no ends (torus)** — a non-flat part with no boundary loop. Expected: FREE part with a warning, no exception. (Task 7)
4. **Mesh with no UV layer** — Expected: loop source UV is unavailable and falls back to Geometry; a layer is created; cancel removes it again. (Task 11)
5. **Cup break picked, then the option set changes** (Split at Seams toggled, layout cycled, selection has a second, open strip) — Expected: the break persists across re-layouts, the ring stays one piece, a click on an open strip's rung is ignored. (Task 3)

---

## File Structure

| File | Responsibility |
|---|---|
| `utils/uv_stripe_core.py` (modify) | `Strip.break_edge` field. |
| `utils/uv_stripe_select_core.py` (modify) | `open_ring`. |
| `operators/uv_stripe_bridge.py` (modify) | `prepare_strip(break_edge=)`, break seam in `match_piece_seams`, `apply_maps` extracted from `apply_stripes`. |
| `operators/mesh_uv_stripe.py` (modify) | `cup_breaks` property, pick sub-mode, C / R keys, HUD. |
| `utils/uv_pipe_core.py` (create) | Loop walker, dihedrals, ring seams, part classification, wall seam, analysis, wall and disk layouts. |
| `operators/uv_pipe_bridge.py` (create) | bmesh ↔ core dicts, per-part layout, Blender-unwrap parts, placement, pack, seams. |
| `operators/mesh_uv_pipe.py` (create) | Operator: properties, `execute`, modal. |
| `tests/uv_pipe_fixtures.py` (create) | Synthetic meshes. |
| `tests/test_uv_pipe_core.py` (create) | Pure tests. |
| `tests/blender/test_uv_pipe_operator.py` (create) | Headless tests. |

---

# Part 1 — Cup break in UV Stripe

### Task 1: Open a ring at a rung

**Files:**
- Modify: `utils/uv_stripe_core.py` (`Strip` dataclass, about line 29)
- Modify: `utils/uv_stripe_select_core.py`
- Test: `tests/test_uv_stripe_split.py`, fixtures in `tests/uv_stripe_fixtures.py`

**Interfaces:**
- Produces: `Strip.break_edge: tuple[int, int] | None = None` (edge key of the rung an opened ring was cut at).
- Produces: `open_ring(strip: Strip, rung: int) -> Strip` in `uv_stripe_select_core`. Input: a closed strip. Output: a strip with `closed=False`, rows starting and ending on the rung's two vertices (each row's first id repeated as its last), `sides` set to the rung on both ends, `corner_near` / `corner_far` filled for the repeated ids, `break_edge` set, `seam=None`, `layout` and `height` carried over.

- [ ] **Step 1: Add a flat quad annulus fixture** `flat_annulus(segments=8, outer=1.0, inner=0.5) -> (verts, faces)` to `tests/uv_stripe_fixtures.py` if no equivalent exists there, and a variant `flat_annulus_with_triangle` where one quad is split into two triangles.

- [ ] **Step 2: Write the failing tests** in `tests/test_uv_stripe_split.py`:

```python
def test_open_ring_is_open_and_keeps_every_face():
    strip = strip_from_faces(*flat_annulus(8))
    opened = open_ring(strip, 3)
    assert opened.closed is False
    assert opened.break_edge == rung_edge(strip, 3)
    assert set(opened.faces) == set(strip.faces)
    assert opened.near[0] == opened.near[-1] and opened.far[0] == opened.far[-1]

def test_opened_ring_true_layout_keeps_row_lengths():
    strip = strip_from_faces(*flat_annulus(8, outer=1.0, inner=0.5))
    opened = open_ring(strip, 0); opened.layout = "TRUE"
    uv = stripe_uvs(opened)
    # near row = outer loop: 8 chords of radius 1; far row: 8 chords of radius 0.5
    assert near_row_span(uv, opened) == pytest.approx(16 * math.sin(math.pi / 8), rel=1e-6)
    assert far_row_span(uv, opened) == pytest.approx(8 * math.sin(math.pi / 8), rel=1e-6)

def test_opened_ring_straightens_to_rectangles():
    opened = open_ring(strip_from_faces(*flat_annulus(8)), 0)
    assert straighten(opened) is True
    for face_uvs in uvs_by_face(stripe_uvs(opened)).values():
        assert is_axis_aligned_rectangle(face_uvs)

def test_opened_ring_faces_are_not_flipped():
    opened = open_ring(strip_from_faces(*flat_annulus(8)), 5)
    assert all(signed_area(f) > 0 for f in uvs_by_face(stripe_uvs(opened)).values())
```

Write the small helpers (`near_row_span`, `far_row_span`, `uvs_by_face`, `is_axis_aligned_rectangle`, `signed_area`) in the test file or reuse ones already in the test suite.

- [ ] **Step 3: Run** `python -m pytest tests/test_uv_stripe_split.py -q` — expect FAIL: `open_ring` not defined.

- [ ] **Step 4: Implement.** Add the `break_edge` field with default `None`. Write `open_ring`: rotate the rows so the rung is first (see `ascending_rungs` and `_cut_open`), then append the first id to each row and record the repeated ids for the last face in `corner_near` / `corner_far` — read `stripe_uvs`, `_orient_open` and `_side_v` to see how an open strip's `sides` and corner maps are consumed, and match that.

- [ ] **Step 5: Run** `python -m pytest tests -q` — expect all PASS (existing tests included).

- [ ] **Step 6: Lint and commit** — `feat(uv-stripe): open a closed strip at a chosen rung`.

### Task 2: Break edge through the bridge and the operator's execute path

**Files:**
- Modify: `operators/uv_stripe_bridge.py` (`prepare_strip` ~:189, `match_piece_seams` ~:215)
- Modify: `operators/mesh_uv_stripe.py` (properties ~:150-229, `_pieces` ~:261, `_lay_out` ~:320, `_collect_preview` ~:118)
- Test: `tests/blender/test_uv_stripe_operator.py`

**Interfaces:**
- Consumes: `open_ring`, `Strip.break_edge` (Task 1).
- Produces: `prepare_strip(strip, faces, layout, split_angle, extra_cuts=(), break_edge=None)`. When `strip.closed` and `break_edge` is one of its rungs: the strip is opened there, bend cuts and `extra_cuts` are skipped, the result is exactly one piece, and the piece's layout is `STRAIGHT` when every face is a quad, else the requested layout.
- Produces: operator property `cup_breaks: StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})` — JSON `{"<object name>": [edge_index, ...]}`. It is not a `StripeSettings` field.

- [ ] **Step 1: Write the failing headless tests** (follow the file's `TESTS` list and helper style):

```python
def test_cup_break_ring_is_one_piece_despite_bend_split():
    # flat 8-segment quad annulus, all faces selected, split_at_bends=True, split_angle=5°
    # cup_breaks names one radial edge
    # expect: one UV island; that edge is a seam; no other edge between selected faces is a seam

def test_cup_break_all_quads_is_rectangles_under_no_stretch():
    # same mesh, layout="TRUE": every face's UVs form an axis-aligned rectangle

def test_cup_break_replaces_an_old_seam():
    # annulus with a seam on another radial edge, split_at_seams=True, mark_seams=True
    # expect: one island; the old seam is cleared; the break edge is the only inner seam

def test_cup_break_with_a_triangle_follows_layout():
    # annulus with one quad split into triangles, layout="TRUE":
    # one island, no flipped face, and the faces are NOT all axis-aligned rectangles
    # (the ring is laid out by No Stretch as an open strip would be, not forced to Rectangles)

def test_cup_break_on_an_open_strip_is_ignored():
    # straight 4-quad strip, cup_breaks names an inner cross edge: result identical to no cup_breaks
```

- [ ] **Step 2: Run** the headless file — expect the new tests to FAIL.

- [ ] **Step 3: Implement.** In `_lay_out`, parse `cup_breaks` for the object into edge keys **before** any merge of doubles (resolve to `BMEdge` first so a weld cannot shift the indices). In `_pieces`, when the island builds a closed strip and one of its rungs is a break: drop that island's inner seams from the cuts and call `prepare_strip(..., break_edge=...)`. In `match_piece_seams`, mark a piece's `strip.break_edge` as a seam. In `_collect_preview`, draw `break_edge` with the tears.

- [ ] **Step 4: Run** the headless file and `python -m pytest tests -q` — expect all PASS.

- [ ] **Step 5: Run** `tests/blender/test_smart_inset_uv_stripe.py` and `tests/blender/test_smart_edge_slide.py` headless — expect PASS, unchanged.

- [ ] **Step 6: Lint and commit** — `feat(uv-stripe): lay a ring out from a picked break edge`.

### Task 3: Pick sub-mode, C and R keys, HUD, docs

**Files:**
- Modify: `operators/mesh_uv_stripe.py` (`_modal` ~:564-645, `_build_overlays` ~:505, `_status_text` ~:667, `_draw_callback` ~:686)
- Modify: `docs/operators/op_mesh_uv_stripe.md`
- Test: `tests/blender/test_uv_stripe_operator.py`

**Interfaces:**
- Consumes: `cup_breaks` (Task 2); `utils/picking.py` `raycast_edit_meshes`, `closest_face_edge`.
- Produces on the operator: `_picking: bool`; `_hover_break(context, event) -> tuple[object, int] | None` (object and edge index of the pickable rung under the cursor); `_set_break(context, obj, edge_index)` (replaces any break already stored for the same ring, writes `cup_breaks`, re-lays out, leaves the sub-mode).

- [ ] **Step 1: Write the failing headless tests** using `_OperatorStandIn` and `_KeyPress`:

```python
def test_c_enters_and_leaves_picking():
    # press C -> op._picking is True; press ESC -> op._picking is False and the modal is still running
    # (ESC returned {"RUNNING_MODAL"}, UVs still laid out)

def test_set_break_relays_out_and_leaves_picking():
    # annulus; op._picking = True; op._set_break(ctx, obj, radial_edge_index)
    # -> op._picking is False; one island; that edge is in result.tears

def test_second_break_on_the_same_ring_replaces_the_first():
    # _set_break(edge_a) then _set_break(edge_b): cup_breaks lists only edge_b for that ring

def test_break_survives_option_changes():            # Review Focus 5
    # _set_break, then press S, E, A in turn: after each, still one island cut at the break

def test_r_changes_seed_and_c_does_not():
    # press R -> offset_seed == 1; press C -> offset_seed unchanged

def test_cancel_after_break_restores_uvs_and_seams():
    # _set_break, then RMB outside picking: UVs and seam flags equal the pre-invoke snapshot, cup_breaks == ""
```

Update `test_modal_hud_and_help_list_every_key` for the new rows ("Break Ring (C)", "Offset Seed (R)") and the status text; update `test_modal_old_letters_are_free` to drop R.

- [ ] **Step 2: Run** the headless file — expect the new and updated tests to FAIL.

- [ ] **Step 3: Implement the sub-mode.** In `_modal`, before the `event.value != "PRESS"` early return: while `_picking`, MOUSEMOVE updates the hover; LMB press calls `_set_break` on the hover (no hover: stay in picking); RMB / ESC clear `_picking`; navigation events still pass through; every other key is swallowed. HUD and help drag handling keeps its place ahead of this. C toggles `_picking`; R takes the seed increment. Pickable edges are only rungs of closed strips in the current result — keep the per-object set of such edge indices from the last `_lay_out`.

- [ ] **Step 4: Draw.** Hovered rung with `Role.ACTIVE_LINE`, existing breaks with `Role.ERROR_LINE` (they are already in `tears`), through `draw.edges_3d`. HUD: a "Break Ring (C)" row showing the picking state; rename the seed row to "Offset Seed (R)". Help overlay and status text likewise.

- [ ] **Step 5: Update** `docs/operators/op_mesh_uv_stripe.md`: the key table (C, R) and a short "Breaking a ring" section stating the all-quads rule.

- [ ] **Step 6: Run** the headless file and `python -m pytest tests -q` — expect all PASS.

- [ ] **Step 7: Lint and commit** — `feat(uv-stripe): pick a ring's break edge in the modal (C), seed on R`.

---

# Part 2 — UV Pipe

### Task 4: Fixtures, dihedrals and the loop walker

**Files:**
- Create: `tests/uv_pipe_fixtures.py`, `utils/uv_pipe_core.py`, `tests/test_uv_pipe_core.py`

**Interfaces:**
- Produces (fixtures), each returning `(verts, faces)`:
  - `capped_cylinder(sides=32, rows=4, radius=1.0, height=2.0, bottom_rings=(0.671, 0.493), top_rings=(0.671,))` — bottom centre is a triangle fan, top centre an n-gon (spec Reference A).
  - `open_tube(sides=12, rows=4)` — no caps.
  - `bent_pipe(sides=12)` — two straight runs joined by a 90° bend whose inner side is collapsed so the mesh has triangles and one vertex with more than four edges; capped by two n-gons (spec Reference B, reduced).
  - `clean_bend(sides=12, bend_rings=4)` — a 90° bend made of clean quad rings, open ends.
  - `box_tube()` — `capped_cylinder(sides=4)`-like box.
  - `torus(major=12, minor=8)`.
- Produces (core):

```python
@dataclass
class Loop:
    verts: list[int]      # vertex path in order; for a closed loop the first id is not repeated
    closed: bool
    def edges(self) -> list[tuple[int, int]]: ...   # edge keys, closing edge included when closed

def neighbours(faces: dict) -> dict[int, list[int]]            # vid -> adjacent vids
def dihedrals(verts: dict, faces: dict) -> dict[tuple, float]  # edge -> angle between its two face normals, radians, 0 = flat; boundary edges absent
def trace_loop(verts, nbrs, edge, min_angle, stop_verts=frozenset(), uv=None) -> Loop
```

`trace_loop` walks both ways from `edge`. At each vertex it takes the neighbour whose edge makes the largest angle with the edge it arrived by (π = straight on) and continues only if that angle is `>= min_angle - 1e-6`. It ends a direction when: the vertex is in `stop_verts` (the loop ends **on** it), no neighbour qualifies, or it reaches a vertex already on the loop. Reaching the start vertex of the opposite direction makes the loop closed. `uv` is `{vid: (u, v)}` holding only vertices with a single UV position: when the current vertex and both candidate edge ends are in it, the angle is measured in UV; otherwise on `verts`.

- [ ] **Step 1: Write the fixtures.**

- [ ] **Step 2: Write the failing tests:**

```python
def test_dihedral_of_cylinder_rim_is_right_angle():
    # every rim edge of capped_cylinder(): pi/2 within 1e-6; every wall lengthwise edge: 2*pi/32

def test_rim_loop_closes():
    # trace_loop from a rim edge, min_angle=radians(120): closed, 32 verts

def test_lengthwise_loop_stops_at_the_rims():
    # from a wall lengthwise edge with no stop_verts: not closed, 5 verts (rows=4), both ends on rims

def test_loop_stops_on_stop_verts():
    # open_tube, stop_verts = both end loops: lengthwise loop has 5 verts, ends in stop_verts

def test_loop_over_a_right_angle_corner():           # spec acceptance
    # an L of two edges at 90°: min_angle=radians(120) -> 2 verts; min_angle=radians(80) -> 3 verts

def test_loop_passes_a_pole():
    # bent_pipe: the lengthwise loop through the >4-edge vertex reaches both end rims at 120°

def test_uv_source_uses_uv_angles():
    # a planar zigzag whose uv map is a straight line: stops on geometry at 120°, runs through with uv=

def test_uv_source_falls_back_where_a_vertex_has_no_single_uv():
    # same, with one vertex missing from uv: that step is judged on geometry
```

- [ ] **Step 3: Run** `python -m pytest tests/test_uv_pipe_core.py -q` — expect FAIL (module missing).

- [ ] **Step 4: Implement** `Loop`, `neighbours`, `dihedrals`, `trace_loop`. Import `_edge` from `utils.uv_stripe_select_core`.

- [ ] **Step 5: Run** the file — expect PASS. **Lint and commit** — `feat(uv-pipe): loop walker and dihedrals`.

### Task 5: Ring seams and part classification

**Files:**
- Modify: `utils/uv_pipe_core.py`, `tests/test_uv_pipe_core.py`

**Interfaces:**
- Consumes: Task 4; `face_islands`, `strip_from_faces`, `_boundary_loops` from `uv_stripe_select_core`.
- Produces:

```python
FLAT_TOLERANCE = math.radians(1.0)

def ring_seams(verts, faces, sharp_angle, loop_angle) -> list[Loop]
# closed loops (trace_loop, geometry) whose mean dihedral over their edges is >= sharp_angle.
# Start only from edges whose own dihedral is >= sharp_angle; return each loop once.

@dataclass
class Part:
    kind: str                       # "WALL" | "RING" | "DISK" | "FREE"
    faces: dict[int, tuple]
    boundaries: list[list[int]]     # boundary vertex loops, longest first

def split_parts(verts, faces, cuts, suppressed=frozenset()) -> tuple[list[Part], set]
# cuts: edge keys. Returns the parts and the peel seams (edge keys) it added.
```

`split_parts` rule: components of `face_islands(faces, cuts)`. A component is flat when all its face normals are within `FLAT_TOLERANCE` of their mean. Flat: repeatedly take the faces that have an edge on the longest boundary loop; if `strip_from_faces` builds a closed strip from them and the edges between them and the rest are not in `suppressed`, emit them as a RING, add those edges to the peel seams and continue with the rest. When those edges are in `suppressed`, grow the band inward one face layer at a time until its inner edges are not suppressed (or nothing is left); a band of two or more layers with two boundary loops is emitted as a WALL, its inner edges become peel seams, and peeling continues with the rest. When the layer is not a closed strip, stop. What is left: no faces → nothing; one boundary loop → DISK; two or more → WALL. Not flat: two or more boundary loops → WALL, else FREE. Mesh boundary edges count as boundary.

- [ ] **Step 1: Write the failing tests:**

```python
def test_cylinder_ring_seams_are_the_two_rims():
    loops = ring_seams(*capped_cylinder(), radians(60), radians(120))
    assert len(loops) == 2 and all(l.closed and len(l.verts) == 32 for l in loops)

def test_low_poly_wall_edges_are_not_ring_seams():
    # capped_cylinder(sides=8): lengthwise edges are 45° < 60° -> 2 loops.
    # sharp_angle=radians(30): still 2 loops (lengthwise edges never close)

def test_bend_rings_are_not_ring_seams():
    # clean_bend(): [] at 60°

def test_cylinder_splits_into_six_parts():            # spec Reference A
    verts, faces = capped_cylinder()
    cuts = {e for l in ring_seams(verts, faces, radians(60), radians(120)) for e in l.edges()}
    parts, peel = split_parts(verts, faces, cuts)
    assert sorted(p.kind for p in parts) == ["DISK", "DISK", "RING", "RING", "RING", "WALL"]
    assert len(peel) == 3 * 32                       # the three inner cap loops

def test_suppressed_peel_merges_two_rings_into_a_wall():
    # suppress the loop between the two bottom rings: kinds == DISK, DISK, RING, WALL, WALL

def test_bent_pipe_is_one_wall_and_two_disks():       # spec Reference B
```

- [ ] **Step 2: Run** — expect FAIL. **Step 3: Implement.** **Step 4: Run** — expect PASS.

- [ ] **Step 5: Lint and commit** — `feat(uv-pipe): ring seams and part classification`.

### Task 6: Lengthwise seam of a wall

**Files:**
- Modify: `utils/uv_pipe_core.py`, `tests/test_uv_pipe_core.py`

**Interfaces:**
- Consumes: Tasks 4–5.
- Produces:

```python
def loop_kind(loop: Loop, part: Part) -> str
# "RING" if closed; "LENGTH" if its two ends lie on two different boundary loops of part; else "INVALID"

def wall_candidates(verts, part, loop_angle, uv=None) -> list[Loop]
# LENGTH loops between the part's two longest boundary loops, one per vertex of the longest,
# ordered round that loop, duplicates removed.

def wall_seam(verts, part, loop_angle, uv=None) -> tuple[Loop | None, bool]
# shortest candidate by 3D length, ties to the lowest start position (x, y, z).
# No candidate: shortest edge path (Dijkstra over the part's edges, 3D length) between the two
# longest boundary loops, returned with fallback=True. No path: (None, True).

def existing_wall_seam(part, seam_edges) -> Loop | None
# seam_edges inside the part that form one open path joining two different boundary loops

def bend_seams(verts, part, seam: Loop, bend_angle, loop_angle) -> list[Loop]
# closed ring loops crossing the wall, taken at the seam's interior vertices in order; the tube
# direction is the difference of consecutive ring centroids; sum the turn between directions and
# return the ring where the sum reaches bend_angle, then restart the sum.
```

- [ ] **Step 1: Write the failing tests:**

```python
def test_straight_tube_has_one_candidate_per_side():
    # open_tube(12): 12 candidates, each 5 verts

def test_wall_seam_takes_the_inside_of_the_bend():    # spec: shortest loop
    # clean_bend(): the chosen loop's 3D length is the minimum over wall_candidates, fallback False

def test_wall_seam_goes_through_the_pole():           # spec Reference B
    # bent_pipe() wall: seam is LENGTH, fallback False, reaches both rims

def test_wall_seam_falls_back_to_shortest_path():
    # open_tube with loop_angle=radians(179) on a tube whose rows are twisted by a few degrees:
    # no candidate, fallback True, the path still joins the two ends

def test_loop_kind():
    # rim loop -> RING; wall lengthwise loop -> LENGTH; a loop ending mid-wall -> INVALID

def test_existing_wall_seam_is_found():
    # open_tube, seam_edges = one full lengthwise column -> Loop equal to that column;
    # a column missing one edge -> None

def test_bend_seams_cut_a_right_angle_bend_once_at_45():   # spec acceptance
    # clean_bend(bend_rings=4): one ring loop returned at radians(45); none at radians(120)

def test_bend_seams_on_a_straight_tube_is_empty():
```

- [ ] **Step 2: Run** — expect FAIL. **Step 3: Implement.** **Step 4: Run** — expect PASS.

- [ ] **Step 5: Lint and commit** — `feat(uv-pipe): lengthwise seam choice, fallback and bend seams`.

### Task 7: Analysis and the seam state model

**Files:**
- Modify: `utils/uv_pipe_core.py`, `tests/test_uv_pipe_core.py`

**Interfaces:**
- Consumes: Tasks 4–6.
- Produces:

```python
@dataclass
class Analysis:
    parts: list[Part]
    cuts: set                      # every ring / peel / bend / existing-seam cut edge
    seams: dict[int, Loop]         # part index -> lengthwise seam, WALL parts only
    breaks: dict[int, tuple]       # part index -> break edge, RING parts with a user pick only
    fallback: set[int]             # WALL part indices whose seam is a fallback path
    warnings: list[str]

def analyse(verts, faces, *, loop_angle, sharp_angle, bend_angle=None, existing=frozenset(),
            added=frozenset(), removed=frozenset(), picked=(), uv=None) -> Analysis
```

`bend_angle=None` means Split at Bends is off. `existing` is the mesh's seam edges when Split at Seams is on, else empty. `added` / `removed` are edge keys of ring loops the user toggled; `picked` is a sequence of edge-key tuples, each one lengthwise loop the user committed. Order of work: automatic ring seams ∪ `existing` ∪ `added`, minus `removed` → `split_parts(..., suppressed=removed)` → per WALL: a `picked` loop lying wholly inside the part wins (later picks beat earlier), else `existing_wall_seam`, else `wall_seam` → if `bend_angle`: `bend_seams` per WALL, minus `removed`, added to the cuts, then parts and seams recomputed once. A `picked` loop inside a RING part sets `breaks` when it is one of that ring's cross edges. A WALL with no seam at all is re-kinded FREE with a warning. A FREE part adds a warning naming its face count.

- [ ] **Step 1: Write the failing tests:**

```python
def test_reference_a():      # six parts, one seam on the wall of 4 edges, no warnings
def test_reference_b():      # WALL + 2 DISK, seam through the pole, fallback empty
def test_removed_rim_is_not_found_again():
    # removed = one rim's edges: that rim is absent from cuts; wall and cap merged; no exception
def test_added_ring_cuts_a_wall_in_two():
    # open_tube, added = the middle ring: two WALL parts, each with its own seam
def test_picked_seam_replaces_the_automatic_one():
def test_picked_loop_on_a_ring_sets_its_break():
def test_split_at_bends():   # clean_bend: one WALL with bend_angle=None; two with radians(45)
def test_existing_seam_is_kept():   # spec acceptance: existing = one lengthwise column -> that is the seam
def test_box_tube_is_free_with_a_warning():           # Review Focus 1
    # box_tube at 120°: one FREE part, one warning; at loop_angle=radians(80): no exception and
    # every face belongs to exactly one part (the kinds are not pinned: at 80° a loop may turn a box corner)
def test_open_tube_is_one_wall():                     # Review Focus 2
def test_torus_is_free_with_a_warning():              # Review Focus 3
def test_analysis_is_deterministic():                 # two runs give equal cuts and seams
```

- [ ] **Step 2: Run** — expect FAIL. **Step 3: Implement.** **Step 4: Run** — expect PASS.

- [ ] **Step 5: Lint and commit** — `feat(uv-pipe): analysis with user-added, removed and picked loops`.

### Task 8: Wall and disk layouts

**Files:**
- Modify: `utils/uv_pipe_core.py`, `tests/test_uv_pipe_core.py`

**Interfaces:**
- Consumes: Tasks 4–7; `_tutte` (mean-value relax) from `uv_stripe_core`.
- Produces:

```python
def wall_uvs(verts, part, seam: Loop, quads=False) -> tuple[dict, bool]
# {(fid, vid): (u, v)} in world units, and whether the quad-grid layout was used.
def disk_uvs(verts, part) -> dict
# {(fid, vid): (u, v)}: projection onto the part's best-fit plane, real size.
```

`wall_uvs`: the two ends are the boundary loops the seam touches. Width W = mean 3D length of the two end loops; height H = the seam's 3D length. Perimeter: seam vertices at u = 0 for the faces on one side of the seam and u = W for the faces on the other, v by arc length along the seam; each end loop's vertices on v = 0 or v = H, u by arc length round the loop scaled to W. Everything else — interior vertices and the vertices of any further boundary loop — is relaxed with the mean-value solve. If the total signed UV area is negative, mirror in u. With `quads=True` and the wall a regular grid (all quads, every non-boundary vertex has four edges, every ring loop has the same vertex count): v of ring k = mean arc length of the columns up to k, u of column j = mean arc length of the rings up to j; return `True`. Otherwise fall back to the relaxed layout and return `False`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_cylinder_wall_is_a_true_size_rectangle():    # spec acceptance
    # capped_cylinder() wall: bbox width == perimeter of the 32-gon, height == 2.0 (1e-6 relative)

def test_wall_perimeter_is_straight():
    # bent_pipe wall: every seam-side uv has u in {0, W}; every end-loop uv has v in {0, H} (1e-9)

def test_wall_has_no_flipped_face():
    # bent_pipe and clean_bend walls: signed UV area of every face > 0

def test_quads_layout_makes_every_face_a_rectangle():
    # open_tube: wall_uvs(quads=True) -> (uv, True); each face axis-aligned

def test_quads_layout_falls_back_on_triangles():
    # bent_pipe wall: wall_uvs(quads=True)[1] is False and the perimeter is still straight

def test_wall_with_a_hole_keeps_the_hole_inside():
    # open_tube with one wall face removed: hole vertices lie strictly inside (0, W) x (0, H)

def test_disk_keeps_real_size():
    # capped_cylinder top n-gon: bbox is 2 * 0.671 square (1e-6); a fan disk likewise
```

- [ ] **Step 2: Run** — expect FAIL. **Step 3: Implement.** **Step 4: Run** `python -m pytest tests -q` — expect all PASS.

- [ ] **Step 5: Lint and commit** — `feat(uv-pipe): wall and disk layouts`.

### Task 9: Map-level placement in the UV Stripe bridge

**Files:**
- Modify: `operators/uv_stripe_bridge.py` (`apply_stripes` ~:103-186)

**Interfaces:**
- Produces: `apply_maps(bm, maps, lengths, heights, faces, mode, contexts, fit_groups, vertical, active, active_fit, offset)` — everything `apply_stripes` does after it has each piece's `{(fid, vid): (u, v)}` map and its u / v extents: FIT / IN_PLACE / ACTIVE placement, vertical turn, random offset, writing the active UV layer (created when missing). `apply_stripes` computes `maps`, `lengths`, `heights` from its strips and calls it. Parameter meanings are those of `apply_stripes`.

- [ ] **Step 1: Refactor** — pure extraction, no behaviour change.

- [ ] **Step 2: Run** `python -m pytest tests -q` and the three headless files (`test_uv_stripe_operator.py`, `test_smart_inset_uv_stripe.py`, `test_smart_edge_slide.py`) — expect all PASS with no test edited.

- [ ] **Step 3: Lint and commit** — `refactor(uv-stripe): split map placement out of apply_stripes`.

### Task 10: Pipe bridge and the operator's automatic run

**Files:**
- Create: `operators/uv_pipe_bridge.py`, `operators/mesh_uv_pipe.py`, `tests/blender/test_uv_pipe_operator.py`
- Modify: `__init__.py` (import near :414, classes tuple near :780)

**Interfaces:**
- Consumes: `analyse`, `Analysis`, `wall_uvs`, `disk_uvs` (Tasks 7–8); `apply_maps`, `uv_context`, `match_piece_seams`-style seam marking, `MODE_ITEMS`, `ACTIVE_MODE_ITEM`, active-fit and offset-axis items (bridge); `strip_from_faces`, `stripe_uvs`, `open_ring` (Stripe core).
- Produces (bridge):

```python
LAYOUT_ITEMS = (("RECTANGLE", "Rectangle", ...), ("QUADS", "Quads", ...), ("TRUE", "No Stretch", ...))
LOOP_SOURCE_ITEMS = (("GEOMETRY", "Geometry", ...), ("UV", "UV", ...))

def mesh_dicts(bm, matrix, face_filter) -> tuple[dict, dict]   # verts, faces (world space)
def single_uvs(bm, snapshot_uvs) -> dict | None                 # vid -> uv where all its loops agree; None without a layer
def seam_edges(bm, faces) -> frozenset                          # existing seams between two processed faces
def lay_out_parts(bm, analysis, verts, layout) -> list[PartLayout]
def finish_pipe(bm, layouts, settings, contexts) -> None        # placement, pack, random offset, seams

@dataclass
class PartLayout:
    part_index: int; kind: str; uv: dict; length: float; height: float; faces: dict  # fid -> BMFace
    notice: str | None                                           # e.g. "Quads fell back to Rectangle"
```

- Produces (operator `IOPS_OT_Mesh_UV_Pipe`, `bl_idname = "iops.mesh_uv_pipe"`, `bl_label = "UV Pipe"`, `bl_options = {"REGISTER", "UNDO"}`, `is_bindable = True`, poll: active object is a mesh in Edit Mode). Properties:

| Name | Type | Default |
|---|---|---|
| `mode` | Enum FIT / IN_PLACE / ACTIVE | `"FIT"` |
| `active_fit` | Enum BOTH / WIDTH / HEIGHT | `"WIDTH"` |
| `orientation` | Enum HORIZONTAL / VERTICAL | `"HORIZONTAL"` |
| `layout` | Enum `LAYOUT_ITEMS` | `"RECTANGLE"` |
| `loop_source` | Enum `LOOP_SOURCE_ITEMS` | `"GEOMETRY"` |
| `loop_angle` | Float, ANGLE, min 1°, max π | 120° |
| `sharp_angle` | Float, ANGLE, min 1°, max π | 60° |
| `split_at_bends` | Bool | False |
| `bend_angle` | Float, ANGLE, min 1°, max π | 45° |
| `split_at_seams` | Bool | False |
| `mark_seams` | Bool | True |
| `pack` | Bool | True |
| `offset_axis` | Enum NONE / ALONG / ACROSS / BOTH | `"NONE"` |
| `offset_limit` | Float, min 0, soft max 1 | 0.25 |
| `offset_seed` | Int, min 0 | 0 |
| `merge_doubles` | Bool | True |
| `picks` | String, `{"HIDDEN", "SKIP_SAVE"}` | `""` |

`picks` is JSON: `{"<object name>": {"added": [[edge_index, ...], ...], "removed": [[edge_index, ...], ...], "picked": [[edge_index, ...], ...]}}` — each inner list is one loop. Resolve the indices to `BMEdge` before merging doubles.

Scope: the selected faces; with no face selected, every visible face of the objects in Edit Mode.

Per-part layout (`lay_out_parts`):
- WALL, layout RECTANGLE → `wall_uvs(quads=False)`; QUADS → `wall_uvs(quads=True)`, notice when it fell back; TRUE → Blender's unwrap of that part (seams set first), rotated so the seam side runs along V, then both seam sides snapped straight (u = min and u = max, v by arc length), scaled so UV area equals 3D area.
- RING → `strip_from_faces` on the part (`near=` the longer loop), opened with `open_ring` at the analysis's break when there is one, else left closed; `layout = "EVEN"`; `stripe_uvs`.
- DISK → `disk_uvs`.
- FREE → Blender's unwrap of that part, scaled so UV area equals 3D area.

Blender-unwrap parts need the part's faces selected and its seams marked for the call; restore the selection afterwards. Check the operator's arguments on the running version with `bpy.ops.uv.unwrap.get_rna_type()`.

`finish_pipe`: `apply_maps` with all groups 0 (one texel density per object). Mode FIT with `pack`: after placement, pack the processed islands into 0–1 with Blender's island packer — no rotation, scale together (never per island), margin 0.005 — again checking its arguments with `get_rna_type()`. Random offset is applied only when not (FIT and pack). Seams when `mark_seams`: every edge on a part outline plus each wall's seam and each opened ring's break are marked; edges inside a part are cleared; edges outside the processed faces are untouched.

- [ ] **Step 1: Write the failing headless tests** (same harness pattern as `tests/blender/test_uv_stripe_operator.py`: `enable_addon()`, a `TESTS` list, `main()`; build meshes from `tests/uv_pipe_fixtures.py`):

```python
def test_operator_is_registered():
def test_reference_a_gives_six_islands():             # spec acceptance
    # capped_cylinder, defaults: 6 UV islands; density (sqrt(uv area / 3d area)) equal across
    # islands within 1e-3 relative; wall bbox width : height == 32-gon perimeter : 2.0;
    # each ring strip's length : width == mean of its two loop lengths : its real width
def test_reference_a_packs_inside_zero_one():         # spec acceptance
    # all UVs within [0, 1]; no two island bounding boxes overlap
def test_pack_off_stacks_like_uv_stripe():
    # pack=False: longest island spans U 0..1, islands stacked upward with 0.01 gaps
def test_reference_b_wall_is_one_island():            # spec acceptance
    # bent_pipe: 3 islands; the wall island's two long sides are straight (1e-6); no face flipped
def test_quads_layout_on_a_clean_tube():
def test_no_stretch_layout_keeps_the_seam_sides_straight():
def test_seams_follow_the_parts():
    # reference A: seams == rims + cap ring loops + 4 wall seam edges, nothing else
def test_mark_seams_off_leaves_seams_alone():
def test_selected_faces_only():
    # select only the wall faces: cap UVs unchanged
def test_no_selection_takes_every_visible_face():
def test_object_scale_is_respected():
    # object scaled (1, 1, 3): wall bbox height : width uses the world height 6.0
def test_split_at_seams_keeps_an_old_lengthwise_seam():   # spec acceptance
def test_split_at_bends_cuts_the_clean_bend():            # spec acceptance
def test_picks_property_is_applied_by_execute():
    # picks with one "picked" loop on another column: that column is the seam
def test_free_part_reports_a_warning():
    # box tube: operator finishes, reports a warning, every face has UVs
```

- [ ] **Step 2: Run** the headless file — expect FAIL (operator missing).

- [ ] **Step 3: Implement** the bridge, then the operator with `execute()` only (no modal yet): gather per object, `analyse`, `lay_out_parts`, `finish_pipe`, report warnings and notices. Register the class in `__init__.py`.

- [ ] **Step 4: Run** the headless file, `python -m pytest tests -q`, and the three existing headless files — expect all PASS.

- [ ] **Step 5: Lint and commit** — `feat(uv-pipe): bridge and automatic unwrap operator`.

### Task 11: The UV Pipe modal

**Files:**
- Modify: `operators/mesh_uv_pipe.py`, `tests/blender/test_uv_pipe_operator.py`

**Interfaces:**
- Consumes: Task 10; the modal shell pattern of `operators/mesh_uv_stripe.py` (`_start`, `_take_snapshot`, `_restore_snapshot`, `_relayout`, `_finish`, `_build_overlays`, `_draw_callback`, the `modal` exception wrapper, `NAVIGATION`, `PASS_KEYS`) — copy the pattern into this operator; do not extract a shared base class from UV Stripe.
- Produces on the operator: `_pending: tuple[object, Loop] | None`; `_hover_loop(context, event) -> tuple[object, Loop, str] | None` (loop under the cursor and its kind: RING / LENGTH / INVALID / BREAK); `_click_loop(context, obj, loop, kind)` (first call makes the loop pending, a second call with the same loop commits it); `_cycle_seam(context, obj, part_index, step)`.

Behaviour (spec "Modal interaction" is the source; the table there lists every input):
- `invoke`: `_start` lays out the automatic result at once; nothing laid out → restore and cancel with a report.
- Mouse move: recompute the hover with `raycast_edit_meshes` + `closest_face_edge`, then `trace_loop` from that edge with the wall's boundary vertices as `stop_verts`.
- Commit: LENGTH on a WALL → append to `picked`; RING → if all its edges are current cuts, add to `removed` (and drop it from `added`), else add to `added` (and drop from `removed`); a loop on a RING part that is one of its cross edges → `picked` (the break). INVALID → no commit. Write `picks`, re-lay out, clear `_pending`. The modal keeps running.
- RMB / Esc: clear `_pending` if set; otherwise restore the snapshot and the property values and cancel.
- Enter / Space: with Merge Doubles on and doubles found, re-lay out with the merge (as UV Stripe's confirm does); finish.
- Alt + Wheel: `_cycle_seam` on the wall under the cursor through `wall_candidates`, stored as a `picked` loop.
- Wheel ±5° (Ctrl ±1°): `loop_angle`. Shift + Wheel: `sharp_angle`. Shift + Alt + Wheel: `bend_angle`, only while `split_at_bends`. A wheel event not consumed passes through to navigation.
- Keys: G loop source (stays GEOMETRY and shows disabled when the snapshot has no UV layer), A, S, Q, D, W, E, X, Z, R (seed), F, P. N and T pass through. H and SLASH toggle help and HUD as in UV Stripe.
- Draw: all cut edges and wall seams `Role.PREVIEW_LINE`; fallback seams and INVALID hover `Role.ERROR_LINE`; hover `Role.CLOSEST_LINE`; pending `Role.ACTIVE_LINE`. Check `ui/draw/theme.py` for the exact member names.
- HUD rows, in this order: Mode (Q), Orientation (W), Fit to Active (D), Layout (E), Loop Source (G), Loop Angle (Wheel), Sharp Angle (Shift + Wheel), Split at Bends (A), Bend Angle (Shift + Alt + Wheel), Split at Seams (S), Mark Seams (X), Pack (P), Random Offset (Z), Offset Limit, Offset Seed (R), Merge Doubles (F), Seam (Alt + Wheel), Notices. HUD header: `"{walls} wall(s), {rings} ring(s), {disks} disk(s)"`.

- [ ] **Step 1: Write the failing headless tests** with an operator stand-in and fake key presses, as the UV Stripe file does:

```python
def test_modal_opens_with_the_automatic_layout():
def test_first_click_is_pending_and_second_commits():
    # _click_loop twice with another wall column: after the first, UVs unchanged and _pending set;
    # after the second, that column is the wall's seam and _pending is None; modal still running
def test_escape_drops_the_pending_loop_first():
    # pending set, ESC -> RUNNING_MODAL, _pending None, layout kept; ESC again -> CANCELLED, snapshot restored
def test_ring_click_adds_then_removes_a_ring_seam():
    # middle ring of open_tube: commit -> 2 wall islands; commit again -> 1
def test_removing_a_rim_does_not_come_back_on_relayout():
    # commit a rim loop, then press E twice: the rim is still not a seam
def test_alt_wheel_steps_the_seam():
    # 12 steps on open_tube(12) return to the first seam; one step changes it
def test_wheel_changes_loop_angle_and_relays_out():
def test_invalid_loop_cannot_be_committed():
def test_break_click_on_a_ring_strip_sets_its_break():
def test_loop_source_uv_is_unavailable_without_a_uv_layer():   # Review Focus 4
    # mesh with no UV layer: G leaves loop_source == "GEOMETRY"; cancel leaves the mesh without a UV layer
def test_cancel_restores_uvs_and_seams_exactly():              # spec acceptance
def test_redo_reproduces_the_modal_result():
    # finish the modal after one commit, read op.picks, run execute() on a fresh copy with the same
    # properties: identical UVs (1e-6) and seams
def test_modal_hud_and_help_list_every_key():
```

- [ ] **Step 2: Run** — expect FAIL. **Step 3: Implement.** **Step 4: Run** all headless files and `python -m pytest tests -q` — expect all PASS.

- [ ] **Step 5: Reload the addon in the user's running Blender** (disable, drop its `sys.modules` entries, enable — never hand-reload single classes) and confirm `hasattr(bpy.ops.iops, "mesh_uv_pipe")`. Do not open, purge or save the user's file.

- [ ] **Step 6: Lint and commit** — `feat(uv-pipe): interactive modal with loop picking`.

### Task 12: Menus and documentation

**Files:**
- Modify: `ui/iops_pie_edit.py` (near :73), `ui/iops_pie_menu.py` (near :79), `docs/operators.md`, `docs/index.md`, `mkdocs.yml`
- Create: `docs/operators/op_mesh_uv_pipe.md`

- [ ] **Step 1: Add UV Pipe** next to UV Stripe in both pie files, the same way UV Stripe is added there.

- [ ] **Step 2: Write** `docs/operators/op_mesh_uv_pipe.md` following the structure of `op_mesh_uv_stripe.md`: what it does, what counts as a wall / ring / disk, the automatic seams and their two angles, the full key table from the spec, layouts, placement and Pack, limits (chamfered rims are clicked by hand; tubes of 4–5 sides need a lower Loop Angle). Link it from `docs/operators.md`, `docs/index.md` and the `mkdocs.yml` nav beside UV Stripe.

- [ ] **Step 3: Verify** — `uvx ruff@0.12.0 check .`; `python -m pytest tests -q`; all headless files; `git ls-files --eol` on every modified pre-existing file shows its original ending; `git grep -nE "[A-Z]:\\\\" -- docs utils operators tests` shows no new drive paths.

- [ ] **Step 4: Commit** — `docs(uv-pipe): operator page and menu entries`.

- [ ] **Step 5: Reload the addon in the user's Blender** and report that it is ready to try on the two reference objects.
