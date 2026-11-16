# Falloff Fields Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the self-contained falloff modal tools with scene-level falloff fields (stackable, viewport-editable) that Move / Rotate / Scale / Normal Offset read, with F9 adjust-after-confirm.

**Architecture:** Fields are property groups under `Scene.IOPS.falloff`. A bpy-free core turns "points + plain stack description" into weights. Operators snapshot the stack into their own collection property, are `REGISTER | UNDO`, and compute everything in world space over all edit-mode meshes. A WorkSpaceTool with a gizmo group provides handles; field visuals and the weight preview are drawn by module-level draw handlers shared by the tool and the running operators.

**Tech Stack:** Blender 5.x Python API (bpy, bmesh, gpu, Gizmo / GizmoGroup / WorkSpaceTool), numpy, pytest, the repo's `ui/draw` and `ui/hud` modules.

**Spec:** `docs/superpowers/specs/2026-11-16-falloff-fields-design.md` — read it before any task.

## Global Constraints

- Branch `falloff-fields` in the main checkout `D:\git\InteractionOps`. **No worktrees** (Blender only loads this checkout through the `B:` symlink).
- `operators/save_load_space_data.py` has an unrelated uncommitted change. Never stage, commit or revert it. Stage files by explicit path only.
- The repo is public. Never commit anything from `B:\test\falloff_reference\`, never name the reference product or its author, never name the user's employer.
- `utils/falloff_core.py` stays bpy-free (numpy only).
- Operator idnames `iops.mesh_falloff_move`, `iops.mesh_falloff_rotate`, `iops.mesh_falloff_scale` must not change.
- Field geometry and all weight / transform maths are **world space**.
- Linear: 0 % at Start, 100 % at End. Radial / Elliptical: 100 % at centre. Bidirectional: 0 % at both ends, 100 % at midpoint.
- Curves are the existing `SHAPES` tuple, unchanged.
- No draw handler, gizmo group, tool or app handler may survive add-on unregister.
- pytest: `python -m pytest tests -q` from the repo root. Headless Blender: `BLENDER_USER_RESOURCES="<an empty folder under %TEMP%>" "V:\SteamLibrary\steamapps\common\Blender\blender.exe" --background --factory-startup --python-exit-code 1 --python tests/blender/<file>` — the isolated user folder is required: the scripts refuse to run unless Blender's user resources, scripts and extensions folders lie under the temp dir (`tests/blender/_isolation.py`); `BLENDER_USER_SCRIPTS` / `BLENDER_USER_EXTENSIONS`, if set, must point there too (scripts enable the add-on with the `enable_addon()` helper pattern from `tests/blender/test_draw_handlers.py`).
- Never touch the user's running Blender session (MCP port 9999 / blinker 9902) in this plan. All Blender work uses a separately launched instance.
- Commit after every task with the trailer lines from the session's attribution reminder. Task 7 squashes everything (including the spec and plan commits) into one feature commit.
- The old operator code is the reference for mouse→amount mapping, HUD building and draw idioms: `git show master:operators/falloff/common.py`, `git show master:operators/falloff/ops.py`.

## Review Focus

1. **Degenerate field** (Start == End, zero radius, zero secondary radii): weights are finite, no NaN reaches the mesh, operators still run. → Task 1 tests.
2. **Rotated / non-uniformly scaled objects in multi-object edit**: a vertex with weight 0 comes back bit-for-bit unchanged; a weight-1 vertex moves by the world-space amount regardless of its object's matrix. → Task 3 headless test.
3. **Unregister while the Falloff tool is active** (dev reload does this constantly): no leaked draw handler, tool, gizmo group or `depsgraph_update_post` entry; enable again works. → Task 5 headless test.
4. **Nothing selected / hidden geometry / empty mesh**: nothing selected → all visible verts; hidden verts never move; a mesh with zero verts cancels with a report, no exception. → Task 3 headless test.
5. **Stack with every field disabled, or empty after Clear, at F9 time**: weight 1 everywhere, operator behaves like the plain transform, no index error from `active_index`. → Task 1 test (core) and Task 4 headless test (operator).

---

### Task 1: Weight core — new field types, stack, fits

**Files:**
- Modify: `utils/falloff_core.py`
- Modify: `tests/test_falloff_core.py`

**Interfaces — Produces** (all numpy float64; `P` is `(N,3)`):

```python
FALLOFF_TYPES = ("LINEAR", "RADIAL", "ELLIPTICAL", "BIDIRECTIONAL")
BLEND_MODES = ("REPLACE", "ADD", "SUBTRACT", "MULTIPLY", "MIN", "MAX")
FIT_MODES = ("PCA", "X", "Y", "Z")
MIN_SIZE = 1e-4

def weight_linear(P, S, E) -> W            # 0 at S, 1 at E, clamped; S==E -> ones
def weight_bidirectional(P, S, E) -> W     # 1 - |2t - 1|, t clamped to [0,1]; S==E -> ones
def weight_radial(P, C, r) -> W            # unchanged
def ellipsoid_frame(start, end, radii2, roll) -> (axes(3,3), radii(3,))
    # axes[:,0] = unit(end-start); axes[:,1:] = basis_from_normal-style perpendiculars
    # rotated by `roll` radians about axes[:,0]; radii = (|end-start|, radii2[0], radii2[1]),
    # each floored at MIN_SIZE
