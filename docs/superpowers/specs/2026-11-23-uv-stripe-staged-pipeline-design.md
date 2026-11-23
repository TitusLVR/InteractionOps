# UV Stripe: the staged pipeline for a strip several faces wide

## Intent
The wide-strip layout is one solve today (`balanced_uvs`: EVEN start, ARAP, optional Least Stretch descent). The user took five ideas, each for its own stage of the unwrap, and wants every stage visible in the interactive preview. Standing rules hold: key, call, result; the operator finds the strip and the modal corrects it; one strip, no tears; the HUD shows only what applies.

## Non-goals
One-face-wide strips, closed rings, tears, Mode / Orientation / Fit / Offset, and the corner-correction click stay as they are. No numpy. No new layout list.

## The pipeline
| # | Stage | Consumes | Produces | Idea |
|---|---|---|---|---|
| 1 | Detection | selected faces | `Strip` (corners, rails, ends) from `strip_from_faces`, n-gons at corners and ends accepted | 4 |
| 2 | Lines and regions | `Strip`, the u = 0 end | `Lines`: lengthwise lines in order from the near rail, non-quad regions, joins through them | 3 |
| 3 | Face model | `Strip` | `Fans`: per face its flat shape and fan triangles round a virtual centre | 4 |
| 4 | Reference line | `Lines`, the setting or a click | the pinned line (or none) and its scale | 1 |
| 5 | Start layout | `Lines`, reference | a (u, v) per vertex | 5 |
| 6 | Solve | start, `Fans`, shared-coordinate expressions, slider | (u, v) per vertex, converged or not | 2 |
| 7 | Guard and fallback | solved layout | the layout kept, and why | - |
| 8 | Placement | UVs | orientation, fit, offset, as today | - |

**1. Detection: n-gons are first class.** The mesh is never triangulated; fans exist only inside the solve (stage 3). Today a corner is a boundary vertex used by one face, so an end 5-gon (a quad with one more vertex on its rail or end edge) gives five and the patch is refused ("5 corners", on master too). New rule in `strip_from_faces`: when more than four boundary vertices are used by one face, the corners are the four with the smallest in-surface angle (`_surface_angle`), provided the fourth is sharper than the fifth by more than `CAP_ANGLE`; the rest are ordinary vertices of the side they lie on. No clear gap: refused as today. Fewer than four: `_lost_corners` as today, now also after this filter. This covers an n-gon holding one corner, an end n-gon spanning the whole width (two corners) and extra vertices on a rail or on an end. Exactly four candidates stay as today; a wrong guess there is what the corner-correction click is for.

**2. Lines and regions (idea 3).** Edge classes spread as today, plus: a face of more than four edges whose boundary falls into four runs (across, along, across, along) passes classes like a quad, run to run, so an end n-gon with an extra vertex on its end edge still carries the lines; two triangles sharing an edge whose union is a four-cornered face pass classes like a quad (their diagonal gets no class). A *region* is a connected set of faces that pass nothing on. Lines are traced from both ends, motorcycle style; each line that stops at a region leaves a *tip* on its boundary. Tips on the region's two lengthwise flanks are ordered from the near rail; with equal counts the k-th joins the k-th and the two lines share one v. The region's own vertices stay free, so the solve bends the region to the straight lines round it. Unequal counts, or a join that would flatten a face or an across edge: the lines stay separate, as today.

**3. Face model (idea 4).** A face of four or more corners is measured on a fan round a virtual centre, the mean of its corners (fixed affine weights, so the centre's UV is a linear expression of the corners' and adds no unknown). A repeated corner is dropped first; a fan triangle under 1e-3 of the face's area is dropped; a face left with none is ignored by the energy and not counted as stretched. `uv_stripe_core.face_stretch` moves to the same fan, so the energy still minimises exactly what is reported. Triangles are unchanged.

**4. Reference line (idea 1).** One lengthwise line (a rail or an inner line) may be *pinned*: each vertex on it gets u = its 3D arc length along the line, a constant in the u expressions, so that line has no lengthwise stretch at all. With no line pinned the strip's length is an unknown, as today, and the balance already puts the true length inside the strip with the error spread to both sides (the oblique-Mercator arrangement); the preview then shows which line came out true. No separate scale knob (open question 2).

