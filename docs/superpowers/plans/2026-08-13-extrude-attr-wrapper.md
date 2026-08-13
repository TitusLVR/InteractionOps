# Extrude Wrapper with Edge-Attribute Continuation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drop-in `E` replacement (`iops.mesh_extrude_ex`) that extrudes like native Blender but propagates sharp / bevel-weight / crease onto the new rail edges.

**Architecture:** Three operators in one new file: an instant fixup operator (`iops.extrude_attr_fix`, topology-based bmesh pass), a `bpy.types.Macro` chaining `MESH_OT_extrude_region → IOPS_OT_extrude_attr_fix → TRANSFORM_OT_translate` (exactly how native `extrude_region_move` is built — one undo step, native modal feel), and a thin dispatcher that invokes the macro with normal-constrained translate for face selections, free translate otherwise.

**Tech Stack:** Blender 5.1 Python API (`bpy`, `bmesh`), iops addon registration in `__init__.py`, iops hotkey system (`prefs/hotkeys_default.py`).

**Spec:** `docs/superpowers/specs/2026-08-13-extrude-attr-wrapper-design.md`

## Global Constraints

- Propagated attributes: `edge.smooth` (sharp), float layers `bevel_weight_edge`, `crease_edge`. NEVER seams or freestyle marks.
- Never create attribute layers — propagate only through layers that already exist (a nonzero source value implies its layer exists).
- The fixup must be topology-only (no geometry/positions) so it runs between extrude and translate.
- Do NOT touch `operators/iops.py` — it has unrelated uncommitted changes. `git add` only the files each task names.
- Public repo: never mention CCP or internal projects in commit messages.

## Environment / Test Harness Notes (read before any task)

- The live Blender instance has `V:\temp_blends\extrude_wrapper.blend` open. Objects: `start` (plane at (0,-2.41,0), right edge at x=1 marked sharp + bevel_weight 1 + crease 1), `target` (desired semantics), `finish` (what a plain scripted extrude gives). There may be a scratch object `native_test` from design phase — delete it if present.
- Run test code in Blender via the MCP tool `mcp__blender__execute_blender_code`. Assign a JSON-serializable dict to `result`.
- Each test iteration creates a collection `v1`, `v2`, `v3`, … holding its test objects (user tracks iterations visually). Never delete previous `vN` collections.
- Addon lives at `B:\scripts\addons\InteractionOps` → symlink to this repo. To reload the addon after editing code, send a line to the "blinker" on TCP 9902:

  Use the Bash tool (quoting is simpler than PowerShell):

  ```bash
  python -c "import socket; s=socket.create_connection(('localhost',9902),timeout=5); s.sendall(b'reload\n'); s.close()"
  ```
- Registration check gotcha: `bpy.types` stores operators under the bl_idname-derived name (`IOPS_OT_mesh_extrude_ex`), not the Python class name. Verify with `hasattr(bpy.ops.iops, "mesh_extrude_ex")` / `bpy.ops.iops.mesh_extrude_ex.get_rna_type()`.
- Blender MCP runs ops fine without window overrides for `mesh.*`/`transform.*` in exec mode (verified during design: `bpy.ops.mesh.extrude_region_move(TRANSFORM_OT_translate={"value": (0.9,0,0)})` worked).

---

### Task 1: Fixup operator (`iops.extrude_attr_fix`) + registration

**Files:**
- Create: `D:\git\InteractionOps\operators\mesh_extrude_attrs.py`
- Modify: `D:\git\InteractionOps\__init__.py` (import near line 252 block, classes tuple near line 524 block)
- Test: MCP script (below), results land in collection `v1` of the open blend

**Interfaces:**
- Produces: operator `iops.extrude_attr_fix` (no props); module function `fix_extruded_attrs(bm) -> int` (returns number of rail edges modified); classes `IOPS_OT_extrude_attr_fix` exported for `__init__.py`.

- [ ] **Step 1: Run the failing test** — paste this into `mcp__blender__execute_blender_code`. Expected: `{"status": "FAIL", "reason": "operator missing"}` because `iops.extrude_attr_fix` does not exist yet.

