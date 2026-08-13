# iOps Selection Sets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Named, unlimited selection sets for verts/edges/faces (Edit Mode) and objects (Object Mode), with boolean ops, a UIList N-panel and 3D View header integration.

**Architecture:** Edit-mode membership lives on the elements themselves as hidden int attributes (`.iops_ss_<D>_<name>`, one per set per domain) — undo-safe, topology-robust, no set-count limit. Object-mode sets live in a `Scene` CollectionProperty. A never-persisted WindowManager "mirror" collection feeds the UIList and is rebuilt from the source of truth by app handlers (depsgraph/undo/redo), never from panel `draw()` (writing ID data in draw is forbidden).

**Tech Stack:** Blender 4.x Python API (bpy, bmesh int layers), pytest for the bpy-free core, MCP live-Blender smoke tests via `mcp__blender__execute_blender_python` (load the `blender-mcp` skill before the first MCP step).

**Spec:** `docs/superpowers/specs/2026-08-04-selection-sets-design.md`

## Global Constraints

- Attribute name scheme: `.iops_ss_<D>_<name>`, `D ∈ {V,E,F}`; leading dot hides it from the Attributes panel. Set names ≤ 48 chars after sanitize.
- int (0/1) bmesh layers, not bool.
- Never write to `bpy` ID data from `draw()` callbacks — mirror rebuilds happen in operators and app handlers only.
- Hidden (`hide`) elements are never selected by recall.
- Dead object refs / vanished elements are skipped silently; UI shows counts (`0` or `alive/total`) + warning icon.
- Operator idnames use the `iops.ss_*` prefix; classes follow `IOPS_OT_*` / `IOPS_UL_*` / `IOPS_PT_*` / `IOPS_MT_*` repo conventions.
- pytest tests import `utils.selection_sets_core` (no bpy), matching `tests/test_smart_inset_core.py` conventions.
- One commit per task (user preference: solid commits, no piles).
- MCP note: `bpy.ops.ed.undo()` needs a window context override (see memory `project_smart_insets` gotcha) — use `with bpy.context.temp_override(window=bpy.context.window_manager.windows[0]): bpy.ops.ed.undo()` in smoke snippets.

---

### Task 1: Pure core helpers (`utils/selection_sets_core.py`)

**Files:**
- Create: `utils/selection_sets_core.py`
- Test: `tests/test_selection_sets_core.py`

**Interfaces:**
- Produces (used by Tasks 2–5):
  - `ATTR_PREFIX = ".iops_ss_"`, `DOMAINS = ("V", "E", "F")`, `MAX_NAME_LEN = 48`
  - `make_attr_name(domain: str, name: str) -> str`
  - `parse_attr_name(attr: str) -> tuple[str, str] | None` — `(domain, set_name)` or None for foreign attributes
  - `sanitize_set_name(name: str) -> str` — stripped, whitespace-collapsed, truncated, never empty (falls back to `"Set"`)
  - `unique_name(name: str, existing: collection[str]) -> str` — Blender-style `.001` suffixing
  - `group_sets(attr_names: iterable[str]) -> dict[str, str]` — `{set_name: flags}`, flags a subset of `"VEF"` in that order
  - `merge_membership(memberships: iterable[dict[str, set]]) -> dict[str, set]` — union per domain key
  - `diff_membership(a: dict[str, set], b: dict[str, set]) -> dict[str, set]` — symmetric difference per domain key

- [ ] **Step 1: Write the failing tests**

Create `tests/test_selection_sets_core.py`:

```python
import pytest

from utils.selection_sets_core import (
    ATTR_PREFIX, MAX_NAME_LEN,
    make_attr_name, parse_attr_name, sanitize_set_name, unique_name,
    group_sets, merge_membership, diff_membership,
)


def test_make_parse_roundtrip():
    attr = make_attr_name("V", "bolts")
    assert attr == ".iops_ss_V_bolts"
    assert parse_attr_name(attr) == ("V", "bolts")


def test_parse_name_with_underscores():
    assert parse_attr_name(".iops_ss_F_door_handle_top") == ("F", "door_handle_top")


def test_parse_rejects_foreign_attrs():
    assert parse_attr_name("crease") is None
    assert parse_attr_name(".hidden_other") is None
    assert parse_attr_name(".iops_ss_X_bad_domain") is None
    assert parse_attr_name(".iops_ss_V_") is None  # empty name


def test_sanitize_strips_and_collapses():
    assert sanitize_set_name("  my   set  ") == "my set"


def test_sanitize_empty_falls_back():
    assert sanitize_set_name("   ") == "Set"


def test_sanitize_truncates():
    assert len(sanitize_set_name("x" * 200)) == MAX_NAME_LEN


def test_unique_name_no_clash():
    assert unique_name("Set", []) == "Set"


def test_unique_name_suffixes():
    assert unique_name("Set", ["Set"]) == "Set.001"
    assert unique_name("Set", ["Set", "Set.001"]) == "Set.002"


def test_group_sets_flags_ordered():
    names = [
        make_attr_name("F", "hinges"),
        make_attr_name("V", "hinges"),
        make_attr_name("E", "panel"),
        "crease",  # foreign, ignored
    ]
    assert group_sets(names) == {"hinges": "VF", "panel": "E"}


def test_merge_membership():
    a = {"V": {1, 2}, "E": {5}}
    b = {"V": {2, 3}, "F": {7}}
    assert merge_membership([a, b]) == {"V": {1, 2, 3}, "E": {5}, "F": {7}}


def test_diff_membership_symmetric():
    a = {"V": {1, 2}, "E": {5}}
    b = {"V": {2, 3}}
    assert diff_membership(a, b) == {"V": {1, 3}, "E": {5}}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_selection_sets_core.py -v` (from repo root)
Expected: FAIL — `ModuleNotFoundError: utils.selection_sets_core`

- [ ] **Step 3: Implement the core module**

Create `utils/selection_sets_core.py`:

