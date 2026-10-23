# Visual Widget Editor — Design

Date: 2026-10-23
Status: draft, awaiting approval

## Intent

Composed GPU widgets (`widgets/composed.py`, JSON in
`<user scripts>/presets/IOPS/widgets/*.json`) are today edited by hand or by
asking Claude to edit the JSON. The title-bar pen button (`iops.widget_edit`)
just opens the file in a text editor, and the user barely uses it. Layout
work in particular (sizes, alignment, order) takes several describe/look
round trips. The user wants to **move things themselves and see the result
immediately**: a WYSIWYG editor working on the live widget in the viewport.

## Goals

1. **Edit in place.** The pen button on a composed widget's title bar enters
   *edit mode* on that live widget. It no longer opens the text editor.
2. **Reorder** by dragging cells within a row, between rows, and into or out
   of rows.
3. **Size** cells by dragging the right edge. Widths snap to a **12-step grid**
   per row (halves, thirds, quarters, sixths).
4. **Align** with **spacer cells**: empty cells on the same grid. A spacer on
   the left pushes content right, and spacers on both sides center it. A
   spacer can also stand alone as a full-width row to make a vertical gap.
5. **Add** any supported element (Section, Spacer, Row, Slider, Presets,
   FlipBox, Button, Buttons, Dropdown, Input, Swatch) by dragging it from a
   floating **GPU "Add" palette widget** into the edited widget. A drop
   indicator shows where it will land.
6. **Edit properties** of the selected element, plus widget-level settings,
   in a normal Blender **N-panel** (real text fields, operator search, enum
   pickers). This covers everything the schema supports per type: label,
   prop / target / data / switch binding, op + op_kwargs, role, value_type,
   min/max/snap/fmt, values, items, labels, items_from, unit, color,
   show_alpha, show_if, plus the new width/span. Widget level: title, space,
   width, switches defaults.
7. **New widget from blank.** A "New Widget" button in the prefs Widgets tab
   creates an empty composed widget, shows it in the viewport and enters
   edit mode.
8. **Save / Cancel.** Save writes the JSON via `composed.save_def` and
   re-registers the widget. Cancel discards every change since edit mode
   was entered.

## Confirmed behaviour (user said yes)

- **Ctrl+Z / Ctrl+Shift+Z work while editing.** They undo and redo editor
  changes (moves, resizes, adds, deletes, property edits).
- **Python-built widgets stay read-only.** Edge Data, ccp_data_ops and other
  widgets without a `composed_def` get no edit mode. This matches the
  current `render.is_editable`.
- **Controls are inert while editing.** Clicks select, drags move or resize,
  and no operator fires and no property value changes.
- **The N-panel opens automatically** on entering edit mode in that viewport.
  On exit it goes back to its previous open or closed state.

## Anti-goals

