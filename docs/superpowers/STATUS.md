# Specs & Plans — Implementation Status

Snapshot as of 2026-05-21. Status reflects whether the design described in each spec is reflected in the code on `master`. Specs are historical artifacts — they are not rewritten after the fact; this file is the canonical record of "did it land".

Legend: ✅ implemented · 🟡 partial · ❌ not landed · 🗑 superseded

## Specs

| Date | Spec | Status | Evidence |
|---|---|---|---|
| 2026-04-16 | [waypoint-system-design](specs/2026-04-16-waypoint-system-design.md) | ✅ | `waypoint` symbols present in [`operators/mesh_uv_shortest_mark.py`](../../operators/mesh_uv_shortest_mark.py); plan committed. |
| 2026-04-17 | [astar-algorithm-design](specs/2026-04-17-astar-algorithm-design.md) | ✅ | A* added to Ctrl+Scroll cycle in [`operators/mesh_uv_shortest_mark.py`](../../operators/mesh_uv_shortest_mark.py); Rust port in [`rust/mesh_uv_shortest_mark_lib/`](../../rust/mesh_uv_shortest_mark_lib/). |
| 2026-04-17 | [waypoint-direction-and-path-smoother-design](specs/2026-04-17-waypoint-direction-and-path-smoother-design.md) | ✅ | Direction lock + smoother present in shortest_mark; plan committed. |
| 2026-04-20 | [curvature-bias-design](specs/2026-04-20-curvature-bias-design.md) | ✅ | `curvature_bias` references in [`operators/mesh_uv_shortest_mark.py`](../../operators/mesh_uv_shortest_mark.py). |
| 2026-05-15 | [unified-ui-system-design](specs/2026-05-15-unified-ui-system-design.md) | ✅ | Merged via `02a4d89 Merge feat/unified-ui-foundation`; shared [`ui/draw/`](../../ui/draw/) primitives, [`ui/hud/`](../../ui/hud/) overlay. |
| 2026-05-18 | [theme-palette-unification-design](specs/2026-05-18-theme-palette-unification-design.md) | ✅ | All legacy color/size prefs removed (`f775868`, `06cbf7a`); single `IOPS_Theme` in [`prefs/theme.py`](../../prefs/theme.py) with Point/Line/Text 5-state roles, widgets, axis, handle/pivot/bbox/cursor, island palette. |
| 2026-05-18 | [unified-drawing-system-analysis](specs/2026-05-18-unified-drawing-system-analysis.md) | ✅ | Analysis-only doc; recommendations folded into the unified-ui foundation work. |
| 2026-05-19 | [fix-preview-structrna-crash-design](specs/2026-05-19-fix-preview-structrna-crash-design.md) | ✅ | `a00a8c9 fix(draw): safeguard all draw_handlers against dead StructRNA`, `7fa6659 fix(theme-preview): use 3D viewport region`. |
| 2026-05-19 | [hud-params-and-help-split-design](specs/2026-05-19-hud-params-and-help-split-design.md) | ✅ | `c856cfb feat(hud): split HUD … from Help`, `13a984d feat(operators): migrate all modal operators to HUD/Help split`, `73440e1 Refactor HUD help overlay`. |
| 2026-05-19 | [theme-tab-reorg-design](specs/2026-05-19-theme-tab-reorg-design.md) | ✅ | Collapsible groups (`9ee2f20`), vertical color tables + Text/Font merge + Surfaces rename (`211de45`). |
| 2026-05-20 | [bevel-snap-mode-design](specs/2026-05-20-bevel-snap-mode-design.md) | ✅ | `9207e61 feat(bisect): add bevel mode for dual cuts`; ~85 bevel/snap_point refs in [`operators/mesh_cursor_bisect.py`](../../operators/mesh_cursor_bisect.py). |

## Plans

| Date | Plan | Status |
|---|---|---|
| 2026-04-16 | [waypoint-system](plans/2026-04-16-waypoint-system.md) | ✅ executed |
| 2026-04-17 | [waypoint-direction-and-path-smoother](plans/2026-04-17-waypoint-direction-and-path-smoother.md) | ✅ executed |
| 2026-04-20 | [curvature-bias](plans/2026-04-20-curvature-bias.md) | ✅ executed |
| 2026-05-15 | [unified-ui-foundation](plans/2026-05-15-unified-ui-foundation.md) | ✅ executed (merged via `feat/unified-ui-foundation`) |
| 2026-05-18 | [theme-palette-unification](plans/2026-05-18-theme-palette-unification.md) | ✅ executed |

## Notes

- No A* plan file exists — the A* spec was rolled into the broader shortest-mark work and landed without a separate written plan.
- No bevel-snap plan file exists — implementation was small enough to skip the plan step (single commit `9207e61`).
- All specs above remain accurate as historical descriptions of *intent at the time of writing*. Code may have evolved since; treat specs as orientation, the source as truth.
