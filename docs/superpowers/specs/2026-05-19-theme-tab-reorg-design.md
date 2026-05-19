# Theme tab: layout reorganisation + Help section

## Problem

User feedback on the current Theme tab:

1. **Text and Font are separate sections** — should be one.
2. **Color rows are horizontal** with abbreviated state names ("Closest",
   "Active", ...). User wants vertical rows: each state on its own line
   showing **full name | size | color**.
3. **"Surfaces & status"** is unclear — what is it / where is it used?
4. **Widgets section** has no sizes, just colors, and lacks the same
   "name | size | color" structure.
5. Help overlay (new, see `2026-05-19-hud-params-and-help-split-design.md`)
   needs its own section under Theme.

## Goals

- One **Text & Font** section.
- Point / Line / Text / Widgets each laid out as a vertical table:
  one row per state with `[full name] [size/width] [color]` columns. Full
  state name shown (no abbreviation).
- Rename "Surfaces & status" to something self-explanatory and add an info
  line describing where each color is used.
- Add a **Help** section (toggle key, corner, offset, animation preset,
  duration, hint text).
- New section ordering matches the new HUD/Help split.

## Non-goals

- Adding per-widget sizes that don't exist yet in the draw layer (widgets
  use one size for now — the "size" column is just `—` for them).
- Changing color values / defaults.
- Touching island palette layout (already fine).

## Section layout (top → bottom)

```
[Point]                  vertical, 5 rows (Default/Closest/Active/Locked/Preview)
[Line]                   vertical, 5 rows
[Text & Font]            vertical 5 rows + font_path at bottom
[Status colors]          renamed from "Surfaces & status"
[Widgets]                vertical, name/size/color (size column "—" if none)
[Island palette]         unchanged
[HUD]                    overlay-specific (position, padding, spacing, kill-switch key)
[Help]                   new — toggle key, corner, offset, anim preset, anim duration, hint text
[Statistics overlay]     unchanged
[Behaviour]              unchanged
```

## "Status colors" section content

The renamed section gets an explanatory header. Contents (unchanged from
today's "Surfaces & status"):

- `color_fill` — generic translucent fill (selection rectangles, debug
  bounds, drag previews).
- `color_error` — error feedback in operators (e.g. invalid input flash).
- `color_success` — success feedback (e.g. operation completed flash).

Header line: *"Operator feedback colors (used by status flashes and
generic fills)."*

## Vertical-table helper

Replace `_state_color_row` / `_state_float_row` with a single helper:

```python
def _state_table(parent, theme, prefix_color, prefix_size,
                 names=("Default", "Closest", "Active", "Locked", "Preview")):
    grid = parent.grid_flow(row_major=True, columns=3, align=True)
    grid.label(text="State");  grid.label(text="Size");  grid.label(text="Color")
    for state, label in zip(_STATES, names):
        grid.label(text=label)
        if prefix_size:
            grid.prop(theme, f"{prefix_size}_{state}", text="")
        else:
            grid.label(text="—")
        color_prop = f"color_{prefix_color}" if state == "default" else \
                     f"color_{state}_{prefix_color}"
        grid.prop(theme, color_prop, text="")
```

This gives a clean 3-column vertical layout for Point/Line/Text. Widgets
get a simpler 2-column variant (name + color).

## Widgets layout

Vertical, full name + color per row:

```
Handle              [color]
Handle (hover)      [color]
Pivot               [color]
Selection bbox      [color]
2D cursor           [color]
```

If we later add per-widget sizes, the helper switches to 3-column without
schema change.

## Text & Font merge

The Text & Font section contains:

- 5-row vertical table (state × size × color) — same helper as Point/Line.
- `font_path` (full-width row, with the existing info line).

## New Help section content

```
Toggle key            [hotkey selector → help_toggle_key]
Corner                [enum: TL/TR/BL/BR → help_corner]
Offset X              [int → help_offset_x]
Offset Y              [int → help_offset_y]
Hint text             [str → help_hint_text]
Animation preset      [enum: none/fade/slide-fade → help_anim_preset]
Animation duration    [float → help_anim_duration]
```

(All props themselves are added in the HUD-split spec; this section just
draws them.)

## Fold-state booleans

Rename in `IOPS_Theme`:
- `show_text` → covers Text & Font (was `show_text` + `show_font`).
- `show_surfaces` → `show_status` (matches new title; old name kept as
  alias for one release? — no, hard rename, this is internal UI state).
- New: `show_help`.

Remove `show_font` (folded into `show_text`).

## Verification

- Open Preferences → InteractionOps → Theme:
  - Point/Line/Text rows are vertical with 3 columns.
  - Full state names visible.
  - Font field appears under Text.
  - "Surfaces & status" is now "Status colors" with an info line.
  - Widgets uses vertical layout.
  - New Help section appears between HUD and Statistics, with all controls.
- Existing color/size values from a saved prefs file load correctly (no
  property renames in `IOPS_Theme`, only the UI draw code changes).
