# HUD / Help split + parameter dashboard

## Problem

Today's `HUDOverlay` does two jobs at once:

1. Displays the current state of operator toggles (key + label + on/off).
2. Acts as the only place the user sees "what keys do what" in a modal.

We want to split them:

- **HUD (near cursor)** = live operator-parameter dashboard. Shows current
  values of bool/int/float/string/enum params, both active and inactive. `/`
  hides the parameter rows but keeps the operator title visible.
- **Help (corner)** = hotkey legend. `H` collapses it to a single line
  ("Press H for help"). Has appear/disappear animation, configurable via
  the theme.
- **Stats / Info (corner)** = unchanged from today (already exists, position
  configurable). Mentioned here only because the Theme tab will group
  overlay settings.

Both toggle keys are rebindable in preferences.

## Goals

- Operators can show live parameter values (formatted per kind) in a
  cursor-following HUD.
- Help overlay is a separate corner-anchored panel with its own state.
- `/` (configurable) hides HUD param rows but keeps the title.
- `H` (configurable) collapses Help to a hint, restores on second press.
- Help has an appear/disappear animation with presets (`none`, `fade`,
  `slide-fade`) and configurable duration.
- All three overlays' positions/offsets/colors live under the Theme tab.

## Non-goals

- Migrating every existing operator to the new API in this PR — provide the
  primitives, migrate one or two as proof, leave the rest behind a deprecation
  comment.
- Animating the HUD itself. Only Help animates.
- Drag-to-reposition for Help (corners + offsets only).

## Architecture

### New: `HUDParam`

```python
@dataclass
class HUDParam:
    name: str            # full label shown in HUD ("Subdivisions")
    value_getter: Callable[[], Any]  # called every draw, returns current value
    kind: str            # "bool" | "int" | "float" | "str" | "enum"
    fmt: str | None = None   # optional format string for float ("{:.3f}")
    active: bool = True      # dim when False (parameter currently irrelevant)
```

`HUDOverlay` gains `add_param(param)` and `add_param_section(title, params)`.
The existing `HUDItem`/`add_section` API stays — it becomes the input to the
new `HelpOverlay`.

**Formatting rules:**
- bool → `✓` / `✗` (colors from theme: `hud_label_on` / `hud_label_off`)
- int → `{value}`
- float → `fmt or "{:.3f}"`
- str → `{value}`
- enum → `{value}` (whatever the getter returns, usually a string)

Inactive params use the `hud_label_disabled` role.

### Title-aware visibility

`HUDOverlay` gets:
- `self.params_visible: bool = True`
- `self.title: str | None`  ← operator title, always rendered when set
- `handle_param_toggle_event(event, prefs)` → toggles `params_visible`
  on the `hud_param_toggle_key` (default `SLASH`).

Drawing logic in `_render`: always draw `self.title` (if set) and any
`_header_lines`; only draw sections when `params_visible`.

The existing `handle_toggle_event` (full HUD on/off) stays but is now
considered "kill switch" — operators are encouraged to wire the new param
toggle instead.

### New: `HelpOverlay`

Lives in `ui/hud/help.py`. Mirrors `HUDOverlay`'s draw pipeline (uses the
same `hud_text` primitives + theme), but:

- Position: one of `top_left / top_right / bottom_left / bottom_right` with
  `offset_x / offset_y` from theme. No cursor-follow, no drag.
- State: `expanded` (full hotkey list) / `collapsed` (single line
  "Press {key} for help").
- Toggle key: `prefs.help_toggle_key`, default `H`.
- Animation: alpha multiplier driven by `time.perf_counter()` between two
  transition points; the operator's modal already calls `tag_redraw()` every
  frame so we get free animation without a timer.

**Animation presets** (`prefs.help_anim_preset`):
- `none` — instant.
- `fade` — alpha 0↔1 over `help_anim_duration` (default 0.18s).
- `slide-fade` — alpha 0↔1 + horizontal offset 12px → 0 (slides in from
  the edge it's anchored to).

`HelpOverlay` exposes:
```python
class HelpOverlay:
    def __init__(self, name: str): ...
    def add_section(self, section: HUDSection) -> None: ...
    def handle_toggle_event(self, event, prefs) -> bool: ...
    def draw(self, context, event=None) -> None: ...
```

### Operator wiring (example)

```python
def invoke(self, context, event):
    self.hud = HUDOverlay("loop_cut")
    self.hud.title = "Loop cut"
    self.hud.add_param(HUDParam("Cuts", lambda: self.cuts, "int"))
    self.hud.add_param(HUDParam("Smooth", lambda: self.smooth, "float",
                                fmt="{:.2f}"))
    self.hud.add_param(HUDParam("Even", lambda: self.even, "bool",
                                active_getter=lambda: self.has_flow))

    self.help = HelpOverlay("loop_cut")
    self.help.add_section(HUDSection("Loop cut", [
        HUDItem("More / fewer cuts", "WHEEL", ItemState.ON),
        HUDItem("Toggle even",       "E",     ItemState.ON),
        HUDItem("Confirm",           "LMB",   ItemState.ON),
        HUDItem("Cancel",            "ESC",   ItemState.ON),
    ]))

def modal(self, context, event):
    if self.hud.handle_param_toggle_event(event, prefs):
        return {"RUNNING_MODAL"}
    if self.help.handle_toggle_event(event, prefs):
        return {"RUNNING_MODAL"}
    ...
```

## Theme changes

New preferences:
- `hud_param_toggle_key` (string enum of event types, default `"SLASH"`)
- `help_toggle_key` (default `"H"`)
- `help_corner` (enum: 4 corners, default `"top_left"`)
- `help_offset_x` / `help_offset_y` (int)
- `help_anim_preset` (`none` / `fade` / `slide-fade`)
- `help_anim_duration` (float, 0.0–1.0, default 0.18)
- `help_hint_text` (string, default `"Press {key} for help"`,
  `{key}` is substituted with the actual toggle key)
- Help re-uses `color_hud_key` / `color_hud_label_*` for now (no new colors
  unless we hit a contrast issue).

## Migration

- `IOPS_OT_DrawThemePreview` migrates first (good showcase: params + help
  side by side).
- One real operator (pick a bisect / loop cut / etc. with visible params)
  migrates second.
- Other operators keep working unchanged because the old `HUDSection`/
  `HUDItem`/`add_section` API on `HUDOverlay` still exists — they just don't
  get a separate Help panel until migrated.

## Risk / open questions

- Param `value_getter` runs every draw. For float-heavy operators with
  expensive properties this could matter; mitigation = operators pass cheap
  lambdas (no work in the getter; just read attribute).
- Animation runs off `tag_redraw()`. If the operator forgets to redraw, the
  animation freezes. Acceptable: every modal we ship already redraws each
  frame.

## Verification

- Open theme preview → see params HUD next to cursor + Help panel in top-left.
- Press `/` → param rows vanish, title stays.
- Press `H` → Help collapses to hint with selected animation.
- Change anim preset + duration in prefs → effect visible on next toggle.
- Rebind `H` to e.g. `F1` in prefs → hint text updates to "Press F1 for help".
