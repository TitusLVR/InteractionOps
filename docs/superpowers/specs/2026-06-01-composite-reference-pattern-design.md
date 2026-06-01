# Composite Reference Pattern — Design

**Date:** 2026-06-01
**Component:** `operators/object_aligner.py`, `utils/polygon_match.py`
**Status:** Approved (pending spec review)

## Problem

In the Object Aligner's polygon-reference mode, the reference pattern marked with
**E** is currently limited to a single connected face island. `build_face_pattern`
([utils/polygon_match.py](../../../utils/polygon_match.py)) does a BFS over
shared edges from the largest face and only keeps faces reachable from that seed.
If the user marks several disconnected islands (or scattered single faces), every
island except the seed's is **silently dropped** from the pattern.

We want: **any set of faces marked in E mode — one island, several islands, or
scattered single faces — forms a single rigid reference pattern.** The mutual
spatial arrangement of the disconnected pieces is part of the pattern signature.

## Goal & Semantics

- The whole marked selection (regardless of connectivity) is **one** reference
  pattern (a "constellation" of connected components).
- Matching finds groups of faces on target objects whose components reproduce the
  reference constellation — same per-component shape **and** same mutual
  arrangement — within tolerance.
- **One matched constellation → one rig copy** (one fit matrix, one stamp). N
  matched constellations → N copies. Mirrored matches count as separate copies,
  as today.
- Mirror is a property of the **whole** constellation (the entire arrangement is
  reflected), detected at the global fit.

## Non-Goals

- No change to the object-pick (Q/W) stamping path.
- No change to the manual "leftover" path (`_compute_fit_poly_force`) for
  user-added faces outside any auto-hint.
- No new UI controls. The existing skip/keep/invert (LMB / C / I) interaction is
  reused; a "component" in the UI simply becomes a whole constellation.

## Approach: Component-Constellation Matching

Decompose the reference into connected components, find candidate matches per
component on each target, then assemble candidate tuples whose mutual arrangement
matches the reference and confirm with a single global rigid fit. This reuses the
existing pattern matcher and Kabsch machinery; only the search orchestration is new.

### Data model — reference side (`_commit_ref_polys`)

Computed once at commit (E):

- `components = components_in_selection(ref_bm, ref_faces)` — list of connected
  face-index sets. A single island yields one component; a single face yields a
  one-face component.
- `sub_patterns[i] = build_face_pattern(ref_bm, comp_i)` per component.
- **Component order** is deterministic: sort components by descending face count,
  then by descending total area (stable tie-break).
- **Global face order** = concatenation of `sub_patterns[i]["faces"]` in component
  order.
- `self.ref_pattern_anchors = self._face_anchor_points(ref_obj, global_faces)` —
  a single anchor cloud over **all** faces of all components. (Downstream fit code
  is unchanged: it already consumes `ref_pattern_anchors` as one array.)
- Stored for the search:
  - `self.ref_sub_patterns` — list of sub-pattern dicts.
  - `self.ref_component_centroids` — world-space centroid per component (for
    arrangement prediction).
  - `self.ref_anchor_component` — index of the most distinctive component
    (max face count, tie-break max area) used as the search anchor.
  - `self.ref_anchor_offset` — kept as today (mean √area over all pattern faces).

If the reference is a single connected island (`len(components) == 1`), all of the
above degenerates to current behavior (no assembly step needed).

### Search algorithm (`_search_matches`)

For each scan object (ref object + user-picked targets, visible meshes only):

1. **Per-component candidates:** for each sub-pattern `i`,
   `cands[i] = find_pattern_matches(bm, sub_patterns[i], area_tol=spec.area_tol, allow_overlap=True)`.
   Each candidate is an ordered face list of the same length as the component, with
   faces in the sub-pattern's canonical order (so positional correspondence to the
   reference holds).
2. **Anchor + predict:** let `a = ref_anchor_component`. For each anchor candidate
   `ca ∈ cands[a]`:
   - Build a hypothesis transform `T_hyp` mapping the reference's component `a`
     anchors → `ca` anchors. Try both orientations (`kabsch_with_scale` and
     `kabsch_mirror_with_scale`); keep the lower-rmse one and its mirror flag.
   - **Degenerate anchor guard:** if component `a` has fewer than 2 faces (its
     anchors do not fix rotation about the face normal), escalate to a **pairwise
     seed** — pair `ca` with each candidate of the next-most-distinctive component
     and build `T_hyp` from the combined ≥4 anchors. Use the seed pair that yields
     the lowest fit rmse.
   - For every other component `j`, predict its centroid `T_hyp @ ref_centroid[j]`
     and pick the nearest candidate in `cands[j]` whose centroid lies within
     `pos_tol` and whose faces don't overlap faces already claimed in this
     assembly. If any component has no candidate in range, discard this anchor
     candidate.
