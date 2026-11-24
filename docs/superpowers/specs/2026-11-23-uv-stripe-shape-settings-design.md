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
- Always: the header with the stretched-face count; Straight Sides (Q), Ends (W), Balance (Ctrl + Wheel), More Options (Tab); Stretch Limit (Alt + Wheel) only while it applies (keys and rows revised in the staged pipeline phase 1; revised 2026-11-24: plain wheel zooms the view; Balance moved to Ctrl + Wheel).
- Only when it applies: Align (G) under Straight Sides = None; Manual Cuts when there is one; Doubled Vertices when there are any.
- C and V are no rows: while one is on, a line "Picking cut edges · C to stop" / "Picking the align edge · V to stop" shows at the top.
- More Options (Tab): Mode, Orientation, Fit to Active, Split at Seams, Mark Seams, Random Offset, Offset Limit, Offset Seed, Merge Doubles (Balance left it for its own row on Ctrl + Wheel, 2026-11-24). Remembered as last used, so a user who keeps it open sees everything every time. With Tab off, a row of this section still shows while its option is away from its default (revised 2026-11-24, for every iOps modal HUD; built on the shared `ui/hud/more.py`).
- Help (H), hidden by default: every key of the modal, grouped (Shape, Picking, Placement, General), the keys of the HUD rows included, so a key whose row is folded or hidden is still listed: Q, W, Ctrl + Wheel, Ctrl + Shift + Wheel, B, Alt + Wheel, G, LMB on a side; C, LMB / Alt + LMB, V, LMB / Alt + LMB, LMB on a boundary vertex, Alt + LMB on a face, Shift + Alt + LMB; E, A, D, S, X, Z, Shift + Wheel, R, F; Tab, Enter / Space confirm, Esc / RMB cancel. No navigation, MMB, N / T lines, and no H or `/` line (revised 2026-11-24, for every iOps modal HUD; it replaces the earlier rule of listing only keys with no row).
- Status bar: one line "LMB side: straight/free · Tab: more · Enter: confirm · Esc: cancel".

## Follow-up: correcting the corners in the modal (agreed 2026-11-23, build only if detection fails on real meshes)
The operator finds the four corners itself; the modal is where a wrong guess is corrected. Planned control: a click on a boundary vertex of a piece makes it a corner, moving the nearest corner there, and the piece is laid out again; clicking it again restores the detected corner. Stored like the side picks (redo panel, dropped on a new run). Not built until a real mesh shows a wrong corner.

