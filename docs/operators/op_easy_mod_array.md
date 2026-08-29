# Easy Mod — Array

![Easy Mod — Array](../img/ops/op_easy_mod_array.png)

Two shortcuts for setting up Array modifiers in Object Mode. **Array Caps** is interactive: select a middle piece (active), one or two cap pieces and optionally a curve, and it builds a capped array with the cap origins snapped to the ends. **Array Curve** is one click: select a mesh and a curve, and you get an Array fitted to the curve plus a Curve modifier.

**Hotkey:** Not bound by default — run both from the iOps Pie › *Easy Modifier - Array Caps* / *Easy Modifier - Array Curve*, or from operator search.

## Controls (Array Caps)
| Key | Action |
| --- | --- |
| <kbd>A</kbd> | Add / remove the Array modifier |
| <kbd>+</kbd> / <kbd>-</kbd> (numpad) | Increase / decrease the count |
| <kbd>X</kbd> / <kbd>Y</kbd> / <kbd>Z</kbd> | Place the cap origins along that axis |
| <kbd>F</kbd> | Swap start and end caps |
| <kbd>C</kbd> | Add / remove a Curve modifier (needs a curve in the selection) |
| <kbd>MMB</kbd> / Wheel | Navigate the viewport |
| <kbd>LMB</kbd> / <kbd>Enter</kbd> / <kbd>Space</kbd> | Apply |
| <kbd>Esc</kbd> / <kbd>RMB</kbd> | Exit (changes already made are kept) |
| <kbd>H</kbd> | Show / hide the help legend |

## Options (Array Curve)
- **Array - Fit Curve** — switch an existing Array modifier to Fit Curve and point it at the curve.
- **Merge** and **Merge Distance** — merge vertices between array copies.
- **Add Curve modifier** — also add a Curve modifier deforming along the spline.
- **Use Curve Radius / Length / Bounds** — the standard curve deform options.
- **Deformation Axis** — which axis of the mesh runs along the curve.

## Tips
- Array Caps needs exactly 3 or 4 selected objects: middle (active), caps, optional curve.
- Run Array Curve with only the arrayed mesh selected to jump to the curve that drives it.