3. **Assemble + global fit:** concatenate the matched candidates in component order
   into a global ordered face list. Run the global fit (`kabsch_with_scale` and
   `kabsch_mirror_with_scale`) of `ref_pattern_anchors` vs the assembly's anchors;
   pick the lower-rmse orientation, gate by `rmse_rel = rmse / ref_bbox_diag <=
   spec.fit_rmse`. The global fit is the final arbiter that rejects false
   assemblies.
4. **Record:** each surviving assembly becomes one entry:
   - `match_orders[obj]` += global ordered face list,
   - `match_hints[obj]` += `frozenset` of all its faces,
   - `match_mirrors[obj]` += whole-constellation mirror flag.
   Deduplicate assemblies by the frozenset of their faces.

Two-tier escalation is kept (current `tier_specs`), extended with `pos_tol`:

| tier | area_tol | fit_rmse | pos_tol (× ref_bbox_diag) |
|------|----------|----------|---------------------------|
| 0    | 0.20     | 0.05     | 0.10                      |
| 1    | 0.35     | 0.15     | 0.20                      |

Tier 0 runs first; if no constellation survives, tier 1 reruns with wider tolerances.

### Weak-pattern warning

After decomposition at commit, if the pattern is "weak" — the anchor component has
fewer than 2 faces (i.e. every component is a single face) — report a warning so
the user knows matching is less reliable and prone to false positives:

> `self.report({"WARNING"}, "Weak pattern: mark at least one island of 2+ faces for reliable matching")`

Matching still proceeds (pairwise seeding handles it); the warning is informational.

### Downstream (unchanged)

Because each constellation is stored exactly like a single-island match used to be
(one entry in `match_orders`/`match_hints`/`match_mirrors`, with
`ref_pattern_anchors` as one global cloud), the following require **no change**:

- `_seed_hint_fits` — precomputes one placement matrix per constellation via
  `_compute_fit_poly_pattern`.
- `_compute_fit_poly_pattern` — Kabsch-fits `ref_pattern_anchors` against the
  ordered target faces' anchors. Works on the global order as-is.
- `_enqueue_target_poly_stamps` — iterates `match_orders` entries; each
  constellation yields one stamp.
- Drawing (`_draw_preview_3d`), hover, and skip/keep/invert toggling
  (`_toggle_hint_component`, **C**, **I**) — a "component" in the UI is now a whole
  constellation; clicking any of its faces toggles the entire group.

## Data Flow Summary

```
E (mark faces, any connectivity)
  └─ _commit_ref_polys
       ├─ components_in_selection            -> components
       ├─ build_face_pattern per component   -> ref_sub_patterns
       ├─ global face order                  -> ref_pattern_anchors (one cloud)
       ├─ component centroids                -> ref_component_centroids
       └─ pick anchor component / weak warning
E (commit) -> _search_matches
       per object: per-component find_pattern_matches
                   anchor candidate -> T_hyp -> predict others -> assemble
                   global Kabsch + rmse gate -> constellation match
       -> match_orders / match_hints / match_mirrors  (one entry per constellation)
  └─ _seed_hint_fits -> placement matrices (unchanged)
Enter -> _enqueue_target_poly_stamps -> one stamp per constellation (unchanged)
```

## Error Handling & Edge Cases

- **Single island reference (k=1):** assembly step is skipped; behavior is
  identical to today (regression guard).
- **No candidates for a component:** that anchor candidate is discarded; if no
  assembly survives on any object, tier escalates, then reports zero matches as
  today.
- **Overlapping candidates:** a face already claimed by one component in an
  assembly cannot be reused by another component of the same assembly.
- **Symmetric sub-patterns:** `find_pattern_matches` returns one canonical
  ordering; a wrong-symmetry correspondence yields high Kabsch rmse and is rejected
  by the gate — same limitation as today, not worsened.
- **Evaluated-mesh face indices:** all picks/searches read the evaluated mesh
  (mirror/array modifiers applied), unchanged. Mirror-modifier copies appear as
  separate components/candidates and are matched naturally.

## Testing

Pure-numpy / bmesh helpers are unit-testable with pytest (existing pattern in
`utils/polygon_match.py`). New/affected units to cover:

- Component decomposition produces the expected component count for: one island,
  two disjoint islands, scattered single faces.
- Constellation assembly: given synthetic per-component candidates with a known
  rigid arrangement, the correct tuple is assembled and a wrong arrangement is
  rejected by `pos_tol` / global rmse.
- Mirror: a mirrored constellation is detected (lower mirror rmse) and flagged.
- Degenerate anchor: a single-face anchor escalates to pairwise seed and still
  assembles a correct two-component constellation.
- Regression: a single-island reference produces the same matches as the current
  single-pattern path.

In-Blender behavior (live raycast, draw) is verified manually / via blender-mcp.

## Open Risks

- Scattered single-face patterns (case 2) produce many per-component candidates;
  assembly is heavier and more false-positive prone. Mitigated by anchoring on the
  most distinctive component, `pos_tol` pruning, the global rmse gate, and the
  weak-pattern warning. Candidate counts are logged per tier as today.