```python
"""Pure helpers for iOps Selection Sets — no bpy imports.

Edit-mode selection sets persist as hidden int attributes on the mesh, one
attribute per set per domain:

    .iops_ss_<D>_<name>      D in {V, E, F}

The leading dot hides the attribute from the Attributes panel; the domain
letter keeps names unique across domains (Mesh attribute names share one
namespace); the set's select mode is derived from which domain attributes
exist. Membership lives on the elements themselves, so sets survive undo,
file save and topology edits (deleted elements simply leave the set).
"""

ATTR_PREFIX = ".iops_ss_"
DOMAINS = ("V", "E", "F")
# Blender attribute names cap at 64 bytes; leave room for the prefix,
# domain letter and a ".001" dedup suffix.
MAX_NAME_LEN = 48


def make_attr_name(domain, name):
    return f"{ATTR_PREFIX}{domain}_{name}"


def parse_attr_name(attr):
    """(domain, set_name) for our attributes, None for anything else."""
    if not attr.startswith(ATTR_PREFIX):
        return None
    rest = attr[len(ATTR_PREFIX):]
    if len(rest) < 3 or rest[0] not in DOMAINS or rest[1] != "_":
        return None
    name = rest[2:]
    if not name:
        return None
    return rest[0], name


def sanitize_set_name(name):
    clean = " ".join(str(name).split())
    if not clean:
        clean = "Set"
    return clean[:MAX_NAME_LEN]


def unique_name(name, existing):
    """Blender-style dedup: 'Set' -> 'Set.001' -> 'Set.002' ..."""
    taken = set(existing)
    if name not in taken:
        return name
    i = 1
    while f"{name}.{i:03d}" in taken:
        i += 1
    return f"{name}.{i:03d}"


def group_sets(attr_names):
    """{set_name: flags} from a flat list of attribute names.

    Flags are a subset of "VEF", always in that order.
    """
    sets = {}
    for attr in attr_names:
        parsed = parse_attr_name(attr)
        if parsed is None:
            continue
        domain, name = parsed
        sets.setdefault(name, set()).add(domain)
    return {n: "".join(d for d in DOMAINS if d in doms)
            for n, doms in sets.items()}


def merge_membership(memberships):
    """Union of {domain: set(indices)} dicts."""
    out = {}
    for m in memberships:
        for domain, indices in m.items():
            out.setdefault(domain, set()).update(indices)
    return out


def diff_membership(a, b):
    """Per-domain symmetric difference of {domain: set(indices)} dicts.

    Domains present in only one side pass through unchanged; empty
    results are dropped.
    """
    out = {}
    for domain in set(a) | set(b):
        d = a.get(domain, set()) ^ b.get(domain, set())
        if d:
            out[domain] = d
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_selection_sets_core.py -v`
Expected: 11 PASS. Also run the full suite to check nothing broke: `python -m pytest tests -q`

- [ ] **Step 5: Commit**

```bash
git add utils/selection_sets_core.py tests/test_selection_sets_core.py
git commit -m "feat(selection-sets): pure core helpers — attr-name codec, dedup, membership algebra"
```

---

### Task 2: Edit-mode backend + operators, registered

**Files:**
- Create: `operators/mesh_selection_sets.py`
- Modify: `__init__.py` (imports, `classes` tuple)

