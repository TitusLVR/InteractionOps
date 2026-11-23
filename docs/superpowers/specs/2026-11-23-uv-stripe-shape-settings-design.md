# UV Stripe: shape settings instead of Layout

## Intent
The Layout list (Auto, No Stretch, Rectangles, Even Rows, True Shape) and Split at Bends / Bend Angle ask the user to pick an algorithm. The user wants to say what must be straight and let the operator find the least-stretched result: "remove the settings that give the worst result, keep the ones that give the best".

## Goals
- Three shape settings replace Layout, Split at Bends and Bend Angle.
- The operator picks the layout algorithm itself, by measured stretch.
- Works the same for a strip one face wide and for a patch several faces wide.

## Non-goals
- Mode, Orientation, Fit to Active, Split at Seams, Mark Seams, Random Offset, Offset Limit, Offset Seed, Merge Doubles and the cut picking (C) stay as they are.

## Approaches
1. **What must be straight (picked):** Straight Sides, Ends, Stretch Limit.
2. Keep Layout and add the new options beside it. Rejected: more to tune, the opposite of the request.
3. One Auto with no options. Rejected: the user wants to switch the ends and the sides.

## Settings
- **Straight Sides** (`straight_sides`, key E): *Both* (default) - both long sides and every lengthwise line straight and horizontal; *Longer Side* / *Shorter Side* - only that long side straight, the rest free; *Picked Side* - the long side holding the edge picked on that piece, Longer Side for a piece without one; *None* - nothing straightened: the faces unfolded at their real shape (today's True Shape), turned by **Align**.
- **Ends** (`ends`, key A): *Slanted* (default) - the ends at their real slant; *Straight* - both ends vertical. Unused under None.
- **Stretch Limit** (`stretch_limit`, wheel): as today. A piece whose worst face stretches beyond it is relaxed one step at a time, Both -> the longer side only -> None, and stops at the first step within the limit, else at the least stretched.
- **Align** (G) stays, for None only. **V** picks one edge per piece: under None it is the align edge, under the other values an edge of a long side makes that side the straight one and sets Picked Side.

## How a piece is laid out
For the requested straightness the operator measures every layout that satisfies it and takes the one whose worst face stretches least (first on a tie):
- Both, Slanted: No Stretch, balanced (rails both, ends free).
- Both, Straight: Rectangles, Even Rows, balanced (rails both, ends straight).
- One side: balanced (that rail, ends as set).
- None: the unfold.
A layout that cannot lay the piece out is skipped. Which of the old layouts stay as candidates is decided by measurement on real meshes: one that never wins is removed.

Tears: as Auto makes them today (bend cuts that lower a face's stretch, one-face-wide strips only), measured under Both. Manual cuts, skipped tears, a ring's break and Split at Seams are unchanged.

## Removed
`layout`, `split_at_bends`, `split_angle` and their keys and HUD rows; `StripeSettings` carries `straight_sides` and `ends` instead, so Inset and Edge Slide follow.

## Left to the builder
How the candidates are named internally, the HUD wording, the migration of tests.

## Picking sides by click (added 2026-11-23, replaces the Picked Side value)
The sides are found automatically (the four corners split the boundary into two long sides and two ends), so a plain call needs no clicks. In the interactive mode:
- The four outer sides of every piece are always drawn: a straight side in one theme role, a free side in another; the side under the cursor is highlighted.
- **LMB on a side** toggles that side of that piece: a long side straight / free, an end straight / slanted. The piece is laid out again at once. No pick mode is needed.
- **LMB anywhere else does nothing** (the user's choice: a miss must not confirm). Confirm with Enter / Space.
- **E** (Straight Sides) and **A** (Ends) set the defaults for every piece; a click overrides one piece on top of them. With both long sides free a piece is unfolded at its real shape and Align (G, V) applies.
- The per-piece choices last for the redo panel; a new run starts from the defaults. Straight Sides values: Both, Longer Side, Shorter Side, None (Picked Side is dropped: the click replaces it).
- C (cuts) and V (align edge) stay as they are.

## Balance (added 2026-11-23, user's choice: "as a choice")
A setting under More Options, `balance` (no key of its own beyond the HUD row; Enum):
- *Even Texel* (default) - the wide-strip solve keeps every face near its real size (ARAP): even texel density, some stretch left where rows must differ in length.
- *Least Stretch* - the solve minimises the measured stretch itself (a p-norm of each face's (k + 1/k)/2 over the averaged UV metric that `face_stretch` uses, p = 4, at most 40 iterations, preconditioned with the ARAP matrices, never flipping a face, a small isometric term fixing the size): far less stretch, uneven texel density (up to about 1.3x between faces on the measured meshes).
Prototype and measurements: scratch `solvers/metric_energy.py`, `compare.py` (not in the repo). Least Stretch must keep the fold guard and the failure fallback, and stay within the modal's budget (about 0.1 s) on obj1-sized patches. It applies to strips several faces wide only; one-face-wide strips are unchanged.

## One straight side (decided 2026-11-23)
With only one long side straight, everything else lengthwise is free too: the other long side and the interior lengthwise lines are placed by the stretch minimisation alone. "Everything straight" is Both. This is what `balanced_uvs(rails="NEAR"/"FAR")` already does.

## Ends one by one (decided 2026-11-23)
The ends switch like the long sides: none, one or both straight. **Ends** values: *Slanted* (default, neither), *Both*, *Longer End*, *Shorter End* (the end whose cross edges are longer / shorter in 3D; on a tie the end at u = 0). A click on an end toggles that end alone. The core needs a per-end parameter: `balanced_uvs(strip, ends=...)` takes "FREE", "BOTH", "START" or "END" (START is the u = 0 end); the old "STRAIGHT" becomes "BOTH". For one-face-wide strips a straight end means that end's cross edge stands vertical.

## HUD and help (decided 2026-11-23)
Nothing is removed: every option keeps its key and its row; the HUD only folds what is not needed now.
- Always: the header with the stretched-face count; Straight Sides (E), Ends (A), Stretch Limit (Wheel), More Options (Tab).
- Only when it applies: Align (G) under Straight Sides = None; Manual Cuts when there is one; Doubled Vertices when there are any.
- C and V are no rows: while one is on, a line "Picking cut edges · C to stop" / "Picking the align edge · V to stop" shows at the top.
- More Options (Tab): Balance, Mode, Orientation, Fit to Active, Split at Seams, Mark Seams, Random Offset, Offset Limit, Offset Seed, Merge Doubles. Remembered as last used, so a user who keeps it open sees everything every time.
- Help (H), hidden by default: LMB on a side (straight / free), C, V, Enter / Space confirm, Esc / RMB cancel. No navigation, MMB, N / T or wheel lines, and no keys already shown in the HUD.
- Status bar: one line "LMB side: straight/free · Tab: more · Enter: confirm · Esc: cancel".

## Follow-up: correcting the corners in the modal (agreed 2026-11-23, build only if detection fails on real meshes)
The operator finds the four corners itself; the modal is where a wrong guess is corrected. Planned control: a click on a boundary vertex of a piece makes it a corner, moving the nearest corner there, and the piece is laid out again; clicking it again restores the detected corner. Stored like the side picks (redo panel, dropped on a new run). Not built until a real mesh shows a wrong corner.

## Decisions after validation (user, 2026-11-23)
1. Ends = Slanted means the ends are free: layouts with upright ends (Rectangles, Even Rows, balanced with straight ends) compete too, and the least stretched wins.
2. Relaxation stops at the first step within Stretch Limit (straight sides before a bent shape).
3. Inset and Edge Slide frames must tear symmetrically: `auto_cuts` retries a rejected candidate once later candidates are in, so a 4x1 frame gives four equal pieces.
4. Least Stretch at ~145 ms in the two-solve case is accepted for now (the staged pipeline's warm start addresses it).
5. B stays as the Balance key.