- **Lag.** The user named this as the one thing that matters. Dragging,
  resizing and palette drops must feel instant at viewport frame rate.
  Concretely:
  - No disk I/O and no `validate_def`/`make_widget` rebuild on every
    mouse-move. Mouse-move only updates lightweight drag state (ghost rect,
    drop target, snapped span) and tags a redraw of the one region.
  - Rebuilding the widget from the in-memory def happens once per committed
    change (drop, resize release, property edit), not continuously.
  - The editor adds no cost when nothing is being edited (same "zero idle
    cost" rule as the existing interact modal).
- Edit mode must not leak: leaving it by Save, Cancel, closing the widget,
  file load or addon reload restores normal interaction and the N-panel
  state.

Everything else is open to iteration. The user will give feedback
("no sweat").

## Layout model extension (schema)

The current layout splits a `ROW` equally (BUTTON cells hug their label via
`col_spec`), and consecutive top-level FLIPBOX rows auto-merge
(`merge_flipbox_runs`). Two additions:

- **`span`** (int 1–12) on any cell inside a `ROW`, and on a top-level row.
  It is the cell's width in twelfths of the content width. Cells may sum to
  less than 12; the remainder is empty space on the right.
- **`SPACER`** row type: an empty cell with a `span`. At top level a SPACER
  row is a vertical gap with an optional `height` in px. Spacers draw
  nothing outside edit mode. In edit mode they draw hatched with a dashed
  outline.

Backward compatibility: a definition with no `span` anywhere renders
exactly as today, using the current equal-split / hug rules. Once a row has
any `span`, the whole row uses the 12-step grid. The editor writes an
explicit span for every cell of a row once the user resizes anything in it
(builder's call on finer details). Existing hand-written JSONs must
round-trip through the editor without losing keys the editor doesn't
model. The schema reference (`ai_skills/iops-custom-widgets/schema-reference.md`)
and the skill doc get the new keys.

**Flipbox auto-merge:** the editor writes explicit `ROW`s for anything
side-by-side, so stacked FlipBoxes that the user wants stacked must stay
stacked after save. The builder picks the mechanism (e.g. writing them as
single-cell ROWs, or not merging rows that carry `span`). Old files keep
merging as today.

## Interaction (edit mode)

As mocked up in `.superpowers/brainstorm/.../editor-hybrid.html`:

- **Edited widget:** orange outline, an "EDITING" tag in the title bar,
  faint 12-step grid lines and a dotted outline per row.
- **Select:** click a cell. The selection is outlined and shows a resize
  handle on its right edge.
- **Move:** drag a cell. A green insertion line or ghost cell shows the
  target: before or after a row (becomes its own row), or inside a row
  between cells (joins the row and converts a top-level row into a `ROW`
  as needed). Dropping a ROW's last cell elsewhere removes the empty ROW.
- **Resize:** drag the right-edge handle. The width snaps to twelfths and
  the neighbours don't change. If a row would exceed 12, the resize clamps.
- **Delete:** X / Delete key on the selection, and a Delete button in the
  N-panel.
- **Add palette:** a separate floating GPU widget, shown only during edit
  mode, near the edited widget and draggable like any widget. Its items are
  grouped into Layout (Section, Spacer, Row) and Controls. Dragging an item
  into the edited widget inserts a new element with sensible placeholder
  values (e.g. Button with label "Button" and no op yet). A new element
  needs a binding or op before it can be valid. The editor must let it
  exist unbound while editing and show it as a placeholder. On Save,
  incomplete elements are reported, and the builder decides whether to
  block the save or drop them with a warning.
- **N-panel tab "Widget Editor"** (or the existing IOPS tab): "Selected:
  <Type>" property block for the current selection, the Widget block
  (title, width, space, switches), then Save / Cancel. A secondary "Open
  JSON" button keeps the old text-editor behaviour as a fallback.

## Constraints

- Blender 5.1+, the existing ui/widgets architecture: a persistent
  POST_PIXEL draw handler and a transient modal `iops.widget_interact`,
  poll-gated by panel bounds. Edit-mode gestures route through that same
  path or a sibling modal. Keep the pure / bpy-free split: editor model
  operations (insert, move, resize, delete, span math, def round-trip,
  undo stack) belong in a bpy-free module with pytest coverage like
  `panel.py` / `controls.py`.
- Undo is **editor-local** (a snapshot stack of the in-memory def). It does
  not use Blender's undo, because the JSON def is not scene data. While
  edit mode is active, Ctrl+Z/Ctrl+Shift+Z go to the editor stack.
- To verify early: whether `Region.active_panel_category` can be set in
  5.1. If it can't, the editor panel lives in its own tab so opening the
  sidebar lands on it as often as possible.
- MCP cannot inject modal mouse events (known). Gesture logic gets unit
  tests, and live drag feel is checked by the user.
- Widget JSONs are user content in `B:\scripts\presets\iops\widgets`, not
  shipped in the repo.

## Implicit exit keeps a draft (user decision)

If edit mode ends without Save or Cancel (the widget is closed, a file is
loaded, the addon is reloaded or unregistered, Blender quits), the in-memory
def is written to a **draft file** next to the widget JSON, for example
`<name>.draft.json`. `composed.load_all` must ignore drafts, so they never
register as widgets. The next time edit mode is entered on that widget, the
editor offers **Resume draft / Discard draft**. Save and Cancel both delete
the draft (an older draft still waiting for Resume/Discard is kept, and
editing is locked until the user decides). A draft for a New Widget that was
never saved is offered when that widget's edit mode is opened with its pen. Writing the draft must survive the
known addon-reload traps (restricted `bpy.context`/`bpy.data` during
register/unregister). Use plain file I/O on the def that is already in
memory, and touch no bpy data.

## Decisions made by Claude (user to review)

- **Edit mode shows everything.** Every row and cell is drawn regardless of
  `show_if` or widget `poll`, and anything hidden in the current context is
  drawn dimmed with a small "hidden" mark. Screen cells then map 1:1 to def
  paths, and edge widgets can be edited outside Edit Mesh.
- **Save writes the normalized form.** The editor works on the validated def,
  and Save writes it cleaned, with defaults filled in. If validation dropped
  anything when the widget was loaded (invalid rows, unknown keys), entering
  edit mode warns about it, and the first Save writes a one-time
  `<name>.json.bak` of the original file. Prefs Rename/Duplicate stay as
  they are.
- **`show_if` on ROW cells.** The schema is extended so a cell inside a ROW
  can carry `show_if`. A hidden cell leaves its grid slot empty (which falls
  out of the span model naturally). ROW containers stay selectable via a
  row gutter or handle in edit mode, to edit the ROW's own `show_if`, delete
  it or move it. An element dragged into or out of a ROW keeps its own
  `show_if`.
- **The rest of Blender stays usable** during edit mode (orbit, select, mode
  switch, tools). Editor hotkeys (Ctrl+Z, Ctrl+Shift+Z, X/Delete) only act
  while the mouse is over the edited widget or the Add palette, so scene
  undo and mesh delete work everywhere else. The N-panel gets Undo/Redo
  buttons.
- **Renaming is in scope.** The widget `name` is editable in the N-panel's
  Widget block, and Save then runs the existing rename path (file move,
  prefs list, toggle-hotkey `rename_toggle_kmi`). The prefs "+"
  (`iops.widget_def_add`) becomes the New Widget flow (blank widget, shown,
  in edit mode).

## Left to the builder

- Exact keymap and modal structure for edit mode (one long-lived modal vs.
  per-gesture modals plus an editor-state flag).
- How N-panel fields bind to the in-memory def (e.g. a WM PropertyGroup
  mirrored to and from the selected element).
- Palette contents ordering and visual style (follow the existing theme
  roles).
- Placeholder defaults for new elements.
- Whether title / space / width can also be edited directly on the widget
  (not required).
