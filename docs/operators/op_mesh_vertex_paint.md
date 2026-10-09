# Vertex Paint Brush

Paints vertex colors with a brush directly in Edit Mesh or Object mode — no switch to Vertex Paint mode. The brush shares its settings with Blender's own Vertex Paint tool (radius, strength, color, falloff curve and the unified paint settings), while the stroke itself is applied by iOps: a ray against the object's base mesh, the vertices inside the radius, a falloff-weighted blend into the active color attribute. Works on POINT and CORNER color attributes (Float or Byte); a `Color` attribute is created when the mesh has none.

**Hotkey:** Not bound by default — assign a key in *Preferences › iOps › Keymaps*, or run it from the operator search. Also available: Vertex Color widget › Paint Brush (the colored swatches start the brush with that color).

## Controls
| Key | Action |
| --- | --- |
| LMB drag | Paint |
| Ctrl+LMB drag | Erase — blends back to the colors the mesh had when the brush started |
| E | Eraser mode toggle |
| T | Paint / Blur tool toggle. Blur smooths the colors under the brush toward their neighborhood mean and accumulates over passes |
| F / Shift+F | Radius / Strength via Blender's radial control |
| Ctrl+Wheel / Shift+Wheel | Radius / Strength |
| [ / ] | Radius |
| Alt+Wheel | Cycle the falloff preset (Custom, Smooth, Smoother, Sphere, Root, Sharp, Linear, Pow4, Inverse Square, Constant) |
| R / G / B / K / W | Brush color Red / Green / Blue / Black / White |
| Shift+R / Shift+G / Shift+B | Two-channel mixes: Yellow (R+G) / Cyan (G+B) / Magenta (R+B) |
| C | Custom color: popup color picker with alpha (also *Pick Color* in the widget; the panel has the picker inline) |
| A | Toggle RGB / Alpha channel. RGB paints color and keeps alpha; Alpha paints only alpha |
| Shift+0 / Shift+1 | Brush alpha 0 / 1 |
| 1 / 2 / 3 | Element mode: Vert / Edge / Face (see below) |
| N | Front faces only (toggle) — skip vertices facing away from the view |
| M | Mute modifiers (toggle) — see below |
| V | Wireframe overlay (toggle) — the viewport's *Wireframe* overlay, to see where vertices and edges are |
| P | Preview VC (toggle) — the same temporary emission-material preview as the widget's Preview VC flipbox |
| Ctrl+Z / Ctrl+Shift+Z | Undo / redo one stroke inside the brush session |
| Enter / Space / RMB | Finish — the whole session becomes one global undo step |
| Esc | Cancel — restores every color to the state before the brush started |
| H | Help / HUD toggle |
| MMB / Wheel / Numpad / NDOF | Viewport navigation passes through: orbit, pan, zoom and numpad views work while the brush is up |

Strokes do not accumulate: dragging back and forth over the same spot within one stroke never exceeds brush strength, like Blender's default brushes. Each new stroke blends on top of the previous one.

## Element modes
| Mode | What gets painted |
| --- | --- |
| **Vert** (1) | Every vertex inside the radius, weighted by its distance to the brush center |
| **Edge** (2) | Every edge whose midpoint is inside the radius; both end vertices get the edge's weight |
| **Face** (3) | Every face whose center is inside the radius, plus the face under the cursor at full weight. On a CORNER color attribute only that face's corners are written, so adjacent faces keep their color — a hard per-face fill. On a POINT attribute the face's vertices are painted |

## Blur / Sharpen post-process
`iops.mesh_vertex_color_filter` runs over the whole active color attribute (Object mode) or the selected vertices (Edit Mesh mode, *Selected Only*). **Blur** moves every color toward the mean of its edge-neighborhood (own corners plus adjacent vertices), **Sharpen** pushes it away (unsharp mask), clamped to 0..1. The redo panel has *Amount*, *Iterations* and the channel set (RGB / Alpha / RGBA). Buttons: sidebar panel *Post Process* box and the Vertex Color widget (Blur / Sharpen).

## Brush settings
Radius, strength and RGB come from `Tool Settings › Vertex Paint › Brush` (honoring *Unified* size / strength / color). When the Vertex Paint brush slot is empty — Blender 4.3+ only fills it once Vertex Paint mode was entered — iOps creates a brush named `IOPS Vertex Paint`. The falloff follows the brush's *Falloff* preset; *Custom* evaluates the brush curve. Tablet pressure scales radius / strength when the brush's *Size Pressure* / *Strength Pressure* toggles are on.

Brush alpha, tool (Paint / Blur), element mode, channel mode (RGB / Alpha), eraser, front-only and mute-modifiers are iOps scene settings. The sidebar panel *iOps › IOPS Vertex Color › Paint Brush* exposes all of them next to radius, strength, falloff and color; the Vertex Color widget carries the Mute Mods flipbox.

## Modifiers
Every dab tags the mesh for update, which re-evaluates the object's modifier stack in Object mode (and in Edit mode when modifiers show in edit mode). On a heavy stack this makes the brush sluggish. Turn on **Mute Mods** (or press M while painting): the viewport visibility of all modifiers on the active object is switched off for the session and restored when the brush finishes or cancels. The ray is always cast against the base mesh, so a Mirror or Subdivision modifier never affects where the brush lands — paint on the unmodified geometry.

## Seeing the colors
The brush does not change viewport shading by itself. Press **P** (or use the widget's / panel's **Preview VC** toggle) for the temporary emission material override, use Solid shading with *Color: Attribute*, or a material that reads the color attribute.

## Widget
The Vertex Color widget (`presets/widgets_demo/vertex_color.json`) gains a *Paint* section: two rows of color swatches that launch the brush with that color (R G B W / Y C M K), a row with the current brush color swatch (launches the brush as is), *Pick* (color popup), *Blur* and *Sharpen*, and a Mute Mods / Preview VC / Wire flipbox row. The widget stays clickable while the brush runs — clicks on its panel pass through.