def weight_elliptical(P, C, axes, radii) -> W   # 1 - clip(|((P-C) @ axes) / radii|, 0, 1)
def field_weight(P, field: dict) -> W      # geometry -> shape_curve(field["curve"]) -> invert
def stack_weights(P, stack: list[dict]) -> W
def fit_axis(P, mode: str) -> (S, E)       # through bbox centre, at the extents of the projection
def fit_field(P, ftype: str, mode: str) -> dict   # keys: start, end, radii, roll
def apply_normal_offset(P0, W, N, d: float) -> P   # P0 + W[:,None] * d * N
```

A field dict has exactly these keys: `type, start, end, radii, roll, curve, invert, strength, blend, enabled` (`start`/`end` 3-sequences, `radii` 2-sequence). `Radial` uses `start` as centre and `|end-start|` as radius. `stack_weights` skips `enabled == False`; with no enabled field returns ones; the first enabled field always acts as `REPLACE`; blend formulas and per-step clamp exactly as in the spec's "Weight evaluation".

`fit_axis("PCA")`: first principal direction of `P - mean`, sign flipped so its largest-magnitude component is positive; fewer than 2 distinct points → falls back to `"X"`. `fit_field`: LINEAR / BIDIRECTIONAL → `start, end = fit_axis`; RADIAL → `start` = bbox centre, `end` = centre + axis direction × half bbox diagonal; ELLIPTICAL → `start` = bbox centre, `end` = centre + axis direction × half extent along it, `radii` = half extents along the two perpendicular frame axes, `roll` = 0. All sizes floored at `MIN_SIZE`.

Delete: `weight_screen`, `project_points`, `weight_coplanar_faces`, `vertex_weights_from_faces`, `connected_mask`, `coplanar_grow`, `autofit_linear`, `autofit_radial`, and every test of them. Keep `shape_curve`, `apply_invert`, `bbox_center`, `apply_move`, `apply_rotate`, `apply_scale`, `basis_from_normal`.

Note for the implementer: after this task the old operators in `operators/falloff/` are broken at runtime (they call deleted functions). That is expected; Task 3 replaces them.

- [ ] **Step 1: Write failing tests** (replace the removed tests; keep the shape and transform tests). Required tests and assertions:

```python
def F(**kw):   # test helper: a complete field dict with defaults
    d = dict(type="LINEAR", start=(0,0,0), end=(1,0,0), radii=(1,1), roll=0.0,
             curve="LINEAR", invert=False, strength=1.0, blend="REPLACE", enabled=True)
    d.update(kw); return d

P = np.array([[0,0,0],[0.5,0,0],[1,0,0],[2,0,0],[-1,5,0]], float)

def test_types_and_blends_are_stable():
    assert fc.FALLOFF_TYPES == ("LINEAR","RADIAL","ELLIPTICAL","BIDIRECTIONAL")
    assert fc.BLEND_MODES == ("REPLACE","ADD","SUBTRACT","MULTIPLY","MIN","MAX")

def test_linear_zero_at_start_one_at_end():
    assert fc.weight_linear(P,(0,0,0),(1,0,0)).tolist() == pytest.approx([0,.5,1,1,0])

def test_bidirectional_peaks_at_midpoint():
    assert fc.weight_bidirectional(P,(0,0,0),(1,0,0)).tolist() == pytest.approx([0,1,0,0,0])

def test_elliptical_axes_are_independent():
    axes, radii = fc.ellipsoid_frame((0,0,0),(2,0,0),(1,4),0.0)
    assert radii.tolist() == pytest.approx([2,1,4])
    Q = np.array([[0,0,0],[1,0,0],[2,0,0]], float)
    assert fc.weight_elliptical(Q,(0,0,0),axes,radii).tolist() == pytest.approx([1,.5,0])
    # a point 0.5 along axis 1 (radius 1) and one 2 along axis 2 (radius 4) both weigh 0.5
    assert fc.weight_elliptical(np.array([axes[:,1]*0.5, axes[:,2]*2.0]),(0,0,0),axes,radii
                                ).tolist() == pytest.approx([.5,.5])

@pytest.mark.parametrize("ftype", fc.FALLOFF_TYPES)
def test_degenerate_field_is_finite(ftype):
    w = fc.field_weight(P, F(type=ftype, start=(1,1,1), end=(1,1,1), radii=(0,0)))
    assert np.all(np.isfinite(w)) and w.min() >= 0 and w.max() <= 1

def test_field_weight_applies_curve_then_invert():
    w = fc.field_weight(P, F(curve="SHARP", invert=True))
    assert w.tolist() == pytest.approx([1, .75, 0, 0, 1])

A = F()                                   # weights [0,.5,1,1,0]
B = F(start=(1,0,0), end=(0,0,0))         # weights [1,.5,0,0,1]
@pytest.mark.parametrize("blend,expected", [
    ("REPLACE",[1,.5,0,0,1]), ("ADD",[1,1,1,1,1]), ("SUBTRACT",[0,0,1,1,0]),
    ("MULTIPLY",[0,.25,0,0,0]), ("MIN",[0,.5,0,0,0]), ("MAX",[1,.5,1,1,1])])
def test_stack_blend_modes(blend, expected):
    assert fc.stack_weights(P,[A, dict(B, blend=blend)]).tolist() == pytest.approx(expected)