```python
import bpy, bmesh

def ensure_coll(name):
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
    if coll.name not in {c.name for c in bpy.context.scene.collection.children}:
        bpy.context.scene.collection.children.link(coll)
    return coll

def dup_start(coll, new_name, dx=0.0, dy=0.0):
    src = bpy.data.objects["start"]
    obj = bpy.data.objects.new(new_name, src.data.copy())
    obj.location = (src.location.x + dx, src.location.y + dy, src.location.z)
    coll.objects.link(obj)
    return obj

def edge_by_coords(bm, a, b, tol=1e-3):
    from mathutils import Vector
    a, b = Vector(a), Vector(b)
    for e in bm.edges:
        c0, c1 = e.verts[0].co, e.verts[1].co
        if ((c0-a).length < tol and (c1-b).length < tol) or ((c0-b).length < tol and (c1-a).length < tol):
            return e
    return None

def edge_data(e, bw, cr):
    return {"sharp": not e.smooth, "bw": round(e[bw], 3) if bw else 0.0,
            "cr": round(e[cr], 3) if cr else 0.0}

result = {"status": "?"}
if not hasattr(bpy.ops.iops, "extrude_attr_fix"):
    result = {"status": "FAIL", "reason": "operator missing"}
else:
    scratch = bpy.data.objects.get("native_test")
    if scratch:
        bpy.data.objects.remove(scratch)
    coll = ensure_coll("v1")
    obj = dup_start(coll, "v1_edge_extrude", dx=4.5)
    for o in bpy.context.view_layer.objects: o.select_set(False)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    me = obj.data
    bm = bmesh.from_edit_mesh(me)
    bm.edges.ensure_lookup_table()
    for v in bm.verts: v.select_set(False)
    for e in bm.edges: e.select_set(False)
    marked = bm.edges[2]  # x=1 vertical edge, sharp/bw1/cr1
    marked.select_set(True)
    for v in marked.verts: v.select_set(True)
    bmesh.update_edit_mesh(me)
    bpy.ops.mesh.extrude_region()          # geometry appears at zero offset
    bpy.ops.iops.extrude_attr_fix()        # <- unit under test (pre-translate!)
    bpy.ops.transform.translate(value=(0.9, 0, 0))
    bpy.ops.object.mode_set(mode='OBJECT')
    bm = bmesh.new(); bm.from_mesh(me)
    bw = bm.edges.layers.float.get("bevel_weight_edge")
    cr = bm.edges.layers.float.get("crease_edge")
    checks = {
        "rail_top":    edge_data(edge_by_coords(bm, (1, 1, 0), (1.9, 1, 0)), bw, cr),
        "rail_bottom": edge_data(edge_by_coords(bm, (1, -1, 0), (1.9, -1, 0)), bw, cr),
        "new_edge":    edge_data(edge_by_coords(bm, (1.9, -1, 0), (1.9, 1, 0)), bw, cr),
        "orig_edge":   edge_data(edge_by_coords(bm, (1, -1, 0), (1, 1, 0)), bw, cr),
        "clean_edge":  edge_data(edge_by_coords(bm, (-1, -1, 0), (-1, 1, 0)), bw, cr),
    }
    bm.free()
    want_marked = {"sharp": True, "bw": 1.0, "cr": 1.0}
    ok = (checks["rail_top"] == want_marked and checks["rail_bottom"] == want_marked
          and checks["new_edge"] == want_marked and checks["orig_edge"] == want_marked
          and checks["clean_edge"] == {"sharp": False, "bw": 0.0, "cr": 0.0})
    result = {"status": "PASS" if ok else "FAIL", "checks": checks}
```

- [ ] **Step 2: Create `operators/mesh_extrude_attrs.py`** with exactly:

```python
import bpy
import bmesh


def fix_extruded_attrs(bm):
    """Propagate sharp / bevel weight / crease from extruded source edges
    onto the rail edges created by MESH_OT_extrude_region.

    Must run AFTER extrude_region and BEFORE any translation: it is purely
    topology-based. At that point new geometry is selected and original
    vertices are deselected.

    A rail edge has exactly one selected (new) vertex. Its sources are the
    edges of its linked faces (the new side quads) whose vertices are both
    unselected and include the rail's old vertex — i.e. the original
    extruded edges left behind. Per attribute: OR for sharp, max for
    bevel weight / crease. Layers are never created; values propagate only
    through layers that already exist.

    Returns the number of rail edges that received data.
    """
    bw = bm.edges.layers.float.get("bevel_weight_edge")
    cr = bm.edges.layers.float.get("crease_edge")
    changed = 0
    for rail in bm.edges:
        v0, v1 = rail.verts
        if v0.select == v1.select:
            continue
        old_v = v1 if v0.select else v0
        sharp = False
        weight = 0.0
        crease = 0.0
        for face in rail.link_faces:
            for edge in face.edges:
                if edge is rail:
                    continue
                if edge.verts[0].select or edge.verts[1].select:
                    continue
                if old_v not in edge.verts:
                    continue
                sharp = sharp or not edge.smooth
                if bw is not None:
                    weight = max(weight, edge[bw])
                if cr is not None:
                    crease = max(crease, edge[cr])
        if not (sharp or weight > 0.0 or crease > 0.0):
            continue
        if sharp:
            rail.smooth = False
        if weight > 0.0:
            rail[bw] = weight
        if crease > 0.0:
            rail[cr] = crease
        changed += 1
    return changed


class IOPS_OT_extrude_attr_fix(bpy.types.Operator):
    """Copy sharp/bevel weight/crease onto freshly extruded rail edges"""
    bl_idname = "iops.extrude_attr_fix"
    bl_label = "Extrude Attribute Fix"
    bl_options = {"REGISTER", "INTERNAL"}

    @classmethod
    def poll(cls, context):
        return context.mode == "EDIT_MESH"

    def execute(self, context):
        me = context.active_object.data
        bm = bmesh.from_edit_mesh(me)
        if fix_extruded_attrs(bm):
            bmesh.update_edit_mesh(me)
        return {"FINISHED"}
```

- [ ] **Step 3: Register in `__init__.py`.** In the import block (right after the `from .operators.mesh_shear import IOPS_OT_mesh_shear` line, ~line 253) add:

```python
from .operators.mesh_extrude_attrs import IOPS_OT_extrude_attr_fix
```

In the `classes` tuple (right after the `IOPS_OT_mesh_shear,` entry, ~line 525) add:

```python
    IOPS_OT_extrude_attr_fix,
```

- [ ] **Step 4: Reload addon via blinker** (Bash tool):

```bash
python -c "import socket; s=socket.create_connection(('localhost',9902),timeout=5); s.sendall(b'reload\n'); s.close()"
```

Then verify registration via MCP: `result = {"registered": hasattr(bpy.ops.iops, "extrude_attr_fix")}` — expect `true`. If reload fails (connection refused), report it and stop; do not fall back to `addon_utils` disable/enable.

- [ ] **Step 5: Re-run the Step 1 test** — expect `{"status": "PASS", ...}` with all four marked edges `{"sharp": true, "bw": 1.0, "cr": 1.0}` and `clean_edge` untouched. The `v1` collection stays in the blend for the user.

- [ ] **Step 6: Commit**

```bash
git add operators/mesh_extrude_attrs.py __init__.py
git commit -m "feat(mesh): extrude attr-fix op propagates sharp/bevel/crease to rails

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Macro + dispatcher (`iops.mesh_extrude_ex`) + hotkey slot

**Files:**
- Modify: `D:\git\InteractionOps\operators\mesh_extrude_attrs.py` (append)
- Modify: `D:\git\InteractionOps\__init__.py` (imports, classes tuple, `register()`)
- Modify: `D:\git\InteractionOps\prefs\hotkeys_default.py` (one line in the `# IOPS Operators Mesh` block)
- Test: MCP script (below), results in collection `v2`

**Interfaces:**
- Consumes: `IOPS_OT_extrude_attr_fix` from Task 1 (macro step references its C-style name `IOPS_OT_extrude_attr_fix`).
- Produces: `iops.mesh_extrude_ex` (dispatcher, the user-facing op), `iops.mesh_extrude_ex_macro` (macro), module function `define_extrude_macro()` that `register()` must call after class registration.

- [ ] **Step 1: Run the failing test** via `mcp__blender__execute_blender_code`. Reuse the helper functions from Task 1 Step 1 verbatim (`ensure_coll`, `dup_start`, `edge_by_coords`, `edge_data`, and the same `want_marked` comparison). Differences: collection `v2`, object `v2_edge_extrude` at `dx=9.0`, and instead of the three ops calls (`extrude_region` / `extrude_attr_fix` / `translate`) do the single macro exec call:

