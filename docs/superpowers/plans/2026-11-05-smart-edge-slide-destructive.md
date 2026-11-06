# Smart Edge Slide Destructive Mode (D) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A D toggle that lets Smart Edge Slide run as a skeleton wavefront. Vertices merge, the loop opens at walls, ends shoot on, and only open edges stop the slide. Every angle tolerance becomes a redo-panel prop.

**Architecture:**
- **Angles.** A frozen `Angles` dataclass rides on `Band`, so the bridge and the core read one set of tolerances.
- **Destructive mode** lives in a new pure-Python module, `utils/smart_edge_slide_wave.py`, as `WaveSlider(Slider)`.
  - It keeps `Slider`'s frames, routes, `_meet`/`_merge` and traces.
  - It replaces the fold schedule with a wave schedule: fold, wall hit, wall end/shoot, contact and used-up events.
  - Its solve emits a `Cut` that may have breaks: an opened loop, split pieces, points on walls.
- The bridge's `apply_cut` learns breaks. The operator adds D, the Angles box and the HUD lines.

**Tech Stack:** Blender 5.2 Python (bpy, bmesh, mathutils), pure-Python core, pytest, headless Blender test scripts.

**Spec:** `docs/superpowers/specs/2026-11-05-smart-edge-slide-destructive-design.md`. It builds on `docs/superpowers/specs/2026-11-04-smart-edge-slide-design.md`.

## Global Constraints

- With D off and the angles at their defaults, everything behaves exactly as on master (`469528a`). All existing tests stay green unchanged.
- The core stays pure Python (no bpy) and unit-tested with plain pytest (`python -m pytest tests -q`).
- bmesh work lives only in `operators/mesh_smart_edge_slide_bridge.py`.
- Headless Blender runs only through PowerShell, with every `BLENDER_USER_*` variable pointed at scratch directories. Never touch the user's live Blender.
- The repo is public: no internal paths, asset or object names, or mesh data in committed files. The U-loop snapshot stays in scratch.
- Previews are drawn only through `ui/draw/primitives` with theme `Role`s inside `draw_scope`. No new colours.
- UI labels use full words, no abbreviations.
- Files keep their line endings: LF, except `utils/picking.py` (CRLF). Lint with `uvx ruff@0.12.0 check <files>`.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. The branch is squashed to one commit before merge.
- The modal budget is at most 30 ms per mouse move on a 100×100 grid with a 50-edge chain, D on.
- **Anti-goals**, each pinned by tests:
  - at no width in [0, limit] may a D solve fail;
  - no invalid topology (crossing new edges, zero-length edges, repeated face vertices);
  - a tilt of 1e-9 must not change a D limit by more than 1e-6.

## Review Focus

1. **Several chains, one in D splits while another is used up early.** Per-chain limits hold; the HUD shows "clamped" only for a chain past its own limit. Test in Task 9.
2. **Ctrl-snap in D to a vertex past a merge or split event.** `snap_width` must find widths past events: the offset is no longer monotonic across a split. Test in Task 5.
3. **Redo after a D cut with merged fans.** Re-running `execute()` from the props gives the same topology as the confirm. Test in Task 8.
4. **Toggling D mid-modal.** C's own value comes back, and the preview updates with no stale cached cut. Test in Task 9.
5. **A chain whose end already sits on an open edge (end edge None), and widths below `_ANCHOR_SNAP_TOL`, in D.** No exception; an empty cut at tiny widths. Test in Task 2.

---

### Task 1: Tunable angles (all modes)

**Files:**
- Modify: `utils/smart_edge_slide_core.py` (`Angles`, `Band.angles`, the `RAIL_MAX_DEV` and `STEP_*_COS` use sites at :32-35, :947, :1168, :1397)
- Modify: `operators/mesh_smart_edge_slide_bridge.py` (`END_SHALLOW` :68, `_RUN_BREAK_COS` :72, the uses at :298, :353-365, :421; `build_band(..., angles=...)`)
- Modify: `operators/mesh_smart_edge_slide.py` (props, a `draw()` with the Angles box, passing `angles` to `build_band`)
- Test: `tests/test_smart_edge_slide_core.py`, `tests/blender/test_smart_edge_slide.py`