def test_stack_strength_scales_contribution():
    assert fc.stack_weights(P,[A, dict(B, blend="ADD", strength=0.5)]
                            ).tolist() == pytest.approx([.5,.75,1,1,.5])
    assert fc.stack_weights(P,[A, dict(B, blend="MULTIPLY", strength=0.0)]
                            ).tolist() == pytest.approx([0,.5,1,1,0])

def test_stack_first_enabled_field_replaces_regardless_of_blend():
    assert fc.stack_weights(P,[dict(A, blend="SUBTRACT")]).tolist() == pytest.approx([0,.5,1,1,0])

def test_stack_empty_or_all_disabled_is_ones():
    assert fc.stack_weights(P,[]).tolist() == [1]*5
    assert fc.stack_weights(P,[dict(A, enabled=False)]).tolist() == [1]*5

def test_fit_pca_follows_long_direction():
    t = np.linspace(-3,3,50); cloud = np.stack([t, t, 0.01*np.sin(t)],1)
    S,E = fc.fit_axis(cloud,"PCA"); d = (E-S)/np.linalg.norm(E-S)
    assert d.tolist() == pytest.approx([2**-.5, 2**-.5, 0], abs=1e-2)
    assert np.linalg.norm(E-S) == pytest.approx(6*2**.5, rel=1e-2)

def test_fit_axis_aligned_uses_bbox_extents():
    box = np.array([[0,0,0],[4,2,1]], float)
    S,E = fc.fit_axis(box,"Y")
    assert S.tolist() == pytest.approx([2,0,.5]) and E.tolist() == pytest.approx([2,2,.5])

def test_fit_pca_single_point_falls_back():
    S,E = fc.fit_axis(np.zeros((1,3)),"PCA"); assert np.all(np.isfinite(S)) and np.all(np.isfinite(E))

def test_fit_field_radial_and_elliptical():
    box = np.array([[0,0,0],[4,2,2]], float)
    r = fc.fit_field(box,"RADIAL","X")
    assert np.asarray(r["start"]).tolist() == pytest.approx([2,1,1])
    assert np.linalg.norm(np.asarray(r["end"])-np.asarray(r["start"])) == pytest.approx(24**.5/2)
    e = fc.fit_field(box,"ELLIPTICAL","X")
    assert np.asarray(e["end"]).tolist() == pytest.approx([4,1,1])
    assert sorted(e["radii"]) == pytest.approx([1,1])

def test_normal_offset():
    N = np.array([[0,0,1],[0,0,1]], float); P0 = np.zeros((2,3))
    assert fc.apply_normal_offset(P0, np.array([1,.5]), N, 2.0)[:,2].tolist() == pytest.approx([2,1])
```

- [ ] **Step 2:** Run `python -m pytest tests/test_falloff_core.py -q` — expect failures for the new names.
- [ ] **Step 3:** Implement the interface above in `utils/falloff_core.py`; delete the listed functions. Update the module docstring (world space, field/stack model).
- [ ] **Step 4:** Run `python -m pytest tests -q` — all pass (other test files untouched).
- [ ] **Step 5:** Commit `feat(falloff): field types, stack blending and fits in the weight core`.

---

### Task 2: Scene property groups, edit-mesh domain, stack and fit operators

**Files:**
- Create: `operators/falloff/props.py`, `operators/falloff/domain.py`, `operators/falloff/fields.py`
- Modify: `prefs/addon_properties.py` (remove the eight `falloff_*` props at ~656–685, add `falloff: PointerProperty(type=IOPS_FalloffSettings)`), `__init__.py` (imports + `classes`; the two property groups must be listed before `IOPS_SceneProperties`)
- Test: `tests/blender/test_falloff_fields.py`

**Interfaces — Consumes:** Task 1 core.

**Produces:**

```python
# props.py
class IOPS_FalloffField(PropertyGroup):
    name; type (FALLOFF_TYPES, default "LINEAR"); start, end (FloatVector 3, subtype TRANSLATION)
    radii (FloatVector 2, default (1,1), min 0); roll (Float, ANGLE)
    curve (SHAPES, default "LINEAR"); invert (Bool); strength (Float 0..1, default 1)
    blend (BLEND_MODES, default "REPLACE"); enabled (Bool, default True)
class IOPS_FalloffSettings(PropertyGroup):
    fields (Collection of IOPS_FalloffField); active_index (Int)
    show_weights (Bool, default True)
    basis (enum LOCAL/CURSOR/WORLD/NORMAL — items copied from the removed falloff_basis)
    use_custom_pivot (Bool); pivot (FloatVector 3, TRANSLATION)
    last_type (FALLOFF_TYPES, default "LINEAR")
    fit_mode (FIT_MODES); fit_signature (String)        # Fit cycling state
def field_to_dict(field) -> dict            # the Task 1 field dict
def dict_to_field(d: dict, field) -> None
def stack_to_list(fields) -> list[dict]     # any collection of IOPS_FalloffField
def copy_stack(src_fields, dst_fields) -> None   # clear dst, add + copy every prop incl. name
def active_field(settings) -> IOPS_FalloffField | None   # None when empty / index out of range

# domain.py
class Domain:
    entries: list   # per object: obj, bm, verts (list[BMVert]), mw (4x4 np), mw_inv (4x4 np),
                    #             slice (rows of this object in the concatenated arrays)
    P: np.ndarray   # (N,3) world positions of the domain verts
    N: np.ndarray   # (N,3) world unit normals
    selected: bool  # False when the fallback "all visible" was used