**5. Start layout (idea 5).** With both rails straight: the reference line (the middle line when none is pinned) is laid at true arc length; each next line outwards takes v = the previous v + the mean cross length between them, and each of its vertices u = the u of its across neighbour + the across edge's 3D projection on the local lengthwise direction. Region vertices get the mean of their placed neighbours (two sweeps). Any failure (no line order, a vertex unreached) falls back to today's EVEN start. ARAP then relaxes it as today.

**6. Solve (idea 2).** ARAP first (unchanged, it is also the fallback). Then the blended energy, per face: `(1 - t) * (C / C_ref) ** 4 + max(t, 0.05) * D`, with C = (k + 1/k) / 2 and D the symmetric Dirichlet term, both over the face's fan metric; t is the slider. This is today's `_StretchEnergy` with its fixed 0.05 turned into the slider. t = 1 returns the ARAP layout itself, so today's Even Texel is reproduced exactly; t = 0 is today's Least Stretch. Solver: L-BFGS (memory 5) on the descent already there, preconditioned with the factored ARAP matrices, same flip-free line search; no refactoring per step. Projected Newton is a measured alternative behind the same function (step 2 of the plan): in pure Python its per-step factorisation of the coupled u, v system may cost more than it saves.

**7. Guard and fallback.** Unchanged order: fold guard on the result; on failure the ARAP layout; on its failure the straight-row candidates (`choose_layout`). New: the reason is kept and shown.