**Interfaces:**
- Produces:
  - `core.Angles(rail_bend: float = radians(30), end_edge: float = radians(60), step_agree: float = radians(30), step_differ: float = radians(60), shoot: float = radians(30))`, frozen. Radians throughout.
  - `Band.angles: Angles = field(default_factory=Angles)`.
  - `bridge.build_band(bm, src, side, tris=None, angles: core.Angles | None = None)`. None means `Angles()`, and the band carries the angles it was built with.
  - Operator props, each a `FloatProperty(subtype="ANGLE")`:
    - `rail_bend` "Rail Bend", 30°, 1°–89°;
    - `end_edge_angle` "End Edge Angle", 60°, 1°–179°;
    - `step_agreement` "Step Agreement", 30°, 1°–89°;
    - `step_difference` "Step Difference", 60°, 2°–179°;
    - `shoot_angle` "Shoot Angle", 30°, 0°–89°.
  - `operator._angles() -> core.Angles`.
- The old module constants stay as the defaults' source: `RAIL_MAX_DEV`, `STEP_AGREE_COS`, `STEP_DIFFER_COS`, `bridge.END_SHALLOW`. Existing imports keep working.

- [ ] **Step 1: Write the failing tests**

```python
def test_angles_default_to_the_old_constants():
    a = Angles()
    assert a.rail_bend == pytest.approx(RAIL_MAX_DEV)
    assert math.cos(a.step_agree) == pytest.approx(STEP_AGREE_COS)
    assert math.cos(a.step_differ) == pytest.approx(STEP_DIFFER_COS)
    assert a.end_edge == pytest.approx(math.radians(60)) and a.shoot == pytest.approx(math.radians(30))

def test_rail_bend_bounds_how_far_a_rail_path_turns():
    # strip2 with vertex 9 moved so the rail path at vertex 1 bends 20 degrees at vertex 5.
    band = strip2_bent(20.0)
    assert rail_path(band, 1, 5)[0][-1] == 9                      # 20 deg is within the default 30
    band.angles = Angles(rail_bend=math.radians(10))
    assert rail_path(band, 1, 5)[0][-1] == 5                      # 20 deg is past 10: the path ends at 5
```

`strip2_bent(deg)` is a new fixture. It is `strip2()` with vertex 9 placed so that edge 5→9 turns `deg` from edge 1→5.

Add headless tests in `tests/blender/test_smart_edge_slide.py`:
- `test_end_edge_angle_admits_a_shallower_end_edge`: a chain end whose only edge into the side leaves at 45°. `build_band(...).band.end_edges[0]` is None with the defaults, and that edge's far vertex with `Angles(end_edge=radians(40))`.
- `test_angle_props_reach_execute`: on `strip2_bent(20)` with `rail_bend` = 10°, execute gives different new-vertex coordinates than with the default.

- [ ] **Step 2: Run them and see them fail**
  - `python -m pytest tests/test_smart_edge_slide_core.py -k "angles or rail_bend" -q`. Expected: ImportError / AttributeError on `Angles`.
  - Headless: the two new tests fail.

- [ ] **Step 3: Implement**
  - Every use site reads `band.angles` (the core) or the `angles` argument (the bridge).
  - `END_SHALLOW` becomes `angles.end_edge`.
  - `_RUN_BREAK_COS` is computed from `angles.step_differ` and `angles.step_agree` with today's formula, inside the function that uses it.
  - Operator `draw()`:
    - first the existing props: Width, Exact Width, Allow Collapse, UV Stripe, UV Stripe Mode;
    - then `header, body = layout.panel("IOPS_PT_smart_edge_slide_angles", default_closed=True)`, with header "Angles" and the five props in the body.
  - `step_agreement` is clamped below `step_difference` in `_angles()`, at most `step_difference - 1°`.