```python
    bpy.ops.iops.mesh_extrude_ex_macro(TRANSFORM_OT_translate={"value": (0.9, 0, 0)})
```

Gate at the top on `hasattr(bpy.ops.iops, "mesh_extrude_ex_macro")` → expect `{"status": "FAIL", "reason": "operator missing"}` now.

- [ ] **Step 2: Append macro + dispatcher to `operators/mesh_extrude_attrs.py`:**

```python
class IOPS_OT_mesh_extrude_ex_macro(bpy.types.Macro):
    """Extrude region, fix edge attributes, then move (native-style macro)"""
    bl_idname = "iops.mesh_extrude_ex_macro"
    bl_label = "Extrude Region and Move (Keep Edge Data)"
    bl_options = {"REGISTER", "UNDO"}


def define_extrude_macro():
    """Populate the macro steps. Must be called once per registration,
    AFTER register_classes has run (Macro.define only works on a
    registered macro type)."""
    macro = IOPS_OT_mesh_extrude_ex_macro
    macro.define("MESH_OT_extrude_region")
    macro.define("IOPS_OT_extrude_attr_fix")
    macro.define("TRANSFORM_OT_translate")


class IOPS_OT_mesh_extrude_ex(bpy.types.Operator):
    """Extrude and move, continuing sharp/bevel weight/crease onto the
    new side edges. Face selections translate along the region normal,
    like native E."""
    bl_idname = "iops.mesh_extrude_ex"
    bl_label = "Extrude (Keep Edge Data)"
    # No UNDO here: the macro pushes the single undo step.
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return context.mode == "EDIT_MESH"

    def invoke(self, context, event):
        me = context.active_object.data
        bm = bmesh.from_edit_mesh(me)
        face_mode = context.tool_settings.mesh_select_mode[2]
        use_normal = face_mode and any(f.select for f in bm.faces)
        if use_normal:
            bpy.ops.iops.mesh_extrude_ex_macro(
                "INVOKE_DEFAULT",
                TRANSFORM_OT_translate={
                    "orient_type": "NORMAL",
                    "constraint_axis": (False, False, True),
                },
            )
        else:
            bpy.ops.iops.mesh_extrude_ex_macro("INVOKE_DEFAULT")
        return {"FINISHED"}
```

- [ ] **Step 3: Wire up in `__init__.py`.** Extend the Task 1 import line to:

```python
from .operators.mesh_extrude_attrs import (IOPS_OT_extrude_attr_fix,
                                           IOPS_OT_mesh_extrude_ex_macro,
                                           IOPS_OT_mesh_extrude_ex,
                                           define_extrude_macro)
```

Add to the `classes` tuple after `IOPS_OT_extrude_attr_fix,`:

```python
    IOPS_OT_mesh_extrude_ex_macro,
    IOPS_OT_mesh_extrude_ex,
```

In `register()` (~line 604), immediately after the `reg_cls()` call, add:

```python
    define_extrude_macro()
```

(Confirm the exact name of the classes-registration call at that spot — it is the factory function from `register_classes_factory`, named `reg_cls`. `unregister()` needs no change: `unregister_class` drops the macro and its defines together.)

- [ ] **Step 4: Hotkey slot.** In `prefs/hotkeys_default.py`, `# IOPS Operators Mesh` block, add (F19 = unbound placeholder, consistent with neighbors — do NOT bind E by default):

```python
    ("iops.mesh_extrude_ex", "F19", "PRESS", False, False, False, False),
```

- [ ] **Step 5: Reload via blinker (same command as Task 1 Step 4), verify** `hasattr(bpy.ops.iops, "mesh_extrude_ex")` and `hasattr(bpy.ops.iops, "mesh_extrude_ex_macro")` both true. The functional test in Step 6 is the real gate for whether the macro steps chained correctly.

- [ ] **Step 6: Re-run Step 1 test** — expect PASS with identical checks to Task 1 (rails, new edge, original all `sharp/bw1/cr1`; clean edge clean) in collection `v2`.

- [ ] **Step 7: Commit**

