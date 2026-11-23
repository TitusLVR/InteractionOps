# UV Stripe: balanced layout of a strip several faces wide

## Intent
A patch several faces wide (a profile swept along an arc: a flat ledge, a wall, a flange) should come out as **one** strip, straight along its length, with the least stretch, quads, triangles and larger faces weighed alike. Today such a patch is laid out between its two rails with the interior relaxed (`_tutte`), which leaves the stretch where the rails put it (37 of 38 faces over 5 %, worst 1.25 on the user's arc), and a patch whose corner was lost to a collapsed vertex is refused.

## Goals
- One piece: every face of the patch in one strip, never torn by Auto.
- Straight along the length: both rails straight and horizontal, and every line of edges running along the strip straight and horizontal.
- The stretch that cannot be avoided is spread over the faces instead of landing on one row.
- A patch whose end lost a corner to a collapsed vertex is still a strip.

## Non-goals
- Fitting rows to given trim bands: row heights come out of the balance.
- Straightness across the width: cross edges are not forced vertical, and by default the ends keep their real slant.
- Closed rings several faces wide.

## Approaches
1. **As-rigid-as-possible solve with shared coordinates (picked).** Every vertex has a (u, v); the constraints are expressed by sharing unknowns (a rail or a lengthwise line shares one v; with upright ends, an end shares one u; strip length and height are unknowns too), and the stretch energy is minimised by the usual local rotation fit / global linear solve. Handles quads, triangles and n-gons the same way.
2. Per-column and per-row averages on a detected grid. Rejected: breaks down at triangles and collapsed vertices, which are the point.
3. Blender's own Unwrap / Minimum Stretch followed by straightening. Rejected: not available in the pure cores, and straightening afterwards undoes the balance.

## Design
- **Corners**: as today the four boundary vertices used by one face; when that gives two or three (a corner lost to a collapsed vertex), the missing ones are the boundary vertices used by two faces with the smallest in-surface angle (the sum of their face corners), each under `CORNER_ANGLE` and sharper by more than `CAP_ANGLE` than every other boundary vertex. Otherwise (none or one: a disc or a cap; more than four: a branching patch; no clear corner) the island is refused as today.
- **Lengthwise lines**: edges are classed "along" or "across" by spreading from the rails (along) and ends (across) through quads, where opposite edges share a class, and through larger faces with exactly two non-adjacent across edges, whose other edges are along. The vertices joined by along edges form a line and share one v. A line whose constraint would flatten a face or an across edge is left free.
- **Modes** (`balanced_uvs(strip, ends, rails)`, function parameters only, no operator setting yet): `ends` "FREE" (default: the ends keep their slant; only the first near-rail corner is pinned at u = 0) or "STRAIGHT" (each end shares one u). `rails` "BOTH" (default: both rails and every lengthwise line share one v each), "NEAR" or "FAR" (only that rail straight; the other rail and the lines free). Cross lines are free in every mode.
- **Hanging vertices**: a vertex lying in line between two corners of one of its faces (a quad whose side carries an extra vertex) keeps its fraction along that side, so the face is not torn round it.
- **Fold guard**: a result where any face winds backwards, encloses nothing, turns back at a corner the real face does not, or crosses itself raises, so Auto keeps the straight layout. A failure is cached like a result.
- **Solve**: start from the current layout; alternate fitting a rotation per face (its corners projected onto its own plane) and solving the two linear systems (u and v are independent) until the layout stops moving. Never mirrored.
- **Auto**: for a strip several faces wide Auto takes the balanced layout (default modes) when its worst face stretches less than the best straight-row layout's, and never True Shape. The other layouts are unchanged.

## Left to the builder
The linear solver (pure Python, no numpy), iteration limits, the triangulation weights, and the test meshes.

## Follow-up: lines through triangle regions (user's idea, 2026-11-23, not built yet)
A lengthwise line is found through quads only, so a column of triangles or n-gons across the strip breaks it into two lines that may come out at different heights. The user's rule: such a region is laid out on its own and stitched into the strip, fitted to what is around it. Design: the quad lines on both sides of a non-quad region are matched by their order from the near rail (the k-th line entering on one side continues as the k-th line leaving on the other, when both sides have the same count) and share one v; the region's own vertices stay free and are placed by the same balance solve, so the region bends to fit the straight lines around it. When the counts differ the lines stay separate, as today.