- [ ] **Step 4: Run every suite and see it pass**
  - pytest: all tests, including every existing one, unchanged.
  - Headless `tests/blender/test_smart_edge_slide.py` and `tests/blender/test_smart_inset_uv_stripe.py`: all pass.
  - `tests/blender/check_reference_mesh.py -- <scratch>/reference_mesh.json`: same limits as on master.

- [ ] **Step 5: Commit** `feat(smart-edge-slide): angle tolerances become redo props`

---

### Task 2: WaveSlider, breaks in Cut, end folds

**Files:**
- Create: `utils/smart_edge_slide_wave.py`
- Modify: `utils/smart_edge_slide_core.py` (`Cut.breaks`)
- Test: `tests/test_smart_edge_slide_wave.py` (new; shares fixtures by importing them from `tests/test_smart_edge_slide_core.py`)

**Interfaces:**
- Produces:
  - `Cut.breaks: tuple[int, ...] = ()`. Index `i` in it means there is no new edge between `points[i-1]` and `points[i]`. For a closed band, `0` in `breaks` means the wrap edge is absent. Slider never sets it.
  - `WaveSlider(Slider)` with:
    - `solve(width, *, exact=False, collapse=False, destructive=False) -> Cut`;
    - `limit(*, exact=False, collapse=False, destructive=False) -> float`;
    - `snap_width(target, *, exact=False, collapse=False, destructive=False) -> float | None`.

    With `destructive=False`, every method returns exactly what `Slider`'s does. With `destructive=True`, collapse is implied.
  - `WaveEvent(width: float, kind: str, data: tuple)`. `kind` is one of `"fold"`, `"wall_hit"`, `"wall_end"`, `"contact"`, `"used_up"`.
  - `WaveSlider._wave(exact) -> list[WaveEvent]`, computed once per `exact` and cached.

This task adds only `"fold"`, extended to the end segments, plus `"used_up"` for an open piece whose interior vertices have all merged into its ends. Later tasks add the other kinds.

**The end-fold rule (the algorithm the tests do not settle):**
- `_fold_events` never folds segment 0 or segment m-1 of an open chain. In the wave, they fold like any segment.
- When segment 0 folds, `chain[1]` merges into the start end. The merged group's point is no longer `_meet` of two offset lines. It is the start end's point on its wall at that width (`_border_hit`), and it stays on the wall as the width grows.
- When the two ends' groups meet (every segment dropped), the piece is used up. Its final state is the two ends' wall points, with a break between them.

- [ ] **Step 1: Write the failing tests**

```python
def test_wave_matches_slider_with_destructive_off():
    for make in (strip2, grid_open, u_in_grid, fold_box, walls_meet):
        b = make()
        s, w = Slider(b), WaveSlider(b)
        for exact, collapse in ((False, False), (True, False), (False, True)):
            assert w.limit(exact=exact, collapse=collapse) == s.limit(exact=exact, collapse=collapse)

def test_end_segment_folds_into_the_end_in_destructive():
    # u_in_grid: the mouth is 5 wide, so the U's arms close in. Collapse alone stops where an end segment
    # folds; destructive goes on, and the end absorbs its neighbour.
    b = u_in_grid()
    w = WaveSlider(b)
    c_lim = w.limit(collapse=True)
    d_lim = w.limit(destructive=True)
    assert d_lim > c_lim + 0.1
    cut = w.solve((c_lim + d_lim) / 2, destructive=True)
    assert cut.anchors[0] == cut.anchors[1]

def test_destructive_is_empty_at_tiny_widths_and_without_end_edges():       # Review Focus 5
    assert WaveSlider(u_in_grid()).solve(1e-9, destructive=True).points == []
    WaveSlider(end_slide()).solve(0.3, destructive=True)                      # no end edges: no exception

def test_destructive_never_fails_below_its_limit():                          # anti-goal 1
    for seed in range(40):
        b = jittered_grid(seed)
        w = WaveSlider(b)
        for exact in (False, True):
            lim = w.limit(exact=exact, destructive=True)
            for i in range(1, 61):
                w.solve(lim * i / 60, exact=exact, destructive=True)          # must not raise

def test_destructive_limit_ignores_a_1e9_tilt():                             # anti-goal 3
    assert WaveSlider(u_in_grid()).limit(destructive=True) == pytest.approx(
        WaveSlider(tilted(u_in_grid(), 1e-9)).limit(destructive=True), abs=1e-6)
```