def collect_domain(context) -> Domain | None   # None when no edit-mode mesh has a visible vert
def write_back(domain, P, rows=None) -> None   # world -> each object's space, sets v.co,
                                               # bmesh.update_edit_mesh(loop_triangles=False, destructive=False)
def finish_domain(domain, *, normals=True) -> None   # normal_update + update_edit_mesh, drop bmesh refs
def selection_signature(domain) -> str         # count + bbox rounded to 1e-5; equal for an unchanged selection
def auto_pivot(context, domain) -> np.ndarray  # per settings.basis: LOCAL = bbox centre of domain.P,
                                               # CURSOR / WORLD / NORMAL as the old _set_basis did
def basis_matrix(context, domain) -> np.ndarray  # (3,3) world columns; LOCAL = active object's axes
```

Domain rule: over `context.objects_in_mode_unique_data` (meshes only); selected visible verts of all of them; if that is empty across all objects, all visible verts. `write_back` must leave rows it is not given untouched and must not write a vert whose new position equals its old one bit-for-bit (compare in object space before assigning).

```python
# fields.py — every operator bl_options = {"REGISTER"} (scene data; the spec says field edits are not on the undo stack)
iops.mesh_falloff_field_add      props: type (FALLOFF_TYPES)  — adds, fits to the domain (PCA), makes active, sets last_type
iops.mesh_falloff_field_remove   removes active; active_index clamped
iops.mesh_falloff_field_move     props: direction ("UP"/"DOWN")
iops.mesh_falloff_clear          removes all fields, use_custom_pivot = False
iops.mesh_falloff_fit            see below
iops.mesh_falloff_pivot_reset    use_custom_pivot = False
def fit_active(context, settings, domain, mode) -> None   # writes fc.fit_field result into the active field
def ensure_field(context) -> bool   # empty stack -> add a field of settings.last_type fitted with PCA; False if no domain
```

`iops.mesh_falloff_fit`: `ensure_field` if the stack is empty (mode PCA). Otherwise: if `selection_signature(domain) == settings.fit_signature` advance `fit_mode` cyclically through `FIT_MODES`, else reset it to `PCA`; refit the active field with it; store the signature; clear `use_custom_pivot`. Activating the tool is added in Task 5 — leave a single call site (`_activate_tool(context)`, a no-op function for now). All operators: `poll` = active object is a mesh in Edit Mode; `is_bindable = True` on `mesh_falloff_fit` only.

- [ ] **Step 1: Write `tests/blender/test_falloff_fields.py`** (plain script with asserts, `enable_addon()` copied from `test_draw_handlers.py`, exits non-zero on failure). Fixture: two grid objects of 11×11 = 121 verts each whose local coordinates span exactly [-1, 1] in X and Y at Z = 0 (build with `bmesh.ops.create_grid`, then assert the span and vert count in the fixture itself and rescale if needed), object B at location (3,0,0), rotated 45° about Z, scale (2,1,1); both in multi-object Edit Mode. Checks:
  - `scene.IOPS.falloff` exists; `scene.IOPS` has no attribute `falloff_type`.
  - With nothing selected: `collect_domain` returns `selected is False` and `len(P) == 242`.
  - After selecting all verts of A only: `selected is True`, `len(P) == 121`, `P` equals `mw @ co` for each vert.
  - Hide one selected vert → it is not in the domain.
  - `write_back(domain, domain.P)` changes no `v.co` (compare exact bytes before/after) on both objects.
  - `write_back` with `P + (0,0,1)` moves object-B verts by world +1 Z (check `mw @ co`), within 1e-5.
  - `field_add(type="LINEAR")` on a selection that is 4× longer in X than Y: field start/end differ mainly in X; `active_index == 0`; `stack_to_list` round-trips through `dict_to_field` / `field_to_dict` unchanged.
  - `mesh_falloff_fit` four times with unchanged selection → `fit_mode` goes PCA, X, Y, Z; changing the selection then fitting → PCA.
  - `field_move`, `field_remove`, `clear` keep `active_index` in range; `active_field` returns `None` on an empty stack.
  - An Edit-Mode mesh with zero verts: `collect_domain` → `None`; `mesh_falloff_fit` returns `{'CANCELLED'}` without raising.
- [ ] **Step 2:** Run it headless — expect failure (modules missing).
- [ ] **Step 3:** Implement `props.py`, `domain.py`, `fields.py`; wire `prefs/addon_properties.py` and `__init__.py`. Remove the `FALLOFF_TYPES, SHAPES` import from `addon_properties.py` if it becomes unused. Temporarily remove the three old operators from `__init__.py` imports and `classes` (they are rewritten in Task 3) and delete `operators/falloff/common.py` and the old `ops.py`.
- [ ] **Step 4:** Run the headless test → passes. Run `python -m pytest tests -q` → passes.
- [ ] **Step 5:** Commit `feat(falloff): scene field stack, multi-object domain, fit and stack operators`.

---

### Task 3: Operator base and the four transform operators

**Files:**
- Create: `operators/falloff/base.py`, `operators/falloff/ops.py`
- Modify: `__init__.py` (register the four operators), `tests/smoke_register.py` (add `mesh_falloff_normal_offset`, `mesh_falloff_fit`)
- Test: `tests/blender/test_falloff_ops.py`

**Interfaces — Consumes:** Task 1 core; Task 2 `props`, `domain`, `fields.ensure_field`.

**Produces:**

```python
# base.py
class FalloffOpMixin:
    bl_options = {"REGISTER", "UNDO"};  is_bindable = True
    # operator properties (declare as annotations on the mixin):
    stack: CollectionProperty(type=IOPS_FalloffField, options={"SKIP_SAVE"})
    pivot: FloatVectorProperty(size=3, subtype="TRANSLATION")
    # subclass hooks
    def _apply(self, P0, W, N) -> np.ndarray          # from the operator's own amount props
    def _begin(self, context, event) -> None           # capture drag start
    def _update_amount(self, context, event) -> None   # mouse / axis / numeric -> amount props
    def _amount_text(self) -> str
    def draw_amount(self, layout) -> None              # amount rows of the redo panel
    # provided
    def execute(self, context)      # redo + scripting path
    def invoke(self, context, event)
    def modal(self, context, event)
    def draw(self, context)         # redo panel: draw_amount, pivot, then per field: name, blend,
                                    # strength, curve, invert, enabled