## Decisions after validation (user, 2026-11-23)
1. (Revised 2026-11-23, staged pipeline phase 1) Ends = Slanted means the real slant: the long sides keep their true lengths and no upright-end layout competes under Slanted (Rectangles, Even Rows and balanced with upright ends compete only under Ends Both / Longer End / Shorter End). With one long side straight the other relaxes and is never worse than both straight.
2. Relaxation stops at the first step within Stretch Limit (straight sides before a bent shape).
3. Inset and Edge Slide frames must tear symmetrically: `auto_cuts` retries a rejected candidate once later candidates are in, so a 4x1 frame gives four equal pieces.
4. Least Stretch at ~145 ms in the two-solve case is accepted for now (the staged pipeline's warm start addresses it).
5. B stays as the Balance key (with Balance now a 0..1 slider, B jumps 0 / 0.5 / 1).

## C and V by loop, V straightens (decided 2026-11-24)
In the live app a C or V click often did nothing visible: on a strip several faces wide one cross edge does not tear the island, and V only set the align edge, which matters under Straight Sides = None alone. The user's decisions:
- In both pick modes LMB takes a whole loop, Alt + LMB the single edge under the cursor (the old behaviour).
- C, LMB: the loop across the strip through the hovered edge, rail to rail, cut or mended as a whole (stored in `island_cuts`, every edge of the loop; a click on any edge of a cut mends it). On a strip one face wide the loop is the cross edge itself, so breaks, manual cuts and skipped tears work as before.
- V, LMB: the loop through the hovered edge is laid straight: a line along the strip on one horizontal line (one shared v), a line across it on one vertical line (one shared u). Alt + LMB: the edge alone, horizontal or vertical by its current direction. A second click on a picked line frees it. Stored in `straight_lines` (`{object: [[axis, edge, ...], ...]}`, axis 0 along / 1 across), kept for the redo panel, dropped on a new run. Under Straight Sides = None the clicked edge is also the piece's align edge, as before.
- The picked lines go into the solve: the balanced layout (`uv_stripe_balance_core`) shares one unknown per picked line on top of its rails, lengthwise lines and ends (merged with any line it meets; a line that would join both rails or ends, or flatten a face, is left out), and gains a no-rail mode ("NONE") so a piece with no straight long side can still keep picked lines. Every other layout (the straight-row layouts, the real-shape unfold) is a candidate only when it already keeps them (`uv_stripe_auto_core._measure`). So Stretch Limit relaxes the rails and the unpicked lines but never a picked line: on a band that Both relaxes to one straight rail, a picked middle line stays straight.
- Only a pick that would change something is highlighted, judged on the layout actually laid out (after Stretch Limit), not on the setting: a line already straight in its UVs, or a Split at Seams tear, shows nothing and a click there does nothing.
- Preview: cuts made by hand in the preview colour over the tears, straightened lines in the active colour, all the time the operator runs; while picking, the loop or edge under the cursor in the colour of what the click makes (a pick it takes back in the highlight colour).
- HUD: a "Straightened Lines" row with the count, only while there is one. Top line while picking: "Picking cut loops · Alt: single edge · C to stop" / "Picking lines to straighten · Alt: single edge · V to stop". Help: "Cut a loop / one edge" and "Straighten a loop / one edge" on LMB / Alt + LMB.
- A V click lays out on the live (warm) solve and the timer runs the cold one, like a Balance wheel step; Ctrl + Wheel with picked lines stays a warm step.

After validation (2026-11-24):
- A V loop is geometric, not the edge classes (which stop at every triangle and n-gon): a long side or an end is taken whole; a line inside is followed from the hovered edge, at each vertex on the edge that turns least (at most 30°) and runs within 45° of the line's axis, read on the strip's "EVEN" layout (both rails straight), up to the boundary (`uv_stripe_split_core.chain_through`). One click on the sample's centre line straightens all 30 edges of it.
- A C loop is the full cross path (`cross_path`) of the hovered edge, offered only when it runs rail to rail and `split_island` reads the island cut there (with the cuts already made) as strips without automatic cuts; a cut ending at a triangle fan's pole is therefore not offered (no change to `split_island`).
- A pick only adds a constraint: the piece is laid out without its lines first, the rails that layout keeps stay, the lines go on top with no further relaxation (`uv_stripe_auto_core._with_lines`); balanced with no rail only where the piece had no straight rail anyway (Straight Sides None, or Stretch Limit relaxed it to its real shape). Align (G) shows only for unfolded pieces, never for a balanced one.
- A line that could not be kept is not offered (`uv_stripe_balance_core.pick_allowed`: both rails or ends, a flattened edge or face, a real face corner squashed); a clicked line the layout still does not keep straight, or keeps only with infinite stretch, is taken back and not offered again.
- Under None, removing the last line that set the align edge restores Align. Objects whose islands all wait for help still draw their stored cuts and lines.

## Upright ends where cheap (decided 2026-11-24)
Revises "Slanted is the default" (Settings, Ends one by one, Decisions after validation 1). On the user's wide sample the trim piece needs square corners: both ends upright on the rectangle, the corners on it, the long sides straight; a chamfer at one corner and a notch in one rail keep their shape.
- **End line.** An upright end holds only its own line (`uv_stripe_balance_core.end_line`): the longest run of the end path by 3D length with no inner vertex sharper than 150° within the surface (the corners `uv_stripe_faces_core` measures as real). Vertices off the run keep a free u; a rail vertex keeps its rail v. An end with no such corner stands whole, as before.
- **Notch.** A straight rail holds its own line (`rail_line`): a short inner run (at most 6 edges) whose in-surface turns hold a left and a right turn over 15°, add up to under 10° and come back onto the incoming line keeps its own v.
- **Default.** Ends gains a first value, *Upright Where Cheap* (`AUTO`), the new default: on a strip several faces wide both ends upright, on a strip one face wide the real slant (as Slanted). W cycles Upright Where Cheap → Slanted → Both → Longer End → Shorter End. The old values keep their meaning (Both stays strict); a last-used value saved before stays as it was.
- **Relax margin** (`uv_stripe_auto_core.RELAX_MARGIN` = 0.05, wide strips only, `_choose_wide`): shapes are measured from the strictest; once a clean layout lies within Stretch Limit, the strictest clean one within 0.05 of it is taken; with none within the limit, the strictest clean one within 0.05 of the least stretched. Under Upright Where Cheap, free ends with the same rails are measured only when upright ends fold or exceed the limit, and taken only when they gain more than 0.05. Both rails stay straight when relaxing to one gains less than 0.05.
- **Per-end fallback.** When both ends upright fold a face, each end alone is tried before free ends (every strip).
- **Warm start.** An upright balanced solve starts from the free-ends solve of the same rails when that is converged and better (`_least_start`, `Prepared.looser`), as one-rail solves start from both rails.
- No pull slider (declined); Shift + Alt + Wheel stays free.
## One entry: every invoke is the interactive mode (decided 2026-11-24)
The user: "remove the non-interactive one, it's not needed". `iops.mesh_uv_stripe` starts the interactive mode on every invoke (key, menu, pie, search); the `interactive` property is gone. `execute` stays for the redo panel and scripts (a direct `bpy.ops.iops.mesh_uv_stripe(...)` call lays out at once). `IOPS_OT_Mesh_UV_Stripe_Interactive` is removed and `iops.mesh_uv_stripe_interactive` is listed in `utils/renamed_idnames.py` as renamed to `iops.mesh_uv_stripe`, so saved hotkeys and Edit Pie slots move over (a key bound to the old entry replaces an unbound row of the new one). The Edit pie's UV group and the pie slot list hold one entry, "UV Stripe".