`tilted(band, eps)` is a new helper: it rotates every vertex by `eps` radians about the z axis.

- [ ] **Step 2: Run them and see them fail**
  - `python -m pytest tests/test_smart_edge_slide_wave.py -q`. Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement** `WaveSlider` and `Cut.breaks`.
  - `_plan`, `_positions` and `_solve` are overridden only when `destructive` is set; otherwise they call `super()`.
  - Event widths are exact from the piecewise-linear lines, as in `_fold_events`.
  - Near-simultaneous events within `surf.tol` happen together, in `(width, kind order, chain index)` order. That way noise cannot reorder them.

- [ ] **Step 4: Run them and see them pass**, plus the full pytest suite.

- [ ] **Step 5: Commit** `feat(smart-edge-slide): WaveSlider folds end segments into the ends`

---

### Task 3: Wall hits open the loop

**Files:**
- Modify: `utils/smart_edge_slide_wave.py`
- Test: `tests/test_smart_edge_slide_wave.py`

**Interfaces:**
- Consumes: `WaveSlider`, `WaveEvent`, `Cut.breaks` (Task 2). Uses `Slider._border_hit`, `_Surface.end_path`, `_Surface.border_step` and `_line`.
- Produces: the `"wall_hit"` event, with `data = (k, wall_id)`.
  - Walls are the end paths, plus the band border (open edges, and edges not held by exactly two visible band faces).
  - From the hit width on, vertex k is two ends.
    - The left end is the intersection of segment k-1's offset line with the wall.
    - The right end is the intersection of segment k's offset line with the wall.
    - Each slides along the wall in its own direction, through `border_step`, as `_border_hit` does today.
  - `cut.breaks` gets the index between the two ends' points.

- [ ] **Step 1: Write the failing tests**

```python
def test_middle_vertex_reaching_the_end_wall_opens_the_loop():
    # u_wall(): the U chain of u_in_grid, but its mouth closed by the end walls lying under the arms, so the
    # second vertex from each end runs into the wall first (the user's U case in small).
    b = u_wall()
    w = WaveSlider(b)
    assert w.limit(collapse=True) < 0.5
    cut = w.solve(0.75, destructive=True)
    assert len(cut.breaks) >= 1
    for i in cut.breaks:                                   # both sides of every break lie on a wall edge
        assert cut.points[i - 1].kind in ("edge", "vert") and cut.points[i].kind in ("edge", "vert")

def test_closed_loop_reaching_the_border_becomes_open():
    # hole_rim(): a closed diamond chain (a square turned 45 degrees) round a hole in a grid, off-centre so
    # that, sliding outward, its left corner reaches the grid's border x = 0 first, before any other vertex.
    b = hole_rim()
    w = WaveSlider(b)
    cut = w.solve(2.5, destructive=True)
    assert 0 not in cut.breaks and len(cut.breaks) == 1   # opened once, mid-way round
    assert w.limit(destructive=True) > 2.5

def test_split_ends_keep_the_width():
    b = hole_rim()
    w = WaveSlider(b)
    cut = w.solve(2.5, destructive=True)
    for i in cut.breaks:
        for p in (cut.points[i - 1], cut.points[i]):
            assert distance_to_chain(b, p.co) == pytest.approx(2.5, abs=1e-6)
```

`u_wall`, `hole_rim` and `distance_to_chain(band, co) -> float` are new helpers. The last one gives the in-plane distance to the chain polyline; every fixture here is flat.

- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement** the wall-hit event.
  - The hit width is where a vertex line `a + w·d` crosses a wall segment developed into that vertex's frame. Find it by walking the wall the way `_border_hit` does, with no traces, so `limit()` stays a plan-level bisection.
  - Rerun the Task 2 anti-goal tests: the no-fail sweep and the tilt.
- [ ] **Step 4: Run them and see them pass**, plus the full pytest suite.
- [ ] **Step 5: Commit** `feat(smart-edge-slide): a wall opens the destructive loop`

---

### Task 4: Ends shoot on where their wall ends

**Files:**
- Modify: `utils/smart_edge_slide_wave.py`
- Test: `tests/test_smart_edge_slide_wave.py`

**Interfaces:**
- Consumes: `band.angles.shoot` (Task 1) and the end handling (Tasks 2–3).
- Produces: the `"wall_end"` event, with `data = (end, landing)`.
  - At the width where an end's wall runs out, trace the end's offset line on past the wall's last vertex, across faces.
  - The end lands on the first crossed edge whose direction is within `angles.shoot` of perpendicular to that line.
  - An open edge always qualifies.
  - The landing edge, continued as a rail path within `angles.rail_bend`, is that end's new wall.
  - If the landing point is within `_ANCHOR_SNAP_TOL` of the edge's vertex, the end lands on the vertex.
  - If nothing is crossed before the line leaves the band, the end stays on the wall's last vertex for every greater width.

- [ ] **Step 1: Write the failing tests**

```python
def test_end_shoots_on_to_a_perpendicular_edge():
    # shoot_strip(): the start's end wall is one edge long; past it every onward edge turns 90 degrees, and
    # the offset line crosses a vertical edge 1.5 further on.
    b = shoot_strip()
    w = WaveSlider(b)
    assert w.limit() == pytest.approx(1.0)                          # today's clamp at the wall's end
    cut = w.solve(1.5, destructive=True)
    assert cut.points[0].kind == "edge" and cut.points[0].edge == shoot_strip_landing_edge()

def test_shoot_angle_decides_which_edge_is_perpendicular_enough():
    b = shoot_strip(slant_deg=40.0)                                 # the first crossed edge leans 40 off perpendicular
    b.angles = Angles(shoot=math.radians(30))
    first = WaveSlider(b).solve(1.5, destructive=True).points[0].edge
    b.angles = Angles(shoot=math.radians(45))
    assert WaveSlider(b).solve(1.5, destructive=True).points[0].edge != first

def test_end_with_nothing_to_land_on_stays_on_its_wall_vertex():
    b = shoot_strip(no_landing=True)
    cut = WaveSlider(b).solve(1.5, destructive=True)
    assert cut.points[0].kind == "vert" and cut.points[0].vert == shoot_strip_wall_end()
```

`shoot_strip(slant_deg=0.0, no_landing=False)`, `shoot_strip_landing_edge()` and `shoot_strip_wall_end()` are new fixture helpers. The fixture's comment derives the 1.0 and the landing edge by hand.

- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.** The jump to the landing edge happens at one deterministic width. Rerun the anti-goal tests.
- [ ] **Step 4: Run them and see them pass.**
- [ ] **Step 5: Commit** `feat(smart-edge-slide): destructive ends shoot on to a perpendicular edge`

---

### Task 5: Used-up final states, pieces finishing alone, snap in D

**Files:**
- Modify: `utils/smart_edge_slide_wave.py`
- Test: `tests/test_smart_edge_slide_wave.py`

**Interfaces:**
- Produces:
  - The `"used_up"` event for every piece.
    - A closed piece shrinks to an apex (one point every anchor shares), or to a ridge (two or more points, all anchors on them).
    - An open piece pressed onto a wall leaves only its wall points, with breaks between all of them.
  - `limit(destructive=True)` is the width of the last `"used_up"` event.
  - `solve(width > limit, destructive=True)` returns the final state with `clamped=True`.
  - After a split, a used-up piece keeps its final state while the others go on.
  - `snap_width(..., destructive=True)` bisects within the event interval that holds the target, not over [0, limit] as a whole.