```bash
git add operators/mesh_extrude_attrs.py __init__.py prefs/hotkeys_default.py
git commit -m "feat(mesh): iops.mesh_extrude_ex macro - extrude keeping edge data

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Edge-case matrix (face / corner / vertex / clean mesh)

**Files:**
- Test only: MCP script below, results in collection `v3`. Fix bugs in `operators/mesh_extrude_attrs.py` if any case fails (reload + rerun after each fix).

**Interfaces:**
- Consumes: `iops.mesh_extrude_ex_macro` exec-mode call from Task 2.

- [ ] **Step 1: Run the matrix test.** One MCP call; builds four objects in `v3` from scratch (independent of `start`). For each case: build mesh in a bmesh, write to a new object in `v3`, enter edit mode, set selection, run `bpy.ops.iops.mesh_extrude_ex_macro(TRANSFORM_OT_translate={"value": v})`, return to object mode, assert.

```python
import bpy, bmesh
from mathutils import Vector

def ensure_coll(name):
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
    if coll.name not in {c.name for c in bpy.context.scene.collection.children}:
        bpy.context.scene.collection.children.link(coll)
    return coll

def new_obj(coll, name, loc):
    me = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, me)
    obj.location = loc
    coll.objects.link(obj)
    return obj

def make_plane(me, mark_edges, mark=("sharp", "bw", "cr")):
    """Unit 2x2 plane; mark_edges = list of (v_index_a, v_index_b) pairs to mark."""
    bm = bmesh.new()
    vs = [bm.verts.new(co) for co in ((-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0))]
    bm.faces.new(vs)
    bw = bm.edges.layers.float.new("bevel_weight_edge") if "bw" in mark else None
    cr = bm.edges.layers.float.new("crease_edge") if "cr" in mark else None
    bm.verts.index_update()
    for e in bm.edges:
        key = {e.verts[0].index, e.verts[1].index}
        if key in [set(p) for p in mark_edges]:
            if "sharp" in mark:
                e.smooth = False
            if bw is not None:
                e[bw] = 1.0
            if cr is not None:
                e[cr] = 1.0
    bm.to_mesh(me)
    bm.free()

def activate(obj):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

def select_only(me, verts=(), edges=(), faces=(), mode='EDGE'):
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_mode(type=mode)
    bm = bmesh.from_edit_mesh(me)
    bm.verts.ensure_lookup_table(); bm.edges.ensure_lookup_table(); bm.faces.ensure_lookup_table()
    for v in bm.verts: v.select_set(False)
    for e in bm.edges: e.select_set(False)
    for f in bm.faces: f.select_set(False)
    for i in faces:
        bm.faces[i].select_set(True)
    for i in edges:
        bm.edges[i].select_set(True)
        for v in bm.edges[i].verts: v.select_set(True)
    for i in verts:
        bm.verts[i].select_set(True)
    bmesh.update_edit_mesh(me)

def snapshot(me):
    bm = bmesh.new(); bm.from_mesh(me)
    bw = bm.edges.layers.float.get("bevel_weight_edge")
    cr = bm.edges.layers.float.get("crease_edge")
    out = []
    for e in bm.edges:
        out.append({"a": tuple(round(c, 2) for c in e.verts[0].co),
                    "b": tuple(round(c, 2) for c in e.verts[1].co),
                    "sharp": not e.smooth,
                    "bw": round(e[bw], 2) if bw else 0.0,
                    "cr": round(e[cr], 2) if cr else 0.0})
    bm.free()
    return out

def find(snap, a, b):
    a, b = tuple(a), tuple(b)
    for e in snap:
        if (e["a"] == a and e["b"] == b) or (e["a"] == b and e["b"] == a):
            return e
    return None

def marked(e):
    return e is not None and e["sharp"] and e["bw"] == 1.0 and e["cr"] == 1.0

def clean(e):
    return e is not None and not e["sharp"] and e["bw"] == 0.0 and e["cr"] == 0.0

coll = ensure_coll("v3")
report = {}