# ops.py
iops.mesh_falloff_move           value: FloatVector(3) world-space delta
iops.mesh_falloff_rotate         angle: Float (ANGLE); axis: FloatVector(3) world unit axis
iops.mesh_falloff_scale          factor: FloatVector(3, default 1); orient: FloatVector(9) world basis columns
iops.mesh_falloff_normal_offset  distance: Float (DISTANCE)
```

Behaviour the tests and spec pin:

- `execute`: `collect_domain` (None → report "no visible vertices", `CANCELLED`). If `len(self.stack) == 0` copy the scene stack into it. If `pivot` was not set by the caller (`not self.properties.is_property_set("pivot")`) use the scene's custom pivot or `auto_pivot`. `W = fc.stack_weights(domain.P, stack_to_list(self.stack))`; `P = self._apply(domain.P, W, domain.N)`; `write_back`; `finish_domain`. Then copy `blend, strength, curve, invert, enabled` of each `self.stack[i]` back onto `scene.IOPS.falloff.fields[i]` when both stacks have the same length. Returns `FINISHED`.
- `invoke`: needs `context.region_data` (else report + `CANCELLED`). `ensure_field` when the scene stack is empty. Snapshot scene stack → `self.stack`; resolve pivot and basis; cache `P0`, `N`, `W`; add the modal handler; notify `draw.op_begin(self)` (Task 5 supplies it — import lazily and tolerate its absence until then with a module-level no-op fallback in `base.py`).
- `modal`, Blender-style: transform starts at once from the invoke mouse position. `MOUSEMOVE` → `_update_amount` → write `self._apply(P0, W, N)`. `X/Y/Z` set / clear the axis (Shift+axis = plane for Move and Scale) in the basis orientation; Rotate defaults to the view axis. Shift = ×0.1 precision, Ctrl = snap (move 0.1, rotate 5°, scale 0.1, normal offset 0.1). Digits / minus / period / backspace = typed amount (`DIGIT_TYPES` from `operators/mesh_shear.py`). `[` / `]` step the **active** field's curve through `SHAPES` (wrapping) and `Shift+I` toggles its invert — on both the scene field and the matching `self.stack` entry — then recompute `W`. `LEFTMOUSE` / `RET` / `NUMPAD_ENTER` → finish, `FINISHED`. `RIGHTMOUSE` / `ESC` → `write_back(P0)`, finish, `CANCELLED`. Middle mouse, wheel, NDOF, trackpad → `PASS_THROUGH`. Wrap the body so a `ReferenceError` finishes cleanly and returns `CANCELLED`.
- Finish always: `draw.op_end(self)`, clear status text, drop every bmesh / numpy reference held on `self`.
- Amount mapping: port from the old `ops.py` (`git show master:operators/falloff/ops.py`), converted to world space. Normal Offset: distance = signed change of mouse distance from the projected pivot × world-units-per-pixel at the pivot.
- Status line while running: `"Falloff <Op> | Axis <axis> | <amount> | <field name> Curve: <curve> — LMB/Enter confirm, Esc cancel"`.

- [ ] **Step 1: Write `tests/blender/test_falloff_ops.py`** using `bpy.ops.iops.<op>("EXEC_DEFAULT", …)`. Fixture as Task 2 (grid A at origin; grid B at (3,0,0), rot Z 45°, scale (2,1,1)). A helper sets one LINEAR field on the scene from world (-1,0,0) to (1,0,0). Checks (tolerance 1e-5 unless stated):
  - **Move ramp:** select all of A; `mesh_falloff_move(value=(0,0,1))` → every vert's world Z equals `(x+1)/2` of its original world X.
  - **No compounding / redo equivalence:** snapshot A's coords; run Move; restore the snapshot coords; run Move again with `value=(0,0,1)` and `stack=[…same field but curve="SHARP"…]` passed explicitly → world Z equals `((x+1)/2)**2`; and running the identical call twice from the same restored snapshot gives identical coords.
  - **Copy-back:** after the `curve="SHARP"` call, `scene.IOPS.falloff.fields[0].curve == "SHARP"`.
  - **Rotate:** `mesh_falloff_rotate(angle=pi/2, axis=(0,0,1), pivot=(0,0,0))` → vert at world (1,0,0) ends at (0,1,0); vert at (-1,0,0) unchanged bit-for-bit; vert at (0,y,0) rotated by 45°.
  - **Scale:** `mesh_falloff_scale(factor=(1,2,1), orient=identity, pivot=(0,0,0))` → world Y of a vert at x=1 doubles; at x=-1 unchanged; at x=0 ×1.5.
  - **Normal offset:** `mesh_falloff_normal_offset(distance=0.5)` → world Z of verts = `0.5*(x+1)/2`.
  - **Multi-object (Review Focus 2):** select all verts of A and B; one LINEAR field from world (-1,0,0) to (5,0,0); Move `(0,0,1)` → for every vert of both objects, world Z == `clamp((wx+1)/6)`; world X and Y unchanged; verts of B whose weight is 0 have bit-identical `co`.
  - **Selection rules (Review Focus 4):** nothing selected → all visible verts of both objects move; a hidden vert never moves; an Edit-Mode object with zero verts as the only object → `{'CANCELLED'}`, no exception.
  - **Empty / disabled stack (Review Focus 5):** scene stack empty and `stack` not passed → `execute` moves every domain vert by the full value (weight 1) and adds no field; all fields `enabled=False` → same; `active_index = 5` with one field → no exception.
  - All four idnames resolve via `get_rna_type()`.
- [ ] **Step 2:** Run headless → fails (operators missing).
- [ ] **Step 3:** Implement `base.py` and `ops.py`; register in `__init__.py`; extend `tests/smoke_register.py`.
- [ ] **Step 4:** Run `tests/blender/test_falloff_ops.py`, `tests/blender/test_falloff_fields.py`, `tests/smoke_register.py` headless and `python -m pytest tests -q` → all pass.
- [ ] **Step 5:** Commit `feat(falloff): Move / Rotate / Scale / Normal Offset read the field stack, redo-able`.

---

### Task 4: Redo-panel and stack edge cases through the operator

Small task kept separate because a reviewer can reject the redo UI independently of the maths.

**Files:**
- Modify: `operators/falloff/base.py`
- Test: extend `tests/blender/test_falloff_ops.py`

**Interfaces — Consumes:** Task 3 `FalloffOpMixin`.

- [ ] **Step 1: Add tests:**
  - `FalloffOpMixin.draw` runs against a stand-in layout (record calls like `test_draw_handlers.py`'s stand-ins) for a stack of 0, 1 and 3 fields without raising, and emits a `prop` call for `blend`, `strength`, `curve`, `invert` per field and none for `start` / `end`.
  - With a 2-field scene stack, calling the operator without `stack` gives coordinates identical to calling it with those same two fields passed explicitly.
  - Scene stack length differs from the operator stack (pass a 1-field `stack` with a 2-field scene) → runs, and copies nothing back (scene fields unchanged).
- [ ] **Step 2:** Run → fails where behaviour is missing.
- [ ] **Step 3:** Fix `base.py` accordingly. In `draw`, show each field in a box titled with its name; disabled fields greyed (`row.active = field.enabled`).
- [ ] **Step 4:** Headless tests pass.
- [ ] **Step 5:** Commit `feat(falloff): redo panel lists participating fields`.

---

### Task 5: Falloff tool — draw handlers, weight preview, gizmo handles, tool settings

**Files:**
- Create: `operators/falloff/draw.py`, `operators/falloff/tool.py`
- Modify: `operators/falloff/fields.py` (`_activate_tool`), `operators/falloff/base.py` (drop the no-op fallback, call `draw.op_begin/op_end`), `__init__.py` (classes; `tool.register()` at the end of `register()`, `tool.unregister()` at the start of `unregister()`, each in try/except like the neighbouring blocks)
- Test: `tests/blender/test_falloff_tool.py`

**Interfaces — Consumes:** Tasks 1–3. `ui/draw` (`primitives.line`, `polyline`, `ring_3d`, `points_colored`, `points_world`, `Role`, `get_theme`, `safe_handler_add`, `safe_handler_remove`), `ui/hud/text` (`isolated`, `draw`).

**Produces:**

```python
# draw.py
TOOL_IDNAME = "iops.falloff_tool"
def install() -> None; def uninstall() -> None     # POST_VIEW + POST_PIXEL handlers via safe_handler_add (tick=False),
                                                   # plus a depsgraph_update_post entry that marks the preview dirty