- [ ] **Step 1: Write the failing tests**

```python
def test_closed_square_collapses_to_an_apex():
    b = square_in_grid()                     # closed 2x2 square chain, side inward, in a 6x6 grid of quads
    w = WaveSlider(b)
    assert w.limit(destructive=True) == pytest.approx(1.0)
    cut = w.solve(5.0, destructive=True)
    assert cut.clamped and len(set(cut.anchors)) == 1 and len(cut.points) == 1

def test_open_piece_pressed_onto_its_wall_leaves_wall_points_only():
    b = u_wall()
    w = WaveSlider(b)
    cut = w.solve(w.limit(destructive=True) + 1.0, destructive=True)
    assert len(cut.breaks) == len(cut.points) - 1

def test_pieces_finish_one_by_one():
    b = dumbbell()                           # closed chain round two 4x4 rooms joined by a 1-wide neck; it splits
    w = WaveSlider(b)                        # at the neck first, then the small room's piece collapses first
    small, big = dumbbell_room_limits()
    assert w.limit(destructive=True) == pytest.approx(big)
    cut = w.solve((small + big) / 2, destructive=True)
    assert not cut.clamped

def test_snap_reaches_a_vertex_past_a_merge():                                  # Review Focus 2
    b = u_in_grid()
    w = WaveSlider(b)
    target = vertex_point(b, inner_vertex_past_first_fold(b))
    width = w.snap_width(target, destructive=True)
    assert width is not None and width > w.limit(collapse=True)
    assert any(p.kind == "vert" and p.vert == target.vert for p in w.solve(width, destructive=True).points)
```

The new fixtures each derive their numbers in a comment: `square_in_grid`, `dumbbell` and `dumbbell_room_limits`, plus `vertex_point` and `inner_vertex_past_first_fold`. The dumbbell needs the split (contact) event. Mark that test `xfail(strict=True, reason="contact event: Task 6")`; Task 6 removes the mark.

- [ ] **Step 2: Run them and see them fail** (the dumbbell test xfails).
- [ ] **Step 3: Implement.** Rerun the anti-goal tests.
- [ ] **Step 4: Run them and see them pass.**
- [ ] **Step 5: Commit** `feat(smart-edge-slide): destructive pieces collapse to their final state`

---

### Task 6: Self-contact splits and the loop meeting its own chain

**Files:**
- Modify: `utils/smart_edge_slide_wave.py`
- Test: `tests/test_smart_edge_slide_wave.py`

**Interfaces:**
- Produces: the `"contact"` event, `data = (k, segment j)`. Vertex k reaches non-neighbouring segment j of the same piece.
  - The piece splits there into two pieces, as in Smart Inset's `push_splits`: a reflex vertex against the front.
  - The source chain counts as a wall for this purpose. A vertex reaching it opens the loop, as in Task 3.
  - Detection runs in the local development:
    - one development per vertex, along the segments between k and j, through the `to_next`/`from_next` hops;
    - never one global development of the band, because a band is not flat in general.
  - Only reflex vertices are candidates. A vertex is reflex when its wedge `theta` exceeds π.

- [ ] **Step 1: Write the failing tests**
  - Remove the Task 5 `xfail` mark from `test_pieces_finish_one_by_one`.
  - Add:

```python
def test_dumbbell_splits_at_the_neck():
    b = dumbbell()
    w = WaveSlider(b)
    neck = dumbbell_neck_width()                                 # 0.5: half the neck's width, derived in the fixture
    assert len(w.solve(neck - 0.01, destructive=True).breaks) == 0
    after = w.solve(neck + 0.01, destructive=True)
    assert len(after.breaks) == 2                                # two closed pieces: one break each

def test_new_loop_reaching_the_chain_round_a_tube_stops_on_it():
    b = tube_band()        # open axial chain on an open-ended tube, border to border; the band runs all the way round
    w = WaveSlider(b)
    lim = w.limit(destructive=True)
    assert lim == pytest.approx(tube_circumference(), rel=1e-6)   # the loop goes round and stops on the chain
```