# Case A: face extrude, ONE marked boundary edge (v1-v2, the x=1 edge).
# Extrude face +Z: rails at (1,-1) and (1,1) marked; other two rails clean;
# top edge above the marked edge inherits natively (marked); other top edges clean.
obj = new_obj(coll, "v3_face_one_marked", (14, -2.41, 0))
make_plane(obj.data, [(1, 2)])
activate(obj)
select_only(obj.data, faces=[0], mode='FACE')
bpy.ops.iops.mesh_extrude_ex_macro(TRANSFORM_OT_translate={"value": (0, 0, 1)})
bpy.ops.object.mode_set(mode='OBJECT')
s = snapshot(obj.data)
report["A_face_one_marked"] = {
    "rail_marked_1": marked(find(s, (1, -1, 0), (1, -1, 1))),
    "rail_marked_2": marked(find(s, (1, 1, 0), (1, 1, 1))),
    "rail_clean_1": clean(find(s, (-1, -1, 0), (-1, -1, 1))),
    "rail_clean_2": clean(find(s, (-1, 1, 0), (-1, 1, 1))),
    "top_marked": marked(find(s, (1, -1, 1), (1, 1, 1))),
    "top_clean": clean(find(s, (-1, -1, 1), (-1, 1, 1))),
}

# Case B: two marked edges meeting at a corner, both extruded (edge mode).
# Mark v1-v2 (x=1) and v2-v3 (y=1); select both, extrude +Z.
# Corner rail at (1,1,0)-(1,1,1) gets max of both; end rails also marked.
obj = new_obj(coll, "v3_corner_two_marked", (18, -2.41, 0))
make_plane(obj.data, [(1, 2), (2, 3)])
activate(obj)
bpy.ops.object.mode_set(mode='EDIT')
bm = bmesh.from_edit_mesh(obj.data)
bm.edges.ensure_lookup_table()
sel = [e.index for e in bm.edges
       if {tuple(round(c, 2) for c in e.verts[0].co), tuple(round(c, 2) for c in e.verts[1].co)}
       in ({(1.0, -1.0, 0.0), (1.0, 1.0, 0.0)}, {(1.0, 1.0, 0.0), (-1.0, 1.0, 0.0)})]
bpy.ops.object.mode_set(mode='OBJECT')
activate(obj)
select_only(obj.data, edges=sel, mode='EDGE')
bpy.ops.iops.mesh_extrude_ex_macro(TRANSFORM_OT_translate={"value": (0, 0, 1)})
bpy.ops.object.mode_set(mode='OBJECT')
s = snapshot(obj.data)
report["B_corner"] = {
    "corner_rail_marked": marked(find(s, (1, 1, 0), (1, 1, 1))),
    "end_rail_1_marked": marked(find(s, (1, -1, 0), (1, -1, 1))),
    "end_rail_2_marked": marked(find(s, (-1, 1, 0), (-1, 1, 1))),
}

# Case C: vertex extrude — no faces, no marks; must not error, new edge clean.
obj = new_obj(coll, "v3_vertex", (22, -2.41, 0))
make_plane(obj.data, [])
activate(obj)
select_only(obj.data, verts=[2], mode='VERT')
bpy.ops.iops.mesh_extrude_ex_macro(TRANSFORM_OT_translate={"value": (0.5, 0.5, 0)})
bpy.ops.object.mode_set(mode='OBJECT')
s = snapshot(obj.data)
report["C_vertex"] = {"new_edge_clean": clean(find(s, (1, 1, 0), (1.5, 1.5, 0)))}

# Case D: mesh with NO bevel/crease layers, sharp-only mark. Rails get sharp;
# no bevel_weight_edge / crease_edge layers may appear.
obj = new_obj(coll, "v3_no_layers", (26, -2.41, 0))
make_plane(obj.data, [(1, 2)], mark=("sharp",))
activate(obj)
bpy.ops.object.mode_set(mode='EDIT')
bm = bmesh.from_edit_mesh(obj.data)
bm.edges.ensure_lookup_table()
sel = [e.index for e in bm.edges if not e.smooth]
bpy.ops.object.mode_set(mode='OBJECT')
activate(obj)
select_only(obj.data, edges=sel, mode='EDGE')
bpy.ops.iops.mesh_extrude_ex_macro(TRANSFORM_OT_translate={"value": (0.9, 0, 0)})
bpy.ops.object.mode_set(mode='OBJECT')
s = snapshot(obj.data)
rail1 = find(s, (1, 1, 0), (1.9, 1, 0))
rail2 = find(s, (1, -1, 0), (1.9, -1, 0))
report["D_no_layers"] = {
    "rails_sharp": bool(rail1 and rail2 and rail1["sharp"] and rail2["sharp"]),
    "no_bw_layer": "bevel_weight_edge" not in obj.data.attributes,
    "no_cr_layer": "crease_edge" not in obj.data.attributes,
}