def op_begin(op) -> None; def op_end(op) -> None   # while an op runs, draw even if another tool is active
def is_visible(context) -> bool                    # Edit Mesh mode and (op running or active tool == TOOL_IDNAME)
def invalidate() -> None
# tool.py
class IOPS_GT_falloff_handle(Gizmo)                # draggable dot
class IOPS_GGT_falloff(GizmoGroup)                 # bl_idname "IOPS_GGT_falloff"
class IOPS_WT_falloff(WorkSpaceTool)               # bl_idname TOOL_IDNAME, bl_label "Falloff"
class IOPS_UL_falloff_fields(UIList); class IOPS_PT_falloff_stack(Panel)   # popover
def register() -> None; def unregister() -> None   # bpy.utils.register_tool(IOPS_WT_falloff, separator=True) + draw.install()
```

Decisions:

- **Visuals are draw handlers, not gizmos** (operators need the same drawing under any tool; text labels need POST_PIXEL). Drawn when `is_visible`: for every field the Start→End line as a gradient from the 0 % colour to the 100 % colour (active field full opacity, others at 35 %), `0%` / `100%` labels at the ends (POST_PIXEL, inside `hud_text.isolated()` so blf state does not leak — see the blf-shadow memory), Radial = three orthogonal rings of the radius, Elliptical = three ellipse outlines from `fc.ellipsoid_frame`, Bidirectional = line with the 100 % colour at the midpoint. Pivot: a `Role.PIVOT` point. Weight preview when `settings.show_weights`: `points_colored` over the domain with `lerp(c0, c100, w)`. Colours: take 0 % / 100 % from two existing theme roles (pick the closest existing pair; do not add theme properties in this project). Occluded parts use the theme's occluded opacity like the other tools (`primitives.edges_world` / `points_world` pattern).
- **Preview cache:** module-level; holds domain positions and weights; recomputed only when dirty (depsgraph update) or when a signature of the scene stack (tuple of every field's values) changes. Never keeps BMesh references between draws.
- **Handles** are `IOPS_GT_falloff_handle` instances created by the group for the **active** field: `START`, `END`, `BODY` (midpoint; moves start and end together); Elliptical adds `RADIUS_1`, `RADIUS_2` (at centre ± frame axis × radius; dragging sets the radius to the distance from the centre along that axis); plus `PIVOT` (always), plus one `SELECT_<i>` at the midpoint of every inactive field (click = make active, no drag). The gizmo: `draw` a screen-facing filled circle (`draw_preset_circle`), `test_select` by pixel distance ≤ 14, `invoke` stores the start value, `modal` moves the point in the view plane through its start position (`view3d_utils.region_2d_to_location_3d`), `exit(cancel=True)` restores. In `modal`: `'SNAP' in tweak` (Ctrl) snaps to the nearest domain vertex within 16 px on screen; `'PRECISE' in tweak` (Shift) ×0.1; key events `X` / `Y` / `Z` toggle a world-axis constraint for the rest of the drag. Dragging `PIVOT` sets `use_custom_pivot = True`. The group rebuilds its gizmos in `refresh` / `draw_prepare` when (field count, active index, active type) changes. Group options `{'3D', 'PERSISTENT'}`; `poll` = Edit Mesh mode.
  - If `X/Y/Z` key events turn out not to reach `Gizmo.modal`, do not build a workaround: leave the constraint code in place, report it in the task hand-back as a concern.
- **Tool:** `bl_space_type "VIEW_3D"`, `bl_context_mode "EDIT_MESH"`, `bl_widget "IOPS_GGT_falloff"`, `bl_icon "ops.transform.vertex_random"`, `bl_keymap`: `G` → `iops.mesh_falloff_move`, `R` → `_rotate`, `S` → `_scale`, `Alt+S` → `_normal_offset`, `Shift+F` → `iops.mesh_falloff_fit` (all `PRESS`). `draw_settings`: popover for `IOPS_PT_falloff_stack`, then the active field's `type, curve, invert, strength, blend`, then `show_weights`, `basis`, Fit, Clear, Reset Pivot. Changing `type` in the UI refits that field to the current domain (property `update` callback calling `fields.fit_active` with mode PCA) and sets `last_type`.
- **Popover panel:** `template_list` over `settings.fields` (row: enabled checkbox, name, type icon/label) with add (menu of the four types) / remove / up / down.
- `fields._activate_tool(context)`: if the 3D view's active tool is not ours, `bpy.ops.wm.tool_set_by_id(name=TOOL_IDNAME, space_type="VIEW_3D")`; swallow `RuntimeError` (no 3D view context, e.g. headless).

- [ ] **Step 1: Write `tests/blender/test_falloff_tool.py`** (headless; no GPU drawing is exercised):
  - After enable: `bpy.types.IOPS_GGT_falloff` exists; the tool is found in `bl_ui.space_toolsystem_toolbar.VIEW3D_PT_tools_active.tools_from_context` for an Edit-Mesh context (or equivalent lookup of `TOOL_IDNAME` in the registered tool list).
  - `draw.install()` twice then `uninstall()` once leaves zero falloff handlers: wrap `draw.safe_handler_add` / `safe_handler_remove` with recorders (pattern in `test_draw_handlers.py`) and assert adds == removes; assert no function from `operators.falloff.draw` remains in `bpy.app.handlers.depsgraph_update_post`.
  - **Review Focus 3:** `addon_disable` → the tool id is gone, `hasattr(bpy.types, "IOPS_GGT_falloff")` is False, no falloff depsgraph handler; `addon_enable` again → all present, exactly one depsgraph handler.
  - Preview cache: call the cache's compute function directly on the Task 2 fixture with one LINEAR field → weights length equals the domain size and match `fc.stack_weights`; after `draw.invalidate()` and a changed field it returns the new weights; the cache object holds no `BMesh` / `BMVert` attribute.
  - `IOPS_FalloffField.type` update: set `type = "RADIAL"` on a fitted field with a selection → `start` equals the selection bbox centre (1e-5), `settings.last_type == "RADIAL"`.
  - `mesh_falloff_fit` headless still returns `{'FINISHED'}` (tool activation failure is swallowed).
- [ ] **Step 2:** Run → fails.
- [ ] **Step 3:** Implement `draw.py`, `tool.py`; wire the rest.
- [ ] **Step 4:** All four headless scripts + `tests/smoke_register.py` + `tests/blender/test_draw_handlers.py` + pytest pass.
- [ ] **Step 5:** Commit `feat(falloff): Falloff toolbar tool with handles, field drawing and weight preview`.

---

### Task 6: Docs, built-in widget, navigation

**Files:**
- Rewrite: `docs/operators/op_mesh_falloff_tools.md`
- Modify: `mkdocs.yml` (nav title → `Falloff Fields`), `presets/widgets/falloff_tools.json`
- Test: `tests/blender/test_falloff_tool.py` (one added check)

- [ ] **Step 1: Add a test:** load `presets/widgets/falloff_tools.json`; every `"op"` value resolves via `bpy.ops` `get_rna_type()`; every `"prop"` path beginning `scene.IOPS.` resolves with `bpy.context.scene.path_resolve(<path minus "scene.">)`.
- [ ] **Step 2:** Run → fails (old props).
- [ ] **Step 3:** Rewrite the widget: buttons Fit, Clear, Move, Rotate, Scale, Normal Offset (Edit Mesh only, as today); `DROPDOWN` for `scene.IOPS.falloff.basis`; `FLIPBOX` for `scene.IOPS.falloff.show_weights`. No per-field rows (widget paths cannot index the active field). Rewrite the docs page in the style of its neighbours (`op_mesh_inset.md`): what a field is, the four types, the stack and blend modes, the tool and its handles, Fit cycling, the four operators and their in-operation keys, F9, multi-object, what was removed (Screen, Coplanar, Element, in-modal editing), that field edits are not undoable, and that a user-override copy of the Falloff Tools widget must be updated to the new property paths.
- [ ] **Step 4:** Headless test passes; `python -m mkdocs build --strict` if mkdocs is installed (skip and say so if not).
- [ ] **Step 5:** Commit `docs(falloff): falloff fields page, built-in widget on the new properties`.

---

### Task 7: Reference loop (≥ 80 % per scenario) and squash

This task is run by the controller, not handed to a single implementer: it alternates a capture agent, a scoring reviewer that did not write the code, and fix agents.

**Files:**
- Create (outside the repo, never committed): `B:\test\falloff_reference\iops\` captures, `B:\test\falloff_reference\stage_falloff.py`, `B:\test\falloff_fields.blend`
- Modify: whatever the fixes require.

**Capture method:** launch a *separate, windowed* Blender (`blender.exe B:\test\falloff_fields.blend --python B:\test\falloff_reference\stage_falloff.py -- <scenario>`; add `--enable-event-simulate` when a scenario needs key / mouse events). The script builds the scenario mesh and selection, sets the fields, activates the Falloff tool, frames the view like the reference, then from a `bpy.app.timers` callback saves `bpy.ops.screen.screenshot_area` PNGs of the 3D view to `iops\<scenario>_<moment>.png` and quits. "After confirm" states are produced with `EXEC_DEFAULT` operator calls; mid-operation and F9-panel states with `window.event_simulate` where feasible. The script must assert `bpy.data.filepath` is `B:\test\falloff_fields.blend` before doing anything.

**Scoring:** per the spec's "Reference loop": a fresh reviewer agent reads `B:\test\falloff_reference\sheets\<NN>.jpg` (and `c_f9_move.png` for the F9 scenario) next to the iOps captures and scores every `;`-separated "must match" item of that scenario's table row 1 / 0.5 / 0. Pass = ≥ 80 % and no 0. Theme colours, HUD style and wording are not scored down. An item that could not be staged automatically (for example a live handle drag) is marked **unverified**: it is excluded from the percentage, listed in the final report, and added to the user's live checklist — it is never silently counted as a pass.

- [ ] **Step 1:** Write `stage_falloff.py` with the ten scenarios of the spec table (`06_linear`, `01_transforms`, `11_topo` rotate part, `07_radial`, `08_elliptical`, `09_bidir`, `13_stack`, `14_multiobj`, `15_placement`, `16_visual`). Create `B:\test\falloff_fields.blend` as an empty saved file.
- [ ] **Step 2:** Capture all scenarios. Confirm every expected PNG exists and is not blank.
- [ ] **Step 3:** Score all scenarios with a fresh reviewer. Record a table: scenario, item, score, note.
- [ ] **Step 4:** For each failing scenario: fix (fresh implementer with the reviewer's notes and both images), re-run the headless tests, re-capture, re-score. At most three rounds per scenario; after the third failure stop and report to the user with the scores.
- [ ] **Step 5:** During the first live capture also check the two spec items that need a real UI: scene properties written from a redo `execute()` survive the redo's undo (copy-back), and `X/Y/Z` reach `Gizmo.modal`. If copy-back is rolled back, remove it from `base.py` and its test; record either outcome.
- [ ] **Step 6:** Run the complete suite once more (pytest + all headless scripts).
- [ ] **Step 7: Squash.** `git reset --soft master` then one commit containing only this feature's files (verify `git status --short` shows `operators/save_load_space_data.py` still as an unstaged modification and nothing from `B:\test`): `feat(falloff): falloff fields — stackable scene fields, Falloff tool, redo-able Move / Rotate / Scale / Normal Offset`, with the attribution trailers.
- [ ] **Step 8:** Report to the user: per-scenario scores, unverified items, the live checklist from the spec's "Verification" section, and where the captures are. Do not merge to master without being asked.
