# IOPS Pie: contextual groups and IOPS External pie

## Intent

The IOPS Pie (`ui/iops_pie_menu.py`, Ctrl+Alt+Shift+Q) is one flat column of
about 35 buttons plus boxes for third-party addons. It should be readable at a
glance: tools sorted into titled group boxes, only the groups that make sense
in the current mode, and room for the user-facing operators that are not in
the pie yet. Third-party addon links move to their own pie.

## Goals

- Group boxes in the four cardinal slots, a different set for Object Mode and
  Edit Mesh.
- Add the user-facing operators listed below that the pie lacks today.
- New pie **IOPS External** holding BMax, BMoI and B2RUVL.
- The pie never raises when an optional addon is missing (today
  `addons["B2RUVL"]` is read unguarded).

## Non-goals

- Internal operators (panel callers, list ops, preferences I/O, widget editor,
  modal hotkey tools such as Drag Snap) stay out of the pie.
- No change to the operators themselves, nor to IOPS Pie Edit and other pies.
- No user-editable grouping.

## Approaches

1. **Data table + one draw loop (picked).** Groups are declared as data:
   `(title, [(idname, text, props), ...])` per slot per context; one function
   draws a box and skips it when no button passed `op_if_poll`. Adding an
   operator later is one line.
2. Hand-written draw code per context. Same result, twice the code, and every
   new operator means touching layout code.
3. Sub-menus per group (`layout.menu`). Fewer pixels, but one more click for
   every tool, which defeats a pie.

## Design

### IOPS Pie, Object Mode (and any mode that is not Edit Mesh)

| Slot | Box | Buttons |
|------|-----|---------|
| Left | Transform & Align | Object Aligner, Align Between Two, 3 Point Rotation, Mirror Rotate, Match Dimensions, Normalize, Change Scale, Visual Origin, Drop It! |
| Right | Arrange | Object Replace, Radial Array, Grid, Grid to Center, To Grid From Active |
| Top | Select & Name | Select Similar Name, Name From Active, Search & Replace, Select Boolean Operands, Select Boolean Targets, Select Mirror Objects, Negative Scale Overlay (toggle) |
| Bottom | Vertex Color | same box as in Edit Mesh; buttons that do not poll in Object Mode are hidden |
| Top-left | Modifiers | Easy Modifier: Array Caps, Array Curve, Curve, SHWARP |
| Top-right | Assets & Files | Materials from Textures, Material Override, Render Asset Thumbnail, Reload Libraries, Reload Images |

### IOPS Pie, Edit Mesh

| Slot | Box | Buttons |
|------|-----|---------|
| Left | Mesh | Inset, Edge Slide, Straight Bevel, Shear, Hinge, Converge, Vert Fuse, Quick Connect, Quick Snap, Tris to Quads, Cursor Bisect, To Grid, Mesh Snapshot |
| Right | UV | UV Stripe, UV Pipe, UV Shortest Path Mark, UV Channel Hop, Visual UV |
| Top | Measure & Align | Copy Edge Length, Copy Edges Angle, Align Origin to Normal, Align Object to Face, Non-Planar Overlay (toggle) |
| Bottom | Vertex Color | colour swatch, Set Vertex Color, White / Grey / Black, Set Vertex Alpha; separator; Paint (`iops.mesh_vertex_paint`), the palette swatch row that starts the brush with that colour, Blur / Sharpen (`iops.mesh_vertex_color_filter`) |
| Top-left | Bevel | Pin & Unwrap Bevel, Bevel Edge Data Fix |

The IOPS Pie holds iOps operators only: ForgottenTools and Optiloops move to
IOPS External.

The Vertex Color box sits in the bottom slot in both modes. Its brush part
reuses the drawing of `IOPS_PT_VCol_Panel` (`ui/iops_tm_panel.py`): move that
code into a shared function, do not copy it.

Revised after the live check: boxes in Blender's diagonal slots overlap the
side columns, so the Top-left / Top-right groups are drawn as extra columns of
the Top panel, and Bottom-left / Bottom-right as columns of the Bottom panel.
The four diagonal pie slots stay empty. The Vertex Color column has a fixed
width so the swatch and the palette row do not stretch it.

Rules:

- Every button goes through `op_if_poll`; a box with no visible button is
  replaced by `pie.separator()` so slot order is kept.
- Labels are full names, no abbreviations.

### IOPS External pie

- `IOPS_MT_Pie_External` + bindable `iops.call_pie_external`, in a new
  `ui/iops_pie_external.py`, registered in `__init__.py` and listed in
  `prefs/hotkeys_default.py` with the default hotkey Ctrl+` (`ACCENT_GRAVE`),
  chosen by the user.
- Left: BMax (Send / Get by file format, plus the L / R / S reset toggles).
  Right: BMoI (Send / Get). Bottom: B2RUVL (UV map, Send to UVLayout, Send to
  RizomUV, Get from RizomUV). Top: ForgottenTools (Connect Spread, Grid Fill
  All, Dice Faces, Hinge, Separate Duplicate, Selection Sets). Top-right:
  Optiloops. The last two are mesh tools: their buttons go through
  `op_if_poll`, so they show in Edit Mesh only.
- Each box is drawn only when `get_addon` finds the addon; with none installed
  the pie shows a single "No external addons installed" label.

## Calls made by the author (not decided by the user)

- Exact group titles and which operator sits in which group.
- Curve, armature and other modes fall back to the Object set, filtered by poll.

## Left to the builder

- Verify every listed idname and its `poll()` in the source; drop a button
  whose operator needs invoke-time context the pie cannot give, and report it.
- Docs: update `docs/ui.md` (pie section) and add the External pie.
- Keep each touched file's line ending (`git ls-files --eol`), lint with
  `uvx ruff@0.12.0`.