`tube_band`, `tube_circumference` and `dumbbell_neck_width` are new helpers. The circumference is measured along the tube's polygon section.

- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.** Rerun the anti-goal tests, and the 100×100 timing in the report: 50-edge chain, D on, 20 width changes, each move at most 30 ms.
- [ ] **Step 4: Run them and see them pass.**
- [ ] **Step 5: Commit** `feat(smart-edge-slide): destructive loops split where they touch themselves`

---

### Task 7: Corners, fins and lid sheets in D

**Files:**
- Modify: `utils/smart_edge_slide_core.py` (the trace step through a vertex, `_beyond` for fins, behind a `destructive` flag on the `_Surface` traces)
- Modify: `utils/smart_edge_slide_wave.py`
- Modify: `operators/mesh_smart_edge_slide_bridge.py` (lid sheet continuation)
- Test: `tests/test_smart_edge_slide_wave.py`, `tests/blender/test_smart_edge_slide.py`

**Interfaces:**
- Produces:
  - **Corners.** In D, a trace that reaches a vertex with angle defect goes on through it. Its out direction splits the vertex's remaining angle in the same ratio as its in direction split the angle it came from.
  - **Fins.** In D, a trace that reaches an edge held by more than two visible faces crosses into the face with the smallest fold from the current one. When two faces tie within `surf.tol`, the fin is a wall.
  - **Lid sheets.** In D, where a lid's far side is not a mesh edge, the bridge extends the lid as a projected sheet while real faces lie under it (`_step_region`'s projection test). Where none lie under it, the trace drops along the step normal onto the face it meets.
  - None of these change anything when D is off.

- [ ] **Step 1: Write the failing tests**

```python
def test_destructive_passes_a_box_corner():
    b = box_top_ring()     # closed chain round a unit cube's top face, side outward: the 4 sides, then the bottom face
    w = WaveSlider(b)
    assert w.limit(collapse=True) <= 1.0 + 1e-6                             # today the bottom corners stop it
    assert w.limit(destructive=True) == pytest.approx(1.5, abs=1e-6)        # over the corners, to an apex mid-bottom

def test_destructive_steps_over_a_fin():
    b = strip_fin()
    assert WaveSlider(b).limit(destructive=True) > Slider(b).limit() + 0.5
```

Add a headless test, `test_destructive_lid_sheet_runs_past_a_virtual_far_side`. It uses a pocket longer than its lid, whose far side is not a mesh edge. At a width past the lid, every new vertex lies on a real face, at most 1e-5 from the mesh surface.

- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.** Rerun the anti-goal tests.
- [ ] **Step 4: Run them and see them pass.** Run the full pytest suite and the headless suite.
- [ ] **Step 5: Commit** `feat(smart-edge-slide): destructive traces pass corners, fins and lid ends`

---

### Task 8: Bridge applies destructive cuts

**Files:**
- Modify: `operators/mesh_smart_edge_slide_bridge.py` (`_plan_loop`, `apply_cut`, `_strip_faces`, `preview_layers`)
- Test: `tests/blender/test_smart_edge_slide.py`

**Interfaces:**
- Consumes: `Cut.breaks` (Task 2) and `WaveSlider` (Tasks 2–7).
- Produces:
  - `apply_cut` makes no new edge across a break.
  - Merged anchors are one vertex. Each chain vertex in a merged group gets its connector when its straight leg crosses nothing (the existing `_connectors` rule), which gives the fan.
  - Wall points split their wall edges.
  - `Applied.loop_edges` covers every piece.
  - `Applied.pieces: list[list[BMEdge]]` holds the loop edges per piece. It defaults to one piece, `[loop_edges]`.
  - UV Stripe takes each piece as its own strip. A piece that cannot form a strip is skipped with the existing warning.
  - `preview_layers` draws no line across a break.

