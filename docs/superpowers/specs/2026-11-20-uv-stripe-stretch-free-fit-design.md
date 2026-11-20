# UV Stripe: stretch-free Fit to Active, stretch detection

## Intent
UV Stripe is mostly used to map strips onto trim textures: one strip is the reference (Active mode), the
others are laid onto its band. Today the other pieces come out stretched even with the True Shape or
No Stretch layout. The layouts are not at fault: `uv_stripe_core.fit_to_reference` scales every other piece
with a separate factor per axis (Width: U only, Height: V only, Width and Height: both, each its own), so
any piece whose proportions differ from the reference is stretched as a whole.

## Goals
- Fit to Active never stretches a piece: one scale factor for both axes.
- A strip mapped onto a trim band works with the defaults.
- The stretch that remains for other reasons (curved rails, a bend below Bend Angle, the Rectangles
  layout) is measured and shown, not guessed.

## Non-goals
- No new way of tearing strips by measured stretch, no relaxing of faces.
- No change to Visual UV's own Fit to Active (`uv_match_core.dimension_fit` stays as it is).

## Anti-goals
- A piece that is fitted differently from its neighbours by a hidden threshold.
- A piece turned across the trim band.

## Approaches
1. **Always uniform fit** (picked). Width / Height match that axis and scale the other by the same factor;
   Width and Height fits the piece inside the reference box. No option to learn, no stretch in any mode.
   A piece no longer equals the reference on the second axis.
2. **Keep Proportions toggle**, on by default. Keeps the old per-axis fit behind one more key and option.
   Dropped: the old behaviour is the bug the user reported, nobody asked to keep it.
3. **Automatic by threshold**: only pieces the fit stretches beyond a tolerance are scaled uniformly.
   Dropped: pieces fitted two different ways, not predictable by eye.

## Design

### Uniform fit (`utils/uv_stripe_core.fit_to_reference`)
- `WIDTH`: s = reference width / piece width, applied to U and V.
- `HEIGHT`: s = reference height / piece height, applied to U and V.
- `BOTH`: s = min of the two, so the piece fits inside the reference box.
- A degenerate piece side (zero) gives factor 1, as `dimension_scale` does.
- The piece's box centre still moves onto the reference's centre.
- **No quarter turn** (builder's call, stated to the user): every piece of one run is laid out by the same
  Orientation, so its length already runs along the reference's. The old turn only fired on a stub shorter
  than it is wide, and turned it across the band.
- The function no longer uses `uv_match_core.dimension_fit`; that module is not changed.

Shared through `uv_stripe_bridge.apply_maps`, so Inset, Edge Slide and UV Pipe get the same fit.

### Default
`active_fit` defaults to `HEIGHT` in UV Stripe (and in UV Pipe, which has its own property), so pieces
land on the reference's band at one texel density and run past it along U. With Orientation = Vertical the
band's size is the UV width: the user switches to Width (D). Item labels and descriptions are reworded:
they no longer promise an equal bounding box.

### Stretch detection
- Core: `face_stretch(points3d, points_uv) -> float`, pure python. For each fan triangle of the face the
  affine map 3D triangle → UV triangle has two singular values; the face's stretch is the largest
  ratio max/min over its triangles (1.0 = no stretch, uniform scale does not count). A degenerate triangle
  in 3D is skipped; one degenerate in UV only counts as infinite.
- `STRETCH_TOLERANCE = 1.05` (builder's call): a face above it is "stretched".
- The operator measures after the UVs are written, on the final UVs, for every laid-out face, and keeps
  the stretched faces in `_Result`.
- Shown in the modal: the stretched faces' edges drawn through `draw.edges_world` in a theme role
  distinct from the outline (`PREVIEW_LINE`) and the tears (`ERROR_LINE`); the HUD header and the status
  bar say how many faces are stretched. `execute` (redo panel, scripts) reports the count as a warning.
- Inset, Edge Slide and UV Pipe do not show it in this change.

## Tests
- `tests/test_uv_stripe_*`: uniform fit for the three modes (aspect kept, matched axis equal, centre on
  the reference, no turn for a portrait stub, degenerate side); `face_stretch` on an undistorted quad, a
  uniformly scaled one, one scaled on one axis, a sheared one, an n-gon, degenerate input.
- `tests/blender/test_uv_stripe_operator.py`: Active mode, two strips of different length, True Shape:
  no face above the tolerance; existing expectations that relied on the per-axis fit are updated.

## Docs
`docs/operators/op_mesh_uv_stripe.md` (Mode, Fit to Active, Controls, the stretch display) and the UV Pipe,
Inset and Edge Slide pages where they describe Fit to Active.

## Left to the builder
The exact role for the stretched faces, the wording of labels and messages, where the measuring helper
lives in the operator.