flat = {}
for case, checks in report.items():
    for k, v in checks.items():
        flat[f"{case}.{k}"] = v
result = {"status": "PASS" if all(flat.values()) else "FAIL", "checks": flat}
```

Expected: `{"status": "PASS"}` with every check true. Case A's `top_marked` relies on native duplicated-edge copying — if it fails, that is a NATIVE gap, not a rail bug; report it rather than patching blindly.

- [ ] **Step 2: If any check fails** — diagnose with superpowers:systematic-debugging, fix `fix_extruded_attrs()` in `operators/mesh_extrude_attrs.py`, reload via blinker, rerun. Repeat until PASS. Each rerun may reuse collection `v3` (delete only the failing case's object, keep the collection).

- [ ] **Step 3: Commit (only if code changed in Step 2)**

```bash
git add operators/mesh_extrude_attrs.py
git commit -m "fix(mesh): extrude attr fix edge cases

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Docs page

**Files:**
- Create: `D:\git\InteractionOps\docs\operators\op_mesh_extrude_ex.md`
- Reference for style: `D:\git\InteractionOps\docs\operators\op_mesh_shear.md` (read it first, mirror its front-matter/heading conventions exactly)

**Interfaces:**
- Consumes: operator names from Task 2.

- [ ] **Step 1: Read `docs/operators/op_mesh_shear.md`**, then write `op_mesh_extrude_ex.md` in the same format covering: what it does (extrude + continue sharp/bevel weight/crease onto rail edges), how it differs from native E, the three operators (`iops.mesh_extrude_ex` is the one to bind; the macro and fix op are internal), hotkey unbound by default (bind over `E` in iops hotkey prefs), and the propagation rule (marked extruded edges at each vertex; max/OR at corners; seams and freestyle never propagate). Check whether the docs have a nav index (`docs/operators.md` or `mkdocs.yml` in repo root) listing operator pages — if yes, add the new page entry in the same style.

- [ ] **Step 2: Commit**

```bash
git add docs/operators/op_mesh_extrude_ex.md
git commit -m "docs: iops.mesh_extrude_ex operator page

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

(If a nav index was modified in Step 1, `git add` that file too.)

---

## Post-plan notes for the executor

- User is AFK; do not block on questions. If something is genuinely ambiguous, choose the option closest to native extrude behavior and note it in the final report.
- Manual modal-feel verification (mouse-follow, Esc cancel leaving zero-offset geometry with fixed attrs) cannot be automated — leave `v1`–`v3` collections in the blend and flag modal testing as the one remaining manual step for the user.
- Do not save the .blend file — the user decides what to keep.

---

### Task 5: Rule B — continuation propagation from non-extruded edges (post-translate)

Added after user testing surfaced the second half of the original complaint: extruding an
UNMARKED rim whose corner verts terminate marked edges must propagate those marks onto the
new rails (they geometrically continue the marked edges). Reference: objects
`open_box_start` / `open_box_start_target` (want) / `open_box_start_finish` (current) in the
open blend. Spec updated: Rule B in the Behavior section.

**Files:**
- Modify: `D:\git\InteractionOps\operators\mesh_extrude_attrs.py`
- Modify: `D:\git\InteractionOps\__init__.py` (extend import + classes tuple)
- Modify: `D:\git\InteractionOps\docs\operators\op_mesh_extrude_ex.md` (rules A+B, 4 macro steps, cancel note)
- Test: MCP scripts, collection `v5`

**Interfaces:**
- Produces: `fix_extruded_attrs_post(bm) -> int`, `IOPS_OT_extrude_attr_fix_post`
  (bl_idname `iops.extrude_attr_fix_post`), module constant `CONTINUATION_ANGLE`
  (radians(45)). Macro chain becomes: extrude_region → fix → translate → fix_post.

**Algorithm (Rule B, runs AFTER translate so rail directions exist):**

```python
CONTINUATION_ANGLE = math.radians(45.0)

