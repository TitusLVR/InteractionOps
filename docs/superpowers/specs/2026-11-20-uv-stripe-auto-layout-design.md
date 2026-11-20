# UV Stripe: Auto layout

## Intent
UV Stripe should be "key, call, result". Today every call needs its Layout, Split at Bends and Bend Angle tuned by hand to the strip at hand. Auto makes those choices from the measured stretch of the result, so the keys become overrides, not a routine.

## Goals
- A new Layout, **Auto**, the default: it decides where a strip is torn and how each piece is laid out.
- One setting, **Stretch Limit**.
- The hand tools keep working under Auto: manual cuts, skipped tears, a ring's break, Split at Seams.

## Non-goals
- The other layouts and their keys stay as they are.
- Compacting the keys and the HUD, and applying without a confirm, are the next step, not this one.

## Anti-goals
- A gentle arc cut into one piece per face.
- A piece laid out bent: curvature is removed by tearing, never kept.

## The user's priorities
When straight rows, no stretch and no tear cannot all hold, give up in this order: tear first, then stretch, a bent shape last.

## Approaches
1. **Measured cuts, then a stretch limit per piece (picked).** Tear at every rule-made bend cut, drop the cuts that do not lower any face's stretch, then lay each piece out straight when its stretch is within the limit and as True Shape beyond it.
2. Try the layouts from straightest to truest on the whole strip and tear only when none fits. Rejected: the user wants the tear first.
3. Only compact the keys, or add presets. Rejected: the tuning stays manual.

A prototype of 1 on a real mesh (27 seam-bound strips, 91 faces) gave the same stretched faces as the current defaults with 35 pieces instead of 43. The stretch left comes from tapered faces, which no straight-row layout can lay out clean and True Shape can; hence the limit.

## Design
For one open strip:
1. **Candidate cuts**: the bend cuts at a tiny angle (0.5°), so the existing rules (triangulated strips, fan corners) choose the edges. Skipped tears are left out; manual and seam cuts always tear.
2. **Drop cuts that do not help**: with every candidate cut made, measure each face under its piece's best straight layout (the lowest worst stretch of No Stretch, Rectangles, Even Rows; on a tie in that order). A candidate is dropped when, without it, no face rises above both the stretched-face tolerance (1.05) and its previous value plus 0.01. Repeat, dropping the cut whose removal leaves the lowest total stretch, until none can go.
3. **Lay out each piece**: its best straight layout when that layout's worst face is within Stretch Limit; else True Shape when True Shape's worst face is lower; else the straight layout.

Stretch Limit: 1.25 by default, 1.0 to 3.0. At 1.0 every piece that stretches at all becomes True Shape.

A closed ring is opened as today (its break, a seam, or its sharpest corner) and the opened strip goes through the same steps; a ring that stays whole keeps Even Rows.

## Left to the builder
The function split between the pure cores and the bridge, the test meshes, and the HUD wording, within the repo's conventions.
