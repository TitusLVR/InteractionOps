# Easy Mod — Curve

![Easy Mod — Curve](../img/ops/op_easy_mod_curve.png)

Wires a Curve modifier in one click. Select a mesh and a curve in Object Mode and run it: the curve origin is moved to its first point, the mesh is placed on it, and a Curve modifier is added (or the existing one updated). With only a deformed mesh selected it selects the curve driving it, so you can hop back to the path.

**Hotkey:** Not bound by default — run it from the iOps Pie › *Easy Modifier - Curve*, or from operator search.

## Options
- **Use Curve Radius** — scale the mesh by the curve radius.
- **Use Curve Length** — stretch or squeeze the mesh over the whole curve.
- **Use Curve Bounds** — ignore the offset along the deform axis.
- **Deformation Axis** — which axis of the mesh follows the curve.
- **Array - Fit Curve** — if the mesh also has an Array modifier, set it to Fit Curve with this curve.
- **Find and Replace Curve Modifier** — reuse the existing Curve modifier instead of adding a new one.

## Tips
- Tweak the options in the redo panel right after running.
- The 3D Cursor is used while aligning origins and stays where it ends up.