def fix_extruded_attrs_post(bm):
    """Rule B: rails inherit marks from pre-existing non-extruded edges they
    geometrically continue (direction into old vert within CONTINUATION_ANGLE
    of the rail's direction out of it). Runs after the translate; on a
    cancelled translate rails are zero-length and this is a no-op."""
    bw = bm.edges.layers.float.get("bevel_weight_edge")
    cr = bm.edges.layers.float.get("crease_edge")
    cos_limit = math.cos(CONTINUATION_ANGLE)
    changed = 0
    for rail in bm.edges:
        v0, v1 = rail.verts
        if v0.select == v1.select:
            continue
        new_v, old_v = (v0, v1) if v0.select else (v1, v0)
        rail_dir = new_v.co - old_v.co
        if rail_dir.length_squared < 1e-12:
            continue
        rail_dir.normalize()
        # Seed from the rail's CURRENT values so Rule B can only raise what
        # Rule A (or native duplication) already set, never downgrade it.
        sharp = not rail.smooth
        weight = rail[bw] if bw is not None else 0.0
        crease = rail[cr] if cr is not None else 0.0
        for edge in old_v.link_edges:
            if edge is rail:
                continue
            other = edge.other_vert(old_v)
            if other.select:      # new geometry (other rails / duplicates)
                continue
            marked = (not edge.smooth
                      or (bw is not None and edge[bw] > 0.0)
                      or (cr is not None and edge[cr] > 0.0))
            if not marked:
                continue
            edge_dir = old_v.co - other.co   # direction INTO old_v
            if edge_dir.length_squared < 1e-12:
                continue
            edge_dir.normalize()
            if edge_dir.dot(rail_dir) < cos_limit:
                continue
            sharp = sharp or not edge.smooth
            if bw is not None:
                weight = max(weight, edge[bw])
            if cr is not None:
                crease = max(crease, edge[cr])
        if not (sharp or weight > 0.0 or crease > 0.0):
            continue
        if sharp:
            rail.smooth = False
        if weight > 0.0:
            rail[bw] = weight
        if crease > 0.0:
            rail[cr] = crease
        changed += 1
    return changed
```

`IOPS_OT_extrude_attr_fix_post` mirrors `IOPS_OT_extrude_attr_fix` exactly (poll,
multi-object `context.objects_in_mode_unique_data` loop — extract a shared helper for the
loop if that keeps it DRY), calling `fix_extruded_attrs_post`. `define_extrude_macro()`
gains a fourth define AFTER `TRANSFORM_OT_translate`. Macro post-modal continuation is
proven by native `MESH_OT_loopcut_slide` (two chained modal ops); exec-mode tests exercise
the chain directly.

- [ ] **Step 1: failing test (v5, MCP).** Duplicate `open_box_start` into collection `v5`
  (dx=4.5), select its 4 open-rim boundary edges (`len(e.link_faces) == 1`) + their verts in
  edit mode, run `bpy.ops.iops.mesh_extrude_ex_macro(TRANSFORM_OT_translate={"value": (1.91, 0, 0)})`,
  object mode, assert: the 4 rails (1,±1,±1)→(2.91,±1,±1) have cr=1.0; the 4 new rim edges at
  x=2.91 have cr=0; the 4 original creased edges keep cr=1. Expect FAIL now (rails cr=0 —
  matches `open_box_start_finish`).
- [ ] **Step 2: implement** per the algorithm block + registration (+ macro define) above.
- [ ] **Step 3: blinker reload; rerun Step 1 → PASS.**
- [ ] **Step 4: negative + regression tests (same MCP call or second one, v5):**
  (a) oblique: fresh dup of `open_box_start`, same rim selection, extrude
  `{"value": (0, 0, 2)}` — rails run +Z, creased edges run X: ALL new geometry must stay
  crease-free (45° gate holds); (b) Rule A regression: dup `start` (dx=13.5 into v5), select
  its marked edge 2, macro with `{"value": (0.9, 0, 0)}` — same checks as Task 2 (rails, new
  edge, orig all sharp/bw1/cr1; clean edge clean).
- [ ] **Step 5: update docs page** (`op_mesh_extrude_ex.md`): propagation = Rule A + Rule B
  (with the 45° continuation gate), macro is four steps, Rule B skipped/no-op when the
  translate is cancelled, `CONTINUATION_ANGLE` module constant.
- [ ] **Step 6: commit** (`operators/mesh_extrude_attrs.py`, `__init__.py`,
  `docs/operators/op_mesh_extrude_ex.md`):
  `feat(mesh): extrude wrapper continues marks from non-extruded edges (rule B)`