- [ ] **Step 1: Write the failing headless tests**
  - `test_apply_destructive_u_wall_opens_on_the_wall`: no new edge joins the two points of a break. Each break point lies on a wall edge of the original mesh.
  - `test_apply_destructive_square_apex_fans`: at `square_in_grid` past its limit there is one new vertex, joined to all 4 chain vertices. The faces round it are triangles.
  - `test_apply_destructive_keeps_topology_valid` (anti-goal 2). For every fixture in Tasks 2–7, at 5 widths each:
    - no two new edges cross;
    - no edge is shorter than 1e-6;
    - no face repeats a vertex;
    - every new vertex is at most 1e-5 from the original surface.
  - `test_redo_from_props_matches_the_confirmed_destructive_cut` (Review Focus 3): run `execute()` twice from the same props on copies of the mesh. The vertex coordinates and edge sets are identical.
  - `test_uv_stripe_one_strip_per_piece`: the `dumbbell` past the neck with U on gives two strips. Each is straight: its V lines are parallel within 1e-6.

- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass.** Run both headless suites and pytest.
- [ ] **Step 5: Commit** `feat(smart-edge-slide): apply destructive cuts, one strip per piece`

---

### Task 9: Modal D toggle, HUD, docs, reference check

**Files:**
- Modify: `operators/mesh_smart_edge_slide.py`
- Modify: `docs/operators/op_mesh_smart_edge_slide.md`
- Modify: `tests/blender/check_reference_mesh.py` (an optional `--u-loop` mode)
- Test: `tests/blender/test_smart_edge_slide.py`

**Interfaces:**
- Consumes: `WaveSlider` (replaces `core.Slider` in the operator, `_build_sides` and `execute`), `Applied.pieces`.
- Produces:
  - `use_destructive: BoolProperty(name="Destructive", default=False)`, with the description "Let the new loop run like a skeleton: vertices that meet merge, walls open the loop, ends shoot on to a crossing edge, and only open edges stop it".
  - The **D** key toggles it.
  - HUD param "Destructive (D)". While D is on, "Allow Collapse (C)" shows on and greyed. C does nothing while D is on. C's own value comes back when D goes off.
  - The help legend gets: `HUDItem("Destructive", "D", ItemState.ON, default_state=ItemState.OFF, always_show=True)`.
  - The status text gets `destructive = on/off (D)`.
  - Cancel restores `use_destructive`. The redo panel shows "Destructive" after "Allow Collapse".

- [ ] **Step 1: Write the failing headless tests**
  - `test_d_toggles_destructive_and_restores_collapse` (Review Focus 4):
    - C on, then D on, then C, then D off. `use_collapse` is True again.
    - The preview cut after D off equals a fresh `solve(collapse=True)`.
  - `test_per_chain_limits_in_destructive` (Review Focus 1): two chains, `square_in_grid` and `u_wall`, at a width between their D limits. Only the square reports clamped.
  - `test_modal_move_budget_destructive`: a 100×100 grid, a 50-edge chain, D on, 20 width changes. Each takes at most 30 ms. The test asserts at most 60 ms to allow for machine noise; the report gives the real numbers.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
  - The docs page gets:
    - the D row in the Controls table;
    - a short "Destructive mode" section: merges, walls opening the loop, ends shooting on, only open edges stopping it;
    - an "Angles" section listing the five props in user terms.
  - `check_reference_mesh.py --u-loop <json>`, run on the scratch U-loop snapshot:
    - inward with D on, the limit is greater than 0.24;
    - outward with D on, the limit is greater than 0.10;
    - FINISHED at both limits;
    - every new vertex is at most 1e-5 from the original surface;
    - it prints the limits and the counts.
- [ ] **Step 4: Run all suites and see them pass.**
  - pytest.
  - Both headless suites.
  - `check_reference_mesh.py` on `reference_mesh.json` and its 4 variants: unchanged from master.
  - `check_reference_mesh.py --u-loop` on the U-loop snapshot (scratch path in the task brief).
  - ruff on the touched files.
- [ ] **Step 5: Commit** `feat(smart-edge-slide): D toggles destructive mode in the modal`