**Interfaces:**
- Consumes: everything from `utils.selection_sets_core` (Task 1).
- Produces:
  - Backend fns (used by Tasks 3–5): `bm_list_sets(bm) -> dict[name, flags]`, `bm_save_set(bm, name, mode)`, `bm_delete_set(bm, name)`, `bm_delete_all(bm) -> int`, `bm_rename_set(bm, old, new)`, `bm_set_membership(bm, name) -> dict[domain, set[int]]`, `bm_write_membership(bm, name, membership)`, `bm_apply_selection(bm, name, action)`, `bm_modify_set(bm, name, add: bool)`, `bm_set_count(bm, name) -> int`, `edit_meshes(context)` iterator, `all_edit_set_names(context) -> list[str]`.
  - Operators (idnames): `iops.ss_new`, `iops.ss_recall` (props: `set_name: StringProperty`, `action: EnumProperty in {SET, EXTEND, SUBTRACT}`), `iops.ss_replace`, `iops.ss_modify` (props: `set_name`, `add: BoolProperty` — covers the spec's Add to Set / Remove from Set as one code path), `iops.ss_delete` (with `set_name`), `iops.ss_delete_all`.
  - `_tag_mirror_dirty()` — module-level no-op hook, later monkey-wired by the UI module (Task 5); every operator calls it at the end of `execute`.

- [ ] **Step 1: Write the module**

Create `operators/mesh_selection_sets.py`:

```python
import bpy
import bmesh

from ..utils.selection_sets_core import (
    DOMAINS,
    make_attr_name,
    parse_attr_name,
    sanitize_set_name,
    unique_name,
    group_sets,
)


# Wired to the UI mirror's dirty-tag by ui/iops_selection_sets_panel.py at
# register time; a no-op until then so the backend has no UI dependency.
def _tag_mirror_dirty():
    pass


# ----------------------------------------------------------------------
# bmesh backend (Edit Mode)
# ----------------------------------------------------------------------
def _dom_seq(bm, domain):
    return {"V": bm.verts, "E": bm.edges, "F": bm.faces}[domain]


def _dom_layers(bm, domain):
    return _dom_seq(bm, domain).layers.int


def bm_list_sets(bm):
    names = []
    for d in DOMAINS:
        names.extend(_dom_layers(bm, d).keys())
    return group_sets(names)


def bm_save_set(bm, name, mode):
    """Write current selection into set `name` on the domains enabled in
    `mode` (tool_settings.mesh_select_mode triple)."""
    for d, on in zip(DOMAINS, mode):
        if not on:
            continue
        layers = _dom_layers(bm, d)
        attr = make_attr_name(d, name)
        layer = layers.get(attr)
        if layer is None:
            layer = layers.new(attr)
        for e in _dom_seq(bm, d):
            e[layer] = 1 if e.select else 0


def bm_delete_set(bm, name):
    for d in DOMAINS:
        layers = _dom_layers(bm, d)
        layer = layers.get(make_attr_name(d, name))
        if layer is not None:
            layers.remove(layer)


def bm_delete_all(bm):
    count = 0
    for d in DOMAINS:
        layers = _dom_layers(bm, d)
        for key in list(layers.keys()):
            if parse_attr_name(key) is not None:
                layers.remove(layers[key])
                count += 1
    return count


def bm_rename_set(bm, old, new):
    """bmesh layers can't be renamed in place: new + copy_from + remove.
    layers.new() may invalidate existing layer references — re-fetch."""
    for d in DOMAINS:
        layers = _dom_layers(bm, d)
        if layers.get(make_attr_name(d, old)) is None:
            continue
        layers.new(make_attr_name(d, new))
        src = layers.get(make_attr_name(d, old))
        dst = layers.get(make_attr_name(d, new))
        dst.copy_from(src)
        layers.remove(src)


def bm_set_membership(bm, name):
    """{domain: set(element indices)} for the set's stored domains."""
    out = {}
    for d in DOMAINS:
        layer = _dom_layers(bm, d).get(make_attr_name(d, name))
        if layer is None:
            continue
        seq = _dom_seq(bm, d)
        seq.index_update()
        out[d] = {e.index for e in seq if e[layer]}
    return out


def bm_write_membership(bm, name, membership):
    """Create/overwrite set `name` from {domain: set(indices)}."""
    bm_delete_set(bm, name)
    for d, indices in membership.items():
        layer = _dom_layers(bm, d).new(make_attr_name(d, name))
        seq = _dom_seq(bm, d)
        seq.index_update()
        for e in seq:
            e[layer] = 1 if e.index in indices else 0


def bm_set_count(bm, name):
    total = 0
    for d in DOMAINS:
        layer = _dom_layers(bm, d).get(make_attr_name(d, name))
        if layer is not None:
            total += sum(1 for e in _dom_seq(bm, d) if e[layer])
    return total


def bm_apply_selection(bm, name, action):
    """SET/EXTEND: select set elements; SUBTRACT: deselect them.
    Skips hidden elements. Flushes after. Caller handles deselect-all
    and select-mode restore for SET."""
    select = action != "SUBTRACT"
    for d in DOMAINS:
        layer = _dom_layers(bm, d).get(make_attr_name(d, name))
        if layer is None:
            continue
        for e in _dom_seq(bm, d):
            if e[layer] and not e.hide:
                e.select = select
    bm.select_flush(select)
    bm.select_flush_mode()


def bm_modify_set(bm, name, add):
    """Add (or remove) the current selection to/from an existing set,
    only on the domains the set already stores."""
    for d in DOMAINS:
        layer = _dom_layers(bm, d).get(make_attr_name(d, name))
        if layer is None:
            continue
        for e in _dom_seq(bm, d):
            if e.select:
                e[layer] = 1 if add else 0


def edit_meshes(context):
    """(object, bmesh) for every unique mesh in edit mode."""
    for obj in context.objects_in_mode_unique_data:
        if obj.type == "MESH":
            yield obj, bmesh.from_edit_mesh(obj.data)


def all_edit_set_names(context):
    names = set()
    for _obj, bm in edit_meshes(context):
        names.update(bm_list_sets(bm).keys())
    return sorted(names)


def _flags_for(context, set_name):
    """Union of the set's flags across all meshes in edit."""
    flags = set()
    for _obj, bm in edit_meshes(context):
        flags.update(bm_list_sets(bm).get(set_name, ""))
    return "".join(d for d in DOMAINS if d in flags)


def _update_edit_meshes(context):
    for obj, _bm in edit_meshes(context):
        bmesh.update_edit_mesh(obj.data, loop_triangles=False,
                               destructive=False)


def _have_edit_selection(context):
    return any(
        obj.data.total_vert_sel or obj.data.total_edge_sel
        or obj.data.total_face_sel
        for obj, _bm in edit_meshes(context)
    )


# ----------------------------------------------------------------------
# Operators
# ----------------------------------------------------------------------
class IOPS_OT_SSNew(bpy.types.Operator):
    """Save the current selection as a new selection set"""
    bl_idname = "iops.ss_new"
    bl_label = "New Selection Set"
    bl_options = {"REGISTER", "UNDO"}

    set_name: bpy.props.StringProperty(name="Name", default="Set")

    @classmethod
    def poll(cls, context):
        return context.mode == "EDIT_MESH" and _have_edit_selection(context)

    def execute(self, context):
        name = unique_name(sanitize_set_name(self.set_name),
                           all_edit_set_names(context))
        mode = context.tool_settings.mesh_select_mode[:]
        for obj, bm in edit_meshes(context):
            me = obj.data
            if me.total_vert_sel or me.total_edge_sel or me.total_face_sel:
                bm_save_set(bm, name, mode)
        _update_edit_meshes(context)
        _tag_mirror_dirty()
        return {"FINISHED"}


class IOPS_OT_SSRecall(bpy.types.Operator):
    """Select the set's elements.
    Shift: extend current selection. Ctrl: subtract from it"""
    bl_idname = "iops.ss_recall"
    bl_label = "Recall Selection Set"
    bl_options = {"REGISTER", "UNDO"}

    set_name: bpy.props.StringProperty(name="Set")
    action: bpy.props.EnumProperty(items=[
        ("SET", "Set", "Replace selection"),
        ("EXTEND", "Extend", "Add to selection"),
        ("SUBTRACT", "Subtract", "Remove from selection"),
    ], default="SET")

    @classmethod
    def poll(cls, context):
        return context.mode == "EDIT_MESH"

    def invoke(self, context, event):
        if event.ctrl:
            self.action = "SUBTRACT"
        elif event.shift:
            self.action = "EXTEND"
        else:
            self.action = "SET"
        return self.execute(context)

    def execute(self, context):
        flags = _flags_for(context, self.set_name)
        if not flags:
            self.report({"WARNING"}, f"Set '{self.set_name}' not found")
            return {"CANCELLED"}
        if self.action == "SET":
            bpy.ops.mesh.select_all(action="DESELECT")
            context.tool_settings.mesh_select_mode = tuple(
                d in flags for d in DOMAINS)
        for _obj, bm in edit_meshes(context):
            bm_apply_selection(bm, self.set_name, self.action)
            active = bm.select_history.active
            if active is not None and not active.select:
                bm.select_history.remove(active)
        _update_edit_meshes(context)
        return {"FINISHED"}


class IOPS_OT_SSReplace(bpy.types.Operator):
    """Overwrite the set with the current selection"""
    bl_idname = "iops.ss_replace"
    bl_label = "Replace Selection Set"
    bl_options = {"REGISTER", "UNDO"}

    set_name: bpy.props.StringProperty(name="Set")

    @classmethod
    def poll(cls, context):
        return context.mode == "EDIT_MESH" and _have_edit_selection(context)

    def execute(self, context):
        mode = context.tool_settings.mesh_select_mode[:]
        for _obj, bm in edit_meshes(context):
            bm_delete_set(bm, self.set_name)
            bm_save_set(bm, self.set_name, mode)
        _update_edit_meshes(context)
        _tag_mirror_dirty()
        return {"FINISHED"}


class IOPS_OT_SSModify(bpy.types.Operator):
    """Add or remove the current selection to/from an existing set"""
    bl_idname = "iops.ss_modify"
    bl_label = "Add/Remove Selection To Set"
    bl_options = {"REGISTER", "UNDO"}

    set_name: bpy.props.StringProperty(name="Set")
    add: bpy.props.BoolProperty(name="Add", default=True)

    @classmethod
    def poll(cls, context):
        return context.mode == "EDIT_MESH" and _have_edit_selection(context)

    def execute(self, context):
        for _obj, bm in edit_meshes(context):
            bm_modify_set(bm, self.set_name, self.add)
        _update_edit_meshes(context)
        _tag_mirror_dirty()
        return {"FINISHED"}


class IOPS_OT_SSDelete(bpy.types.Operator):
    """Delete this selection set"""
    bl_idname = "iops.ss_delete"
    bl_label = "Delete Selection Set"
    bl_options = {"REGISTER", "UNDO"}

    set_name: bpy.props.StringProperty(name="Set")

    @classmethod
    def poll(cls, context):
        return context.mode == "EDIT_MESH"

    def execute(self, context):
        for _obj, bm in edit_meshes(context):
            bm_delete_set(bm, self.set_name)
        _update_edit_meshes(context)
        _tag_mirror_dirty()
        return {"FINISHED"}


class IOPS_OT_SSDeleteAll(bpy.types.Operator):
    """Delete all selection sets"""
    bl_idname = "iops.ss_delete_all"
    bl_label = "Delete All Selection Sets"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "EDIT_MESH"

    def execute(self, context):
        removed = 0
        for _obj, bm in edit_meshes(context):
            removed += bm_delete_all(bm)
        _update_edit_meshes(context)
        _tag_mirror_dirty()
        return {"FINISHED"} if removed else {"CANCELLED"}
```

Note: `iops.ss_add_to` / `iops.ss_remove_from` from the spec collapse into one
`iops.ss_modify` operator with an `add` bool — one code path, two buttons.

- [ ] **Step 2: Register in `__init__.py`**

Add the import near the other operator imports (e.g. after
`from .operators.mesh_smart_inset import ...` block):

```python
from .operators.mesh_selection_sets import (
    IOPS_OT_SSNew,
    IOPS_OT_SSRecall,
    IOPS_OT_SSReplace,
    IOPS_OT_SSModify,
    IOPS_OT_SSDelete,
    IOPS_OT_SSDeleteAll,
)
```

Add all six class names to the `classes` tuple (any position after the
PropertyGroups block; keep them together).

- [ ] **Step 3: MCP smoke test**

Load the `blender-mcp` skill, reload the addon per its recipe, then run:

```python
import bpy, bmesh
# fresh scene
bpy.ops.wm.read_homefile(use_empty=False)
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.iops.ss_new(set_name="all")
bpy.ops.mesh.select_all(action='DESELECT')
bm = bmesh.from_edit_mesh(bpy.context.object.data)
bm.verts.ensure_lookup_table()
bm.verts[0].select = True
bm.select_flush_mode()
bmesh.update_edit_mesh(bpy.context.object.data)
bpy.ops.iops.ss_new(set_name="one")
# recall replaces selection
bpy.ops.iops.ss_recall(set_name="all", action='SET')
me = bpy.context.object.data
print("after recall all:", me.total_vert_sel)      # expect 8
bpy.ops.iops.ss_recall(set_name="one", action='SUBTRACT')
print("after subtract one:", me.total_vert_sel)    # expect 7
bpy.ops.iops.ss_recall(set_name="one", action='EXTEND')
print("after extend one:", me.total_vert_sel)      # expect 8
# dedup: second "all" becomes all.001
bpy.ops.iops.ss_new(set_name="all")
from InteractionOps.operators.mesh_selection_sets import bm_list_sets
bm = bmesh.from_edit_mesh(me)
print("sets:", sorted(bm_list_sets(bm)))           # expect ['all', 'all.001', 'one']
bpy.ops.iops.ss_delete(set_name="all.001")
bpy.ops.iops.ss_delete_all()
bm = bmesh.from_edit_mesh(me)
print("after delete_all:", bm_list_sets(bm))       # expect {}
bpy.ops.object.mode_set(mode='OBJECT')
```

Expected: printed values match the comments, no tracebacks.

- [ ] **Step 4: Commit**

```bash
git add operators/mesh_selection_sets.py __init__.py
git commit -m "feat(selection-sets): edit-mode backend and operators on hidden int attributes"
```

---

### Task 3: Object-mode sets on the Scene

**Files:**
- Modify: `operators/mesh_selection_sets.py` (scene PropertyGroups, backend fns, operator branches)
- Modify: `__init__.py` (register PropertyGroups + `Scene.iops_selection_sets`)

**Interfaces:**
- Consumes: Task 2 operators and helpers.
- Produces:
  - `IOPS_SS_ObjectRef(PropertyGroup)` — uses built-in `.name` as object name.
  - `IOPS_SS_SceneSet(PropertyGroup)` — `.name` = set name, `objects: CollectionProperty(type=IOPS_SS_ObjectRef)`.
  - `bpy.types.Scene.iops_selection_sets: CollectionProperty(type=IOPS_SS_SceneSet)`.
  - `scene_list_sets(scene) -> dict[name, tuple[alive, total]]`, `scene_save_set(scene, name, objects)`, `scene_get(scene, name)`, `scene_delete_set(scene, name)`, `scene_rename_set(scene, old, new)`, `scene_membership(scene, name) -> set[str]`, `scene_write_membership(scene, name, obj_names)`.
  - All Task 2 operators grow an Object-Mode branch (poll allows `context.mode == "OBJECT"`).

- [ ] **Step 1: Add scene storage to `operators/mesh_selection_sets.py`**

PropertyGroups + helpers (top of file, after the imports):

```python
class IOPS_SS_ObjectRef(bpy.types.PropertyGroup):
    """One object reference inside a scene selection set (name only)."""
    pass


class IOPS_SS_SceneSet(bpy.types.PropertyGroup):
    objects: bpy.props.CollectionProperty(type=IOPS_SS_ObjectRef)


def scene_get(scene, name):
    return scene.iops_selection_sets.get(name)


def scene_list_sets(scene):
    """{name: (alive, total)} — alive counts refs still present in the
    scene; dead refs are kept (the user decides to re-save or delete)."""
    out = {}
    for item in scene.iops_selection_sets:
        total = len(item.objects)
        alive = sum(1 for ref in item.objects if ref.name in scene.objects)
        out[item.name] = (alive, total)
    return out


def scene_write_membership(scene, name, obj_names):
    item = scene_get(scene, name)
    if item is None:
        item = scene.iops_selection_sets.add()
        item.name = name
    item.objects.clear()
    for obj_name in sorted(obj_names):
        ref = item.objects.add()
        ref.name = obj_name


def scene_save_set(scene, name, objects):
    scene_write_membership(scene, name, [o.name for o in objects])


def scene_membership(scene, name):
    item = scene_get(scene, name)
    if item is None:
        return set()
    return {ref.name for ref in item.objects}


def scene_delete_set(scene, name):
    idx = scene.iops_selection_sets.find(name)
    if idx >= 0:
        scene.iops_selection_sets.remove(idx)


def scene_rename_set(scene, old, new):
    item = scene_get(scene, old)
    if item is not None:
        item.name = new
```

- [ ] **Step 2: Branch the operators**

Every operator gains Object-Mode handling. Shared poll pattern — replace the
Edit-only polls:

```python
# IOPS_OT_SSNew / IOPS_OT_SSReplace / IOPS_OT_SSModify:
@classmethod
def poll(cls, context):
    if context.mode == "EDIT_MESH":
        return _have_edit_selection(context)
    return context.mode == "OBJECT" and bool(context.selected_objects)

# IOPS_OT_SSRecall / IOPS_OT_SSDelete / IOPS_OT_SSDeleteAll:
@classmethod
def poll(cls, context):
    return context.mode in {"EDIT_MESH", "OBJECT"}
```

Execute branches (`if context.mode == "OBJECT":` first, existing edit code in
the `else`):

```python
# IOPS_OT_SSNew.execute, object branch:
scene = context.scene
name = unique_name(sanitize_set_name(self.set_name),
                   [s.name for s in scene.iops_selection_sets])
scene_save_set(scene, name, context.selected_objects)
_tag_mirror_dirty()
return {"FINISHED"}

# IOPS_OT_SSRecall.execute, object branch:
scene = context.scene
if scene_get(scene, self.set_name) is None:
    self.report({"WARNING"}, f"Set '{self.set_name}' not found")
    return {"CANCELLED"}
if self.action == "SET":
    for obj in context.selected_objects:
        obj.select_set(False)
select = self.action != "SUBTRACT"
last = None
for obj_name in scene_membership(scene, self.set_name):
    obj = scene.objects.get(obj_name)
    if obj is not None and not obj.hide_get():
        obj.select_set(select)
        if select:
            last = obj
if last is not None and self.action == "SET":
    context.view_layer.objects.active = last
return {"FINISHED"}

# IOPS_OT_SSReplace.execute, object branch:
scene_save_set(context.scene, self.set_name, context.selected_objects)
_tag_mirror_dirty()
return {"FINISHED"}

# IOPS_OT_SSModify.execute, object branch:
scene = context.scene
current = scene_membership(scene, self.set_name)
selected = {o.name for o in context.selected_objects}
new = current | selected if self.add else current - selected
scene_write_membership(scene, self.set_name, new)
_tag_mirror_dirty()
return {"FINISHED"}

# IOPS_OT_SSDelete.execute, object branch:
scene_delete_set(context.scene, self.set_name)
_tag_mirror_dirty()
return {"FINISHED"}

# IOPS_OT_SSDeleteAll.execute, object branch:
n = len(context.scene.iops_selection_sets)
context.scene.iops_selection_sets.clear()
_tag_mirror_dirty()
return {"FINISHED"} if n else {"CANCELLED"}
```

- [ ] **Step 3: Register scene props in `__init__.py`**

Extend the Task 2 import with `IOPS_SS_ObjectRef, IOPS_SS_SceneSet`. Add both
to `classes` **before** the operator entries (CollectionProperty targets must
register first — same rule as the `IOPS_WidgetDataKV` comment there). In
`register()`, next to the other `bpy.types.Scene.*` pointers:

```python
bpy.types.Scene.iops_selection_sets = bpy.props.CollectionProperty(
    type=IOPS_SS_SceneSet
)
```

In `unregister()`: `del bpy.types.Scene.iops_selection_sets` (wrap in
try/except AttributeError, matching neighboring cleanup style).

- [ ] **Step 4: MCP smoke test**

Reload addon, then:

```python
import bpy
bpy.ops.wm.read_homefile(use_empty=False)
cube = bpy.context.object
bpy.ops.mesh.primitive_uv_sphere_add(location=(3, 0, 0))
sphere = bpy.context.object
bpy.ops.object.select_all(action='SELECT')
bpy.ops.iops.ss_new(set_name="both")
sphere.select_set(False)
bpy.ops.iops.ss_new(set_name="cube_only")
bpy.ops.object.select_all(action='DESELECT')
bpy.ops.iops.ss_recall(set_name="both", action='SET')
print("both:", [o.name for o in bpy.context.selected_objects])  # cube + sphere
bpy.ops.iops.ss_recall(set_name="cube_only", action='SUBTRACT')
print("minus cube:", [o.name for o in bpy.context.selected_objects])  # sphere
# dead-ref counting
bpy.data.objects.remove(sphere)
from InteractionOps.operators.mesh_selection_sets import scene_list_sets
print(scene_list_sets(bpy.context.scene))  # both: (1, 2), cube_only: (1, 1)
bpy.ops.iops.ss_recall(set_name="both", action='SET')  # no traceback
print("alive recall:", [o.name for o in bpy.context.selected_objects])
```

Expected: matches comments, dead sphere skipped without error.

- [ ] **Step 5: Commit**

```bash
git add operators/mesh_selection_sets.py __init__.py
git commit -m "feat(selection-sets): object-mode sets stored on the scene"
```

---

### Task 4: Union and Difference

**Files:**
- Modify: `operators/mesh_selection_sets.py`
- Modify: `__init__.py` (register the two operators)

**Interfaces:**
- Consumes: `merge_membership`, `diff_membership` (Task 1); backend fns (Tasks 2–3).
- Produces:
  - `iops.ss_union` — props `set_names: StringProperty` (`;`-joined), `target: StringProperty` (empty → new set named `Union`).
  - `iops.ss_difference` — props `set_names: StringProperty` (`;`-joined). Two names → symmetric difference of the two sets becomes the selection; one name → symmetric difference of the current selection vs that set.
  - `bm_selection_membership(bm, mode) -> dict[domain, set[int]]` helper.

- [ ] **Step 1: Implement**

Add to `operators/mesh_selection_sets.py`:

```python
def bm_selection_membership(bm, mode):
    out = {}
    for d, on in zip(DOMAINS, mode):
        if not on:
            continue
        seq = _dom_seq(bm, d)
        seq.index_update()
        out[d] = {e.index for e in seq if e.select}
    return out


def _bm_select_membership(bm, membership):
    """Select exactly the given {domain: indices} (additive; caller
    deselects first)."""
    for d, indices in membership.items():
        seq = _dom_seq(bm, d)
        seq.index_update()
        for e in seq:
            if e.index in indices and not e.hide:
                e.select = True
    bm.select_flush(True)
    bm.select_flush_mode()


class IOPS_OT_SSUnion(bpy.types.Operator):
    """Merge the checked sets into a new set or into the target set"""
    bl_idname = "iops.ss_union"
    bl_label = "Union Selection Sets"
    bl_options = {"REGISTER", "UNDO"}

    set_names: bpy.props.StringProperty(name="Sets")  # ';'-joined
    target: bpy.props.StringProperty(name="Target", default="")

    @classmethod
    def poll(cls, context):
        return context.mode in {"EDIT_MESH", "OBJECT"}

    def execute(self, context):
        names = [n for n in self.set_names.split(";") if n]
        if len(names) < 2 and not (self.target and len(names) == 1):
            self.report({"WARNING"}, "Check at least two sets to union")
            return {"CANCELLED"}
        if context.mode == "OBJECT":
            scene = context.scene
            merged = set().union(
                *(scene_membership(scene, n) for n in names))
            target = self.target or unique_name(
                "Union", [s.name for s in scene.iops_selection_sets])
            scene_write_membership(scene, target, merged)
        else:
            target = self.target or unique_name(
                "Union", all_edit_set_names(context))
            for _obj, bm in edit_meshes(context):
                merged = merge_membership(
                    bm_set_membership(bm, n) for n in names)
                if merged:
                    bm_write_membership(bm, target, merged)
            _update_edit_meshes(context)
        _tag_mirror_dirty()
        return {"FINISHED"}


class IOPS_OT_SSDifference(bpy.types.Operator):
    """Select the symmetric difference: between two checked sets, or
    between the current selection and one set"""
    bl_idname = "iops.ss_difference"
    bl_label = "Selection Sets Difference"
    bl_options = {"REGISTER", "UNDO"}

    set_names: bpy.props.StringProperty(name="Sets")  # ';'-joined, 1 or 2

    @classmethod
    def poll(cls, context):
        return context.mode in {"EDIT_MESH", "OBJECT"}

    def execute(self, context):
        names = [n for n in self.set_names.split(";") if n]
        if not names or len(names) > 2:
            self.report({"WARNING"},
                        "Check one set (vs selection) or exactly two sets")
            return {"CANCELLED"}
        if context.mode == "OBJECT":
            scene = context.scene
            a = (scene_membership(scene, names[0]) if len(names) == 2
                 else {o.name for o in context.selected_objects})
            b = scene_membership(scene, names[-1])
            result = a ^ b
            for obj in context.selected_objects:
                obj.select_set(False)
            for obj_name in result:
                obj = scene.objects.get(obj_name)
                if obj is not None and not obj.hide_get():
                    obj.select_set(True)
        else:
            mode = context.tool_settings.mesh_select_mode[:]
            per_bm = []
            for obj, bm in edit_meshes(context):
                a = (bm_set_membership(bm, names[0]) if len(names) == 2
                     else bm_selection_membership(bm, mode))
                b = bm_set_membership(bm, names[-1])
                per_bm.append((obj, bm, diff_membership(a, b)))
            bpy.ops.mesh.select_all(action="DESELECT")
            for _obj, bm, result in per_bm:
                _bm_select_membership(bm, result)
            _update_edit_meshes(context)
        return {"FINISHED"}
```

Note (edit mode): membership is computed per-mesh **before** the deselect-all
and applied right after — indices stay valid because nothing touches topology
in between.

- [ ] **Step 2: Register**

Add `IOPS_OT_SSUnion, IOPS_OT_SSDifference` to the import and `classes`
tuple in `__init__.py`.

- [ ] **Step 3: MCP smoke test**

Reload addon, then:

```python
import bpy, bmesh
bpy.ops.wm.read_homefile(use_empty=False)
me = bpy.context.object.data
bpy.ops.object.mode_set(mode='EDIT')
bm = bmesh.from_edit_mesh(me)
bm.verts.ensure_lookup_table()

def sel(idxs):
    bpy.ops.mesh.select_all(action='DESELECT')
    bm = bmesh.from_edit_mesh(me); bm.verts.ensure_lookup_table()
    for i in idxs: bm.verts[i].select = True
    bm.select_flush_mode(); bmesh.update_edit_mesh(me)

sel([0, 1, 2]); bpy.ops.iops.ss_new(set_name="a")
sel([2, 3, 4]); bpy.ops.iops.ss_new(set_name="b")
bpy.ops.iops.ss_union(set_names="a;b")
bpy.ops.iops.ss_recall(set_name="Union", action='SET')
print("union count:", me.total_vert_sel)          # expect 5
bpy.ops.iops.ss_difference(set_names="a;b")
print("diff count:", me.total_vert_sel)           # expect 4 (0,1,3,4)
sel([0, 7])
bpy.ops.iops.ss_difference(set_names="a")         # selection vs a
print("sel-vs-a count:", me.total_vert_sel)       # expect 3 (1,2,7)
bpy.ops.object.mode_set(mode='OBJECT')
```

Expected: 5 / 4 / 3.

- [ ] **Step 4: Commit**

```bash
git add operators/mesh_selection_sets.py __init__.py
git commit -m "feat(selection-sets): union and symmetric-difference operators"
```

---

### Task 5: WM mirror, handlers, UIList, panel

**Files:**
- Create: `ui/iops_selection_sets_panel.py`
- Modify: `__init__.py` (register classes, call `register_selection_sets_ui()` / `unregister_selection_sets_ui()`)

**Interfaces:**
- Consumes: backend fns from `operators/mesh_selection_sets.py`; `iops.ss_*` operators.
- Produces:
  - `IOPS_SS_MirrorItem(PropertyGroup)` — `name` (StringProperty with rename write-through update), `flags: StringProperty` (`"V(E)(F)"` or `"OBJ"`), `count: IntProperty`, `total: IntProperty`, `checked: BoolProperty`.
  - `bpy.types.WindowManager.iops_ss_mirror` (Collection), `iops_ss_index` (Int).
  - `rebuild_mirror(context, force=False)`, `tag_mirror_dirty()` (wired into the backend's `_tag_mirror_dirty` hook).
  - `IOPS_UL_SelectionSets(UIList)`, `IOPS_PT_SelectionSets_Panel(Panel)`, `iops.ss_refresh` operator.
  - `register_selection_sets_ui()` / `unregister_selection_sets_ui()` — WM props + app handlers (`depsgraph_update_post`, `undo_post`, `redo_post`, `load_post`).

- [ ] **Step 1: Write the module**

Create `ui/iops_selection_sets_panel.py`:

```python
"""iOps Selection Sets panel: UIList over a WindowManager mirror.

The mirror is UI-only state rebuilt from the source of truth (mesh
attributes / scene collection). Panel draw() callbacks may not write to
ID data, so rebuilds run from app handlers (depsgraph/undo/redo/load)
and from the operators via tag_mirror_dirty(); a cheap signature check
keeps the handler no-op on unrelated updates.
"""
import bpy
from bpy.app.handlers import persistent

from ..operators import mesh_selection_sets as ss

_last_sig = None
_dirty = True
_syncing = False


def tag_mirror_dirty():
    global _dirty
    _dirty = True


def _mirror_name_update(self, context):
    """Write-through rename from the UIList double-click editor."""
    if _syncing:
        return
    old = self.get("_prev_name", "")
    new = ss.sanitize_set_name(self.name)
    if not old or old == new:
        return
    if self.flags == "OBJ":
        taken = [s.name for s in context.scene.iops_selection_sets
                 if s.name != old]
        new = ss.unique_name(new, taken)
        ss.scene_rename_set(context.scene, old, new)
    else:
        taken = [n for n in ss.all_edit_set_names(context) if n != old]
        new = ss.unique_name(new, taken)
        for obj, bm in ss.edit_meshes(context):
            ss.bm_rename_set(bm, old, new)
            import bmesh
            bmesh.update_edit_mesh(obj.data, loop_triangles=False,
                                   destructive=False)
    self["name"] = new          # raw write: no update recursion
    self["_prev_name"] = new
    tag_mirror_dirty()


class IOPS_SS_MirrorItem(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty(update=_mirror_name_update)
    flags: bpy.props.StringProperty()   # subset of "VEF", or "OBJ"
    count: bpy.props.IntProperty()
    total: bpy.props.IntProperty()
    checked: bpy.props.BoolProperty(default=False)


def _signature(context):
    if context.mode == "EDIT_MESH":
        sig = ["EDIT"]
        for obj, bm in ss.edit_meshes(context):
            sig.append((obj.name, len(bm.verts), len(bm.edges),
                        len(bm.faces),
                        tuple(sorted(ss.bm_list_sets(bm).items()))))
        return tuple(sig)
    scene = context.scene
    return ("OBJECT", len(scene.objects),
            tuple((s.name, len(s.objects))
                  for s in scene.iops_selection_sets))


def rebuild_mirror(context, force=False):
    global _last_sig, _dirty, _syncing
    if context.mode not in {"EDIT_MESH", "OBJECT"}:
        return
    sig = _signature(context)
    if not force and not _dirty and sig == _last_sig:
        return
    _last_sig, _dirty = sig, False

    wm = context.window_manager
    keep_checked = {it.name: it.checked for it in wm.iops_ss_mirror}
    active_name = ""
    if 0 <= wm.iops_ss_index < len(wm.iops_ss_mirror):
        active_name = wm.iops_ss_mirror[wm.iops_ss_index].name

    rows = []
    if context.mode == "EDIT_MESH":
        merged = {}   # name -> [flags-set, count]
        for _obj, bm in ss.edit_meshes(context):
            for name, flags in ss.bm_list_sets(bm).items():
                entry = merged.setdefault(name, [set(), 0])
                entry[0].update(flags)
                entry[1] += ss.bm_set_count(bm, name)
        for name in sorted(merged):
            flags = "".join(d for d in "VEF" if d in merged[name][0])
            count = merged[name][1]
            rows.append((name, flags, count, count))
    else:
        for name, (alive, total) in sorted(
                ss.scene_list_sets(context.scene).items()):
            rows.append((name, "OBJ", alive, total))

    _syncing = True
    try:
        wm.iops_ss_mirror.clear()
        for name, flags, count, total in rows:
            it = wm.iops_ss_mirror.add()
            it["name"] = name           # raw: skip rename update
            it["_prev_name"] = name
            it.flags = flags
            it.count = count
            it.total = total
            it.checked = keep_checked.get(name, False)
            if name == active_name:
                wm.iops_ss_index = len(wm.iops_ss_mirror) - 1
        wm.iops_ss_index = min(wm.iops_ss_index,
                               max(0, len(wm.iops_ss_mirror) - 1))
    finally:
        _syncing = False


@persistent
def _iops_ss_resync(*_args):
    ctx = bpy.context
    if ctx.window_manager is None:
        return
    try:
        rebuild_mirror(ctx)
    except Exception as e:
        print(f"IOPS selection sets: mirror resync failed: {e}")


@persistent
def _iops_ss_force_resync(*_args):
    tag_mirror_dirty()
    _iops_ss_resync()


class IOPS_OT_SSRefresh(bpy.types.Operator):
    """Rebuild the selection sets list from mesh/scene data"""
    bl_idname = "iops.ss_refresh"
    bl_label = "Refresh Selection Sets"

    def execute(self, context):
        rebuild_mirror(context, force=True)
        return {"FINISHED"}


class IOPS_UL_SelectionSets(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname):
        row = layout.row(align=True)
        row.prop(item, "checked", text="")
        row.prop(item, "name", text="", emboss=False)
        icons = {"V": "VERTEXSEL", "E": "EDGESEL", "F": "FACESEL",
                 "OBJ": "OBJECT_DATA"}
        flags = ["OBJ"] if item.flags == "OBJ" else list(item.flags)
        for f in flags:
            row.label(text="", icon=icons[f])
        stale = item.count == 0 or item.count < item.total
        text = (str(item.count) if item.flags != "OBJ"
                else f"{item.count}/{item.total}")
        row.label(text=text, icon="ERROR" if stale else "NONE")


class IOPS_PT_SelectionSets_Panel(bpy.types.Panel):
    bl_label = "iOps Selection Sets"
    bl_idname = "IOPS_PT_selection_sets_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "iOps"

    @classmethod
    def poll(cls, context):
        return context.mode in {"OBJECT", "EDIT_MESH"}

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager
        mirror = wm.iops_ss_mirror
        active = (mirror[wm.iops_ss_index].name
                  if 0 <= wm.iops_ss_index < len(mirror) else "")
        checked = [it.name for it in mirror if it.checked]

        row = layout.row()
        row.template_list("IOPS_UL_SelectionSets", "", wm, "iops_ss_mirror",
                          wm, "iops_ss_index", rows=4)
        col = row.column(align=True)
        col.operator("iops.ss_new", text="", icon="ADD")
        sub = col.column(align=True)
        sub.enabled = bool(active)
        sub.operator("iops.ss_delete", text="",
                     icon="REMOVE").set_name = active
        col.separator()
        col.operator("iops.ss_refresh", text="", icon="FILE_REFRESH")

        col = layout.column(align=True)
        row = col.row(align=True)
        row.enabled = bool(active)
        op = row.operator("iops.ss_recall", text="Recall")
        op.set_name = active
        row.operator("iops.ss_replace", text="Replace").set_name = active
        row = col.row(align=True)
        row.enabled = bool(active)
        op = row.operator("iops.ss_modify", text="Add Sel")
        op.set_name, op.add = active, True
        op = row.operator("iops.ss_modify", text="Remove Sel")
        op.set_name, op.add = active, False

        col = layout.column(align=True)
        row = col.row(align=True)
        row.enabled = len(checked) >= 2
        op = row.operator("iops.ss_union", text="Union → New")
        op.set_names, op.target = ";".join(checked), ""
        row = col.row(align=True)
        row.enabled = len(checked) >= 1 and bool(active)
        op = row.operator("iops.ss_union", text="Union → Active")
        op.set_names, op.target = ";".join(checked), active
        row = col.row(align=True)
        if len(checked) == 2:
            row.operator("iops.ss_difference",
                         text="Difference (checked)").set_names = \
                ";".join(checked)
        else:
            row.enabled = bool(active)
            op = row.operator("iops.ss_difference",
                              text="Difference vs Selection")
            op.set_names = active

        layout.operator("iops.ss_delete_all", text="Delete All",
                        icon="TRASH")


_HANDLERS = (
    (bpy.app.handlers.depsgraph_update_post, _iops_ss_resync),
    (bpy.app.handlers.undo_post, _iops_ss_force_resync),
    (bpy.app.handlers.redo_post, _iops_ss_force_resync),
    (bpy.app.handlers.load_post, _iops_ss_force_resync),
)


def register_selection_sets_ui():
    bpy.types.WindowManager.iops_ss_mirror = bpy.props.CollectionProperty(
        type=IOPS_SS_MirrorItem)
    bpy.types.WindowManager.iops_ss_index = bpy.props.IntProperty(default=0)
    ss._tag_mirror_dirty = tag_mirror_dirty
    for handler_list, fn in _HANDLERS:
        if fn not in handler_list:
            handler_list.append(fn)


def unregister_selection_sets_ui():
    for handler_list, fn in _HANDLERS:
        if fn in handler_list:
            handler_list.remove(fn)
    ss._tag_mirror_dirty = lambda: None
    for attr in ("iops_ss_mirror", "iops_ss_index"):
        try:
            delattr(bpy.types.WindowManager, attr)
        except AttributeError:
            pass
```

- [ ] **Step 2: Register in `__init__.py`**

Import near the other `ui.*` imports:

```python
from .ui.iops_selection_sets_panel import (
    IOPS_SS_MirrorItem,
    IOPS_OT_SSRefresh,
    IOPS_UL_SelectionSets,
    IOPS_PT_SelectionSets_Panel,
    register_selection_sets_ui,
    unregister_selection_sets_ui,
)
```

Add the four classes to `classes` (`IOPS_SS_MirrorItem` before the rest —
CollectionProperty target). Call `register_selection_sets_ui()` in
`register()` after `reg_cls()` (next to `register_slot_props()`), and
`unregister_selection_sets_ui()` early in `unregister()`.

- [ ] **Step 3: MCP smoke test**

Reload addon, then:

```python
import bpy
bpy.ops.wm.read_homefile(use_empty=False)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.iops.ss_new(set_name="objs")
from InteractionOps.ui.iops_selection_sets_panel import rebuild_mirror
rebuild_mirror(bpy.context, force=True)
wm = bpy.context.window_manager
print([(i.name, i.flags, i.count, i.total) for i in wm.iops_ss_mirror])
# expect [('objs', 'OBJ', 1, 1)]
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.iops.ss_new(set_name="verts")
rebuild_mirror(bpy.context, force=True)
print([(i.name, i.flags, i.count) for i in wm.iops_ss_mirror])
# expect [('verts', 'V', 8)] — edit mode shows mesh sets only
# rename write-through
wm.iops_ss_mirror[0].name = "renamed"
import bmesh
from InteractionOps.operators.mesh_selection_sets import bm_list_sets
bm = bmesh.from_edit_mesh(bpy.context.object.data)
print(bm_list_sets(bm))   # expect {'renamed': 'V'}
# undo resync: delete set, undo, mirror should show it again
bpy.ops.iops.ss_delete(set_name="renamed")
with bpy.context.temp_override(window=bpy.context.window_manager.windows[0]):
    bpy.ops.ed.undo()
rebuild_mirror(bpy.context, force=True)
print([i.name for i in wm.iops_ss_mirror])  # expect ['renamed']
bpy.ops.object.mode_set(mode='OBJECT')
```

Expected: matches comments. Also eyeball the panel in the running Blender
(N-panel → iOps tab) — list renders, buttons enabled/disabled sensibly.

- [ ] **Step 4: Commit**

```bash
git add ui/iops_selection_sets_panel.py __init__.py
git commit -m "feat(selection-sets): UIList panel over handler-synced WM mirror"
```

---

### Task 6: Header integration + prefs toggle

**Files:**
- Modify: `ui/iops_selection_sets_panel.py` (menu + header draw fn)
- Modify: `prefs/addon_preferences.py` (BoolProperty + draw row)
- Modify: `__init__.py` (register menu class, header append/remove)

**Interfaces:**
- Consumes: mirror + operators from Tasks 2–5.
- Produces: `IOPS_MT_SelectionSets(Menu)`, `draw_iops_ss_header(self, context)`, pref `iops_ss_header: BoolProperty`.

- [ ] **Step 1: Menu + header draw fn**

Append to `ui/iops_selection_sets_panel.py`:

```python
class IOPS_MT_SelectionSets(bpy.types.Menu):
    bl_idname = "IOPS_MT_selection_sets"
    bl_label = "Selection Sets"

    def draw(self, context):
        layout = self.layout
        mirror = context.window_manager.iops_ss_mirror
        if not mirror:
            layout.label(text="No selection sets", icon="INFO")
            return
        for item in mirror:
            op = layout.operator("iops.ss_recall", text=item.name)
            op.set_name = item.name


def draw_iops_ss_header(self, context):
    if context.mode not in {"OBJECT", "EDIT_MESH"}:
        return
    prefs = context.preferences.addons["InteractionOps"].preferences
    if not prefs.iops_ss_header:
        return
    layout = self.layout
    row = layout.row(align=True)
    row.menu("IOPS_MT_selection_sets", text="", icon="GROUP_VERTEX")
    row.operator("iops.ss_new", text="", icon="ADD")
    wm = context.window_manager
    mirror = wm.iops_ss_mirror
    active = (mirror[wm.iops_ss_index].name
              if 0 <= wm.iops_ss_index < len(mirror) else "")
    sub = row.row(align=True)
    sub.enabled = bool(active)
    op = sub.operator("iops.ss_modify", text="", icon="SELECT_EXTEND")
    op.set_name, op.add = active, True
    op = sub.operator("iops.ss_modify", text="", icon="SELECT_SUBTRACT")
    op.set_name, op.add = active, False
    sub.operator("iops.ss_replace", text="",
                 icon="FILE_REFRESH").set_name = active
```

Note: the recall menu entries document Shift/Ctrl via the operator docstring
tooltip (already written in Task 2).

- [ ] **Step 2: Pref toggle**

In `prefs/addon_preferences.py`, next to `iops_stat: BoolProperty(` (~line
118), add:

```python
iops_ss_header: BoolProperty(
    name="Selection Sets in 3D View Header",
    description="Show the Selection Sets dropdown and buttons in the 3D View header",
    default=True,
)
```

In the prefs `draw()` where `body.prop(self, "iops_stat", toggle=True)` is
drawn (~line 871), add below it:

```python
body.prop(self, "iops_ss_header", toggle=True)
```

- [ ] **Step 3: Wire the header in `__init__.py`**

Extend the ui import with `IOPS_MT_SelectionSets, draw_iops_ss_header`; add
`IOPS_MT_SelectionSets` to `classes`. In `register()` next to the other
`.append(...)` calls: `bpy.types.VIEW3D_HT_header.append(draw_iops_ss_header)`.
In `unregister()`: `bpy.types.VIEW3D_HT_header.remove(draw_iops_ss_header)`
(same try/except style as the neighbors).

- [ ] **Step 4: MCP smoke test**

Reload addon, then:

```python
import bpy
prefs = bpy.context.preferences.addons["InteractionOps"].preferences
print("pref exists:", prefs.iops_ss_header)
print("menu registered:", hasattr(bpy.types, "IOPS_MT_selection_sets"))
import InteractionOps
from InteractionOps.ui.iops_selection_sets_panel import draw_iops_ss_header
print("header hooked:",
      any(fn is draw_iops_ss_header
          for fn in bpy.types.VIEW3D_HT_header._dyn_ui_initialize()))
```

Expected: `True / True / True`. Visually confirm the dropdown + 4 buttons in
the 3D View header, and that toggling the pref off hides them.

- [ ] **Step 5: Commit**

```bash
git add ui/iops_selection_sets_panel.py prefs/addon_preferences.py __init__.py
git commit -m "feat(selection-sets): 3D View header dropdown and prefs toggle"
```

---

### Task 7: Integration smoke matrix + docs

**Files:**
- Create: `docs/operators/op_selection_sets.md`
- Modify: `mkdocs.yml` (nav entry)

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Full MCP smoke matrix**

Reload addon; run each scenario, all must pass without tracebacks:

1. **Topology robustness:** cube in edit, save all 8 verts as `all`; delete 4
   verts; recall `all` → 4 remaining verts selected;
   `bm_set_count` → 4. Save empty selection impossible (poll), but a set
   emptied by deletion shows `count 0` in the mirror after
   `rebuild_mirror(force=True)`.
2. **Undo:** create set, `ed.undo` (with window override), set gone from
   `bm_list_sets`; `ed.redo`, set back.
3. **Multi-object edit:** two cubes, both in edit mode, selection on both,
   `ss_new` writes to both meshes (`bm_list_sets` on each); recall selects on
   both; a set present on only one mesh recalls without error.
4. **Mode mixing:** sets created in edit mode invisible in the object-mode
   mirror and vice versa; operators poll correctly in each mode.
5. **Select-mode restore:** save a face set (face mode), switch to vert mode,
   recall with `action='SET'` → `mesh_select_mode` back to face.
6. **pytest:** `python -m pytest tests -q` — full suite green.

- [ ] **Step 2: Docs page**

Create `docs/operators/op_selection_sets.md` — follow the structure of an
existing operator page (check `docs/operators/op_iops.md` for heading/tone),
covering: what selection sets are, storage model (hidden attributes /
scene list, what survives undo and topology edits), the panel, the header
row, Shift/Ctrl recall modifiers, union/difference via checkboxes, and the
stale-set warning. Add to `mkdocs.yml` nav under an appropriate Operators
subsection (e.g. `- Selection Sets: operators/op_selection_sets.md` next to
the mesh tools).

- [ ] **Step 3: Commit**

```bash
git add docs/operators/op_selection_sets.md mkdocs.yml
git commit -m "docs(selection-sets): user docs and smoke-matrix sign-off"
```