## Settings
- **Balance** (`balance`, float 0..1, replaces the Even Texel / Least Stretch enum): 0 Least Stretch, 1 Even Texel, default 0.5 (open question 1). Old values migrate: EVEN_TEXEL 1.0, LEAST_STRETCH 0.0. **Wheel** steps 0.1, **Ctrl + Wheel** 0.02, **B** jumps 0 / 0.5 / 1. HUD row "Balance (Wheel)", always shown while a wide piece is laid out, e.g. `0.30 · Least Stretch < > Even Texel`.
- **Stretch Limit** moves to **Alt + Wheel** (Ctrl + Alt: fine). Its HUD row shows only while it applies: a piece exceeds it or was relaxed by it. **Shift + Wheel** stays Offset Limit.
- **True Length Line** (`true_length`, key **L**): *Automatic* (default, nothing pinned), *Middle* (the line whose 3D length is nearest the mean of the rails'), *Longer Side*, *Shorter Side*. **Ctrl + LMB** on a long side or an inner lengthwise line pins that line on that piece; again releases it. Stored like the side picks. Shown only for wide pieces with a straight side; with one straight side only that side can be pinned. A pinned piece is laid out balanced only.
- **Preview** (`preview`, key **P**, More Options): *Result* (default), *Start Layout*, *Off* - what the flat inset shows.
- Straight Sides, Ends, Align, C, V, plain LMB on a side: unchanged.

## Preview
World space, through `draw.edges_world` / `draw.points_world`, always on in the modal; each layer appears only when its stage produced something.
| Stage | Drawn | Role |
|---|---|---|
| 1 | the four corners; a corner recovered from a collapsed vertex | `PREVIEW_POINT`; `CLOSEST_POINT` |
| 1 | straight / free sides (today) | `PREVIEW_LINE` / `LINE` |
| 2 | inner lengthwise lines held straight / left free | `PREVIEW_LINE` / `LINE` |
| 2 | region outline and the join between matched tips | `GHOST_EDGE` |
| 3 | fan centres and spokes of faces with five or more corners and of region faces | `POINT`, `GHOST_EDGE` |
| 4 | the pinned line; under Automatic the line(s) within 1 % of true length, else the nearest | `HANDLE` |
| 6 | stretched faces' edges (today) | `LOCKED_LINE` |
| 7 | centres of the faces that made a layout fall back | `ERROR_POINT` |
| - | side or line under the cursor (today) | `ACTIVE_LINE` |

Flat inset (POST_PIXEL, `draw.polyline` / `draw.points`, a corner of the region, same roles): the hovered or first wide piece in UV space, so the straight lines, the true-length line and the regions read at a glance; under *Start Layout* it shows stage 5's layout instead. HUD header adds, only when true: "Refining..." while a live step is not converged, and "Fell back: Even Texel" / "Fell back: straight rows" in `HUD_STATS_ERROR`. Help (H) gains: Ctrl + LMB on a line, Alt + Wheel, L, P.

## Cores and interfaces (all stdlib only, no bpy)
- `utils/uv_stripe_lines_core.py` (new; `_classes`, `_lines` move here): `strip_lines(strip, lo, hi) -> Lines` with `lines: list[Line]` (`verts` in order, `rank` from the near rail, `state` "rail" / "straight" / "free", `length`), `regions: list[Region]` (`faces`, `joins`), `order_ok`.
- `utils/uv_stripe_faces_core.py` (new): `face_fans(verts, faces, tiny) -> dict[int, Fan]` (`flat`, `weights`, `tris`, `area`); used by the energy, the fold guard and `face_stretch`.
- `utils/uv_stripe_drape_core.py` (new): `drape_start(strip, lines, reference) -> dict[int, Vec2]`, raises ValueError when it cannot.
- `utils/uv_stripe_balance_core.py`: `prepare(strip, ends, rails, reference=None) -> Prepared` (lines, fans, expressions, factored systems, start, ARAP result; cached by topology, positions and these arguments, failures cached too); `solve(prepared, balance, warm=None, max_steps=None) -> Solution` (`uv`, `unknowns`, `converged`, `fallback`, `steps`); `balanced_uvs(strip, ends, rails, balance=0.5, reference=None)` = `prepare` + cold `solve` to convergence, deterministic; `stages(prepared, solution) -> Stages` for the preview (lines, regions, fans, start, per-line UV / 3D length ratio, fallback faces).
- `uv_stripe_auto_core`: `Shape` gains `reference: int | None` (a vertex-pair pick resolved to a line); `candidates` returns only balanced when it is set; `balance` becomes float everywhere (`StripeSettings`, Inset, Edge Slide).

## Live wheel and the budget
Measured today on obj1 (56 faces): setup 5 ms, ARAP 9 ms, Least Stretch 65 ms for 40 steps, about 1.6 ms a step. A relayout that changes the shape or the reference line is cold: `prepare` + `solve`, target under 60 ms on obj1.

A wheel step reuses `Prepared` (nothing is refactored) and warm-starts from the last unknowns: `solve(prepared, t, warm, max_steps=6)`, about 10-15 ms on obj1, so scrolling is live. Results are cached by (prepared, t rounded to 0.01); scrolling back is free. When the wheel has been still for 0.15 s the modal runs the cold solve for the final t in 30 ms slices on timer events (dropped if the wheel moves) and swaps it in; Enter waits for it. The confirmed UVs therefore equal what the redo panel and a plain call produce. Coarse-to-fine was rejected: no clean coarse mesh on mixed topology.

About 700 faces (extrapolated, about 0.03 ms a face a step; to be measured on a synthetic 10 x 70 arc): `prepare` with ARAP 0.3-0.5 s once; a wheel step is capped at 3 steps, about 60-80 ms; the cold refinement 0.4-0.8 s, sliced, with "Refining..." shown. Above 250 faces a cold relayout in the modal shows the ARAP layout at once and refines in slices. A plain call always runs to convergence (about 1 s at 700 faces).

## Measuring success
Baseline, free ends, from the prototype (scratch `solvers/results.txt`; step 0 re-measures it on the built cores): faces over 1.05 / worst stretch / texel scale max over min / time.
| Mesh | Even Texel | Least Stretch |
|---|---|---|
| obj0 (38 faces) | 8 / 1.115 / 1.06 / 5 ms | 0 / 1.013 / 1.11 / 25 ms |
| obj1 (56 faces) | 35 / 1.209 / 1.10 / 9 ms | 6 / 1.079 / 1.31 / 65 ms |
| ring8_tri (40) | 31 / 1.418 / 1.10 / 6 ms | 14 / 1.100 / 1.21 / 39 ms |
| ring24_tri (104) | 70 / 1.151 / 1.09 / 20 ms | 4 / 1.070 / 1.19 / 55 ms |

To beat: t = 1 identical to Even Texel; t = 0 no worse than Least Stretch on any mesh and cold under 40 ms on obj1; worst stretch and texel ratio both monotone along the slider, t = 0.5 strictly inside both ends; on the triangle arcs at least one line joined through a region, zero straightness deviation, worst no higher than 1.100 / 1.070; drape start halves ARAP's rounds on obj1 (16 today) with the same result to 1e-4; a pinned line true to 1e-6, the rise in worst stretch reported; wheel step under 20 ms on obj1 and under 100 ms at 700 faces; no folded face anywhere. Both ends straight on obj1 (worst 1.57) is tracked, not a target.

## Risks
- The four-sharpest rule may accept a branching patch whose arms end sharply: the gap test and the fold guard are the checks; the test set keeps a branching patch refused.
- Fan change shifts every reported stretch a little: re-baseline right after step 3, alone.
- A wrong join through a region bends the strip: the join is dropped when it flattens anything, and when the joined layout stretches more than the unjoined one.
- A pinned line removes freedom and can raise the worst stretch: it is never the default.
- t = 1 (ARAP) to t = 0.98 (descent) may jump visibly: if it does, t = 1 takes the descent's limit instead and the Even Texel tests are re-pinned.
- Warm and cold results differ: only the cold one is ever confirmed.
- Pure-Python cost at 700 faces rests on extrapolation: step 0 measures it before anything is built on it.

## Build plan
0. Bench script over obj0, obj1 and synthetic arcs (quad, triangle column, n-gon, 10 x 70) printing the table above from the real cores; record the baseline. Meshes stay in scratch; the arcs are generated in tests.
1. Balance as a float: blended energy on the existing descent, migration of the enum, B, wheel remap (Alt + Wheel for Stretch Limit), HUD rows. Tests: t = 0 and t = 1 equal today's two results; monotone stretch and texel ratio.
1a. N-gon corners in `strip_from_faces` (independent of the rest, can go first). Test meshes, a 3 x 6 quad arc with: (a) the corner quad carrying an extra vertex on its rail edge, (b) the same on its end edge, (c) one n-gon spanning the whole end, (d) a 6-gon inside. Each: accepted, the four true corners found, the extra vertex on the right side, laid out with no folded face, face count unchanged; (e) a kinked side with no clear gap stays refused.
2. `prepare` / `solve` split, warm start, `max_steps`, result cache, idle sliced refinement, L-BFGS; projected Newton spiked and kept only if faster on the bench. Tests: warm-then-cold equals cold; step timings.
3. `uv_stripe_faces_core`, fans in energy, guard and `face_stretch`; re-baseline. Tests: n-gon result independent of corner order; collapsed corner handled.
4. `uv_stripe_lines_core`: move, triangle pairs, regions, joins; `Stages` and the world-space layers for stages 1-3. Tests: triangle-column arc joins its lines; unequal counts stay separate.
5. Reference line: constants in expressions, `true_length`, L, Ctrl + LMB, `HANDLE` layer. Tests: pinned line true; Automatic unchanged.
6. `uv_stripe_drape_core` as the start, EVEN fallback. Tests: same result, fewer rounds.
7. Flat inset, P, fallback marks and header, help, `docs/operators/op_mesh_uv_stripe.md`.

## Open questions
1. **Default Balance.** Recommended 0.5, if step 1 shows it inside both ends on obj0 and obj1; otherwise keep 1.0 (today's Even Texel).
2. **An explicit true-length scale** (the Mercator knob, e.g. 0.97)? Recommended no: Automatic already spreads the error to both sides, and a number nobody can guess breaks "key, call, result".
3. **The flat inset in the viewport** (a small UV view of the piece)? Recommended yes, on by default: it is the only way to show the start layout and the straightness at a glance; P turns it off.

## Decisions (user, 2026-11-23)
1. Balance default 0.5 if step 1 shows it lies strictly between the ends on obj0 and obj1, else 1.0.
2. No explicit true-length scale handle.
3. The flat UV inset in the viewport is on by default; P turns it off.
