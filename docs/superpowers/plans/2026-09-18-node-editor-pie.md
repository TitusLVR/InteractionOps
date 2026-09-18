# Node Editor Contextual Pie Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A pie menu in the Geometry Nodes and Shader editors whose contents depend on the active node's exact type, where picking a slot spawns the node already wired to the active node and hands it to a grab.

**Architecture:** Pure logic (rule merge, socket compatibility, spawn planning) lives in `utils/node_pie_*.py` with no `bpy` import so pytest can cover it; the `bpy` side (`operators/node_pie/`, `ui/iops_pie_node.py`, `prefs/node_pie_prefs.py`) applies plans and draws UI but makes no decisions. Rules are shipped as Python data and overridden per node type by user JSON under `scripts/presets/IOPS/node_pies/`.

**Tech Stack:** Blender 5.2.2 Python API (`bpy`), pytest (headless, bpy-free), JSON preset files.

**Spec:** `docs/superpowers/specs/2026-09-18-node-editor-contextual-pie-design.md`

## Global Constraints

- Target Blender: 5.2.2 LTS. `NodeClass.poll(ntree)` **must not** be used to decide whether a node type is valid in a tree — it returns `False` for `ShaderNodeMath`, `ShaderNodeMix`, `ShaderNodeValToRGB`, `NodeReroute`, `NodeGroupInput`, `NodeFrame` in a `GeometryNodeTree`, all of which create fine. Probe by attempting `nodes.new()` in a scratch node group and catching `RuntimeError`.
- `node.dimensions` is `(0.0, 0.0)` until the node has been drawn. Only `node.width` may be used in placement math.
- `links.new()` never raises on a type mismatch — Blender flags the link invalid afterwards. Socket compatibility logic decides which link is *good*, not which is *possible*.
- Pure modules (`utils/node_pie_rules.py`, `utils/node_pie_planner.py`) must not `import bpy`, directly or transitively. `tests/conftest.py` deliberately prevents the addon `__init__.py` from being imported; a stray `bpy` import breaks the whole test run.
- Pie slot order is W, E, S, N, NW, NE, SW, SE — list indices 0-7 in that order.
- Draw callbacks must never raise. Bad data degrades to a dropped slot plus a one-time console warning.
- Hotkey rules for this addon: an operator opts in with `is_bindable = True`; a shipped default binding goes in `prefs/hotkeys_default.py`; `unregister` must only ever touch addon-owned keymaps, never the user keyconfig.
- Python style: follow `ruff.toml` in the repo root; match the surrounding code's docstring and comment density.
- Commit messages end with the two attribution lines used on this branch (see existing commits on `node-editor-pie`).
- Branch: `node-editor-pie`. Per repo convention the feature ends as **one squashed commit** — task commits are checkpoints and get soft-reset into a single commit at the end (Task 10).

---

### Task 1: Pure socket compatibility

**Files:**
- Create: `utils/node_pie_planner.py`
- Test: `tests/test_node_pie_planner.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `SocketDesc`, `NodeDesc`, `LinkDesc` dataclasses; `is_compatible(a: str, b: str) -> bool`; `IMPLICIT_GROUP: frozenset[str]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_node_pie_planner.py
from utils import node_pie_planner as pl


def test_exact_types_are_compatible_with_themselves():
    for t in ("GEOMETRY", "SHADER", "OBJECT", "COLLECTION", "MATERIAL",
              "IMAGE", "STRING", "MENU", "TEXTURE", "MATRIX"):
        assert pl.is_compatible(t, t)


def test_exact_only_types_do_not_cross_link():
    assert not pl.is_compatible("GEOMETRY", "SHADER")
    assert not pl.is_compatible("SHADER", "VALUE")
    assert not pl.is_compatible("OBJECT", "COLLECTION")


def test_implicit_group_is_mutually_compatible():
    group = ("VALUE", "INT", "BOOLEAN", "VECTOR", "ROTATION", "RGBA")
    for a in group:
        for b in group:
            assert pl.is_compatible(a, b), (a, b)


def test_implicit_group_does_not_reach_exact_only_types():
    assert not pl.is_compatible("VALUE", "GEOMETRY")
    assert not pl.is_compatible("RGBA", "SHADER")


def test_unknown_socket_type_is_only_self_compatible():
    assert pl.is_compatible("CUSTOM", "CUSTOM")
    assert not pl.is_compatible("CUSTOM", "VALUE")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_node_pie_planner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'utils.node_pie_planner'`

- [ ] **Step 3: Write minimal implementation**

```python
# utils/node_pie_planner.py
"""Pure spawn planning for the node-editor pie (no bpy) so pytest can cover it.

Everything that can be wrong — which sockets to link, what to splice, where to
put the node — is decided here over plain dataclasses. The bpy side in
`operators/node_pie/ops.py` only applies the result.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Socket types Blender implicitly converts between. Anything outside this set
# links only to its own type. Values are `NodeSocket.type` enum identifiers.
IMPLICIT_GROUP = frozenset(
    {"VALUE", "INT", "BOOLEAN", "VECTOR", "ROTATION", "RGBA"}
)


@dataclass(frozen=True)
class SocketDesc:
    """One socket, stripped to what planning needs."""
    name: str
    type: str
    index: int
    enabled: bool = True
    hide: bool = False


@dataclass(frozen=True)
class NodeDesc:
    """One node, stripped to what planning needs."""
    bl_idname: str
    location: tuple[float, float] = (0.0, 0.0)
    width: float = 140.0
    inputs: tuple[SocketDesc, ...] = field(default_factory=tuple)
    outputs: tuple[SocketDesc, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class LinkDesc:
    """One existing link, addressed by node + socket index."""
    from_node: str
    from_socket: int
    to_node: str
    to_socket: int
    to_socket_type: str
    to_node_location: tuple[float, float] = (0.0, 0.0)


def is_compatible(a: str, b: str) -> bool:
    """True when a link between socket types `a` and `b` is meaningful."""
    if a == b:
        return True
    return a in IMPLICIT_GROUP and b in IMPLICIT_GROUP
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_node_pie_planner.py -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Commit**

```bash
git add utils/node_pie_planner.py tests/test_node_pie_planner.py
git commit -m "feat(node-pie): socket compatibility core"
```

---

### Task 2: Source and target socket selection

**Files:**
- Modify: `utils/node_pie_planner.py`
- Test: `tests/test_node_pie_planner.py`

**Interfaces:**
- Consumes: `SocketDesc`, `NodeDesc`, `is_compatible` from Task 1.
- Produces: `pick_source(node: NodeDesc, from_socket: str | int | None) -> SocketDesc | None`; `pick_target(node: NodeDesc, source_type: str) -> SocketDesc | None`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_node_pie_planner.py

def _geo_node(idname="GeometryNodeSetPosition"):
    return pl.NodeDesc(
        bl_idname=idname,
        inputs=(
            pl.SocketDesc("Geometry", "GEOMETRY", 0),
            pl.SocketDesc("Selection", "BOOLEAN", 1),
            pl.SocketDesc("Position", "VECTOR", 2),
            pl.SocketDesc("Offset", "VECTOR", 3),
        ),
        outputs=(pl.SocketDesc("Geometry", "GEOMETRY", 0),),
    )


def test_pick_source_defaults_to_first_visible_output():
    node = pl.NodeDesc(
        "GeometryNodeRaycast",
        outputs=(
            pl.SocketDesc("Is Hit", "BOOLEAN", 0, enabled=False),
            pl.SocketDesc("Hit Position", "VECTOR", 1),
        ),
    )
    assert pl.pick_source(node, None).name == "Hit Position"


def test_pick_source_skips_hidden_outputs():
    node = pl.NodeDesc(
        "N",
        outputs=(
            pl.SocketDesc("A", "VALUE", 0, hide=True),
            pl.SocketDesc("B", "VALUE", 1),
        ),
    )
    assert pl.pick_source(node, None).name == "B"


def test_pick_source_honours_from_socket_by_name_and_index():
    node = pl.NodeDesc(
        "N",
        outputs=(pl.SocketDesc("A", "VALUE", 0), pl.SocketDesc("B", "VECTOR", 1)),
    )
    assert pl.pick_source(node, "B").index == 1
    assert pl.pick_source(node, 1).index == 1


def test_pick_source_falls_back_when_from_socket_is_unknown():
    node = pl.NodeDesc("N", outputs=(pl.SocketDesc("A", "VALUE", 0),))
    assert pl.pick_source(node, "Nope").name == "A"


def test_pick_source_returns_none_without_usable_outputs():
    assert pl.pick_source(pl.NodeDesc("N"), None) is None


def test_pick_target_takes_first_compatible_input():
    assert pl.pick_target(_geo_node(), "GEOMETRY").index == 0
    assert pl.pick_target(_geo_node(), "VECTOR").index == 1  # BOOLEAN, implicit


def test_pick_target_skips_disabled_inputs():
    node = pl.NodeDesc(
        "N",
        inputs=(
            pl.SocketDesc("A", "GEOMETRY", 0, enabled=False),
            pl.SocketDesc("B", "GEOMETRY", 1),
        ),
    )
    assert pl.pick_target(node, "GEOMETRY").index == 1


def test_pick_target_returns_none_when_nothing_is_compatible():
    assert pl.pick_target(_geo_node(), "SHADER") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_node_pie_planner.py -v`
Expected: FAIL — `AttributeError: module 'utils.node_pie_planner' has no attribute 'pick_source'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to utils/node_pie_planner.py

def _usable(sockets):
    return [s for s in sockets if s.enabled and not s.hide]


def pick_source(node: NodeDesc, from_socket: str | int | None) -> SocketDesc | None:
    """Output socket to link from.

    `from_socket` (a rule entry's optional override) may be a socket name or an
    index; an override that does not resolve falls back to the default pick
    rather than failing, so a rule written against another Blender version
    still spawns something useful.
    """
    usable = _usable(node.outputs)
    if not usable:
        return None
    if from_socket is not None:
        for s in usable:
            if s.name == from_socket or s.index == from_socket:
                return s
    return usable[0]


def pick_target(node: NodeDesc, source_type: str) -> SocketDesc | None:
    """First input on the spawned node that `source_type` can meaningfully feed."""
    for s in _usable(node.inputs):
        if is_compatible(source_type, s.type):
            return s
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_node_pie_planner.py -v`
Expected: PASS, 13 tests

- [ ] **Step 5: Commit**

```bash
git add utils/node_pie_planner.py tests/test_node_pie_planner.py
git commit -m "feat(node-pie): source/target socket selection"
```

---

### Task 3: Spawn plan — placement and splice

**Files:**
- Modify: `utils/node_pie_planner.py`
- Test: `tests/test_node_pie_planner.py`

**Interfaces:**
- Consumes: everything from Tasks 1-2.
- Produces: `SpawnPlan` dataclass with fields `location: tuple[float, float]`, `links_to_add: tuple[tuple[int, str, int], ...]` (each `(from_socket_index, to_node_key, to_socket_index)` where `to_node_key` is `"NEW"` for the spawned node or an existing node's name), `links_to_remove: tuple[LinkDesc, ...]`, `warning: str | None`; and `plan_spawn(active: NodeDesc, new: NodeDesc, downstream: tuple[LinkDesc, ...], from_socket=None) -> SpawnPlan`.
- Link tuples are directional: `("ACTIVE", out_index, "NEW", in_index)`. Use the 4-tuple form `(from_node_key, from_socket_index, to_node_key, to_socket_index)`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_node_pie_planner.py

GAP = 40.0


def test_plain_spawn_places_right_of_active_and_links_once():
    active = pl.NodeDesc("GeometryNodeMeshCube", location=(0.0, 0.0), width=140.0,
                         outputs=(pl.SocketDesc("Mesh", "GEOMETRY", 0),))
    plan = pl.plan_spawn(active, _geo_node(), downstream=())
    assert plan.location == (180.0, 0.0)
    assert plan.links_to_add == (("ACTIVE", 0, "NEW", 0),)
    assert plan.links_to_remove == ()
    assert plan.warning is None


def test_spawn_without_compatible_input_still_places_and_warns():
    active = pl.NodeDesc("ShaderNodeBsdfPrincipled", location=(0.0, 0.0),
                         outputs=(pl.SocketDesc("BSDF", "SHADER", 0),))
    plan = pl.plan_spawn(active, _geo_node(), downstream=())
    assert plan.links_to_add == ()
    assert plan.location == (180.0, 0.0)
    assert "no compatible input" in plan.warning


def test_splice_rewires_every_downstream_consumer():
    active = pl.NodeDesc("GeometryNodeMeshCube", location=(0.0, 0.0),
                         outputs=(pl.SocketDesc("Mesh", "GEOMETRY", 0),))
    downstream = (
        pl.LinkDesc("GeometryNodeMeshCube", 0, "Join", 0, "GEOMETRY", (900.0, 0.0)),
        pl.LinkDesc("GeometryNodeMeshCube", 0, "Output", 0, "GEOMETRY", (1200.0, 0.0)),
    )
    plan = pl.plan_spawn(active, _geo_node(), downstream=downstream)
    assert ("ACTIVE", 0, "NEW", 0) in plan.links_to_add
    assert ("NEW", 0, "Join", 0) in plan.links_to_add
    assert ("NEW", 0, "Output", 0) in plan.links_to_add
    assert set(plan.links_to_remove) == set(downstream)


def test_splice_places_midway_when_there_is_room():
    active = pl.NodeDesc("GeometryNodeMeshCube", location=(0.0, 0.0), width=140.0,
                         outputs=(pl.SocketDesc("Mesh", "GEOMETRY", 0),))
    downstream = (
        pl.LinkDesc("GeometryNodeMeshCube", 0, "Join", 0, "GEOMETRY", (900.0, 0.0)),
    )
    plan = pl.plan_spawn(active, _geo_node(), downstream=downstream)
    assert plan.location == (450.0, 0.0)


def test_splice_uses_plain_offset_when_downstream_is_close():
    active = pl.NodeDesc("GeometryNodeMeshCube", location=(0.0, 0.0), width=140.0,
                         outputs=(pl.SocketDesc("Mesh", "GEOMETRY", 0),))
    downstream = (
        pl.LinkDesc("GeometryNodeMeshCube", 0, "Join", 0, "GEOMETRY", (200.0, 0.0)),
    )
    plan = pl.plan_spawn(active, _geo_node(), downstream=downstream)
    assert plan.location == (180.0, 0.0)


def test_splice_picks_output_matching_the_downstream_socket_type():
    active = pl.NodeDesc("A", location=(0.0, 0.0),
                         outputs=(pl.SocketDesc("Out", "VALUE", 0),))
    new = pl.NodeDesc(
        "ShaderNodeSeparateXYZ",
        inputs=(pl.SocketDesc("Vector", "VECTOR", 0),),
        outputs=(pl.SocketDesc("X", "VALUE", 0), pl.SocketDesc("Y", "VALUE", 1)),
    )
    downstream = (pl.LinkDesc("A", 0, "Math", 1, "VALUE", (900.0, 0.0)),)
    plan = pl.plan_spawn(active, new, downstream=downstream)
    assert ("NEW", 0, "Math", 1) in plan.links_to_add


def test_plan_without_usable_output_on_active_still_places_the_node():
    active = pl.NodeDesc("GeometryNodeGroupOutput", location=(0.0, 0.0))
    plan = pl.plan_spawn(active, _geo_node(), downstream=())
    assert plan.links_to_add == ()
    assert plan.location == (180.0, 0.0)
    assert "no output" in plan.warning
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_node_pie_planner.py -v`
Expected: FAIL — `AttributeError: module 'utils.node_pie_planner' has no attribute 'plan_spawn'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to utils/node_pie_planner.py

#: Horizontal gap between the active node's right edge and the new node.
SPAWN_GAP = 40.0
#: Extra clearance required before a spliced node is placed midway.
SPLICE_CLEARANCE = 80.0


@dataclass(frozen=True)
class SpawnPlan:
    """Everything the bpy side needs to apply, and nothing it must decide."""
    location: tuple[float, float]
    links_to_add: tuple[tuple[str, int, str, int], ...] = ()
    links_to_remove: tuple[LinkDesc, ...] = ()
    warning: str | None = None


def _splice_output(new: NodeDesc, to_socket_type: str) -> SocketDesc | None:
    usable = _usable(new.outputs)
    if not usable:
        return None
    for s in usable:
        if s.type == to_socket_type:
            return s
    return usable[0]


def plan_spawn(active: NodeDesc, new: NodeDesc,
               downstream: tuple[LinkDesc, ...] = (),
               from_socket: str | int | None = None) -> SpawnPlan:
    """Decide where the new node goes and how it is wired.

    `downstream` is every existing link leaving the active node; only those
    leaving the chosen source socket are spliced. The node is always placed,
    even when nothing can be linked — a pie press that produces no node at all
    reads as a dead key.
    """
    plain = (active.location[0] + active.width + SPAWN_GAP, active.location[1])

    source = pick_source(active, from_socket)
    if source is None:
        return SpawnPlan(plain, warning="active node has no output to link from")

    target = pick_target(new, source.type)
    spliced = tuple(l for l in downstream if l.from_socket == source.index)

    if target is None:
        return SpawnPlan(
            plain,
            warning=f"{new.bl_idname} has no compatible input for {source.type}",
        )

    links = [("ACTIVE", source.index, "NEW", target.index)]
    for link in spliced:
        out = _splice_output(new, link.to_socket_type)
        if out is not None:
            links.append(("NEW", out.index, link.to_node, link.to_socket))

    location = plain
    if spliced:
        nearest = min(l.to_node_location[0] for l in spliced)
        needed = active.location[0] + active.width + new.width + SPLICE_CLEARANCE
        if nearest >= needed:
            location = ((active.location[0] + nearest) / 2.0, active.location[1])

    return SpawnPlan(location, tuple(links), spliced, None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_node_pie_planner.py -v`
Expected: PASS, 20 tests

- [ ] **Step 5: Commit**

```bash
git add utils/node_pie_planner.py tests/test_node_pie_planner.py
git commit -m "feat(node-pie): spawn plan with placement and splice"
```

---

### Task 4: Rule store — schema, merge, degradation

**Files:**
- Create: `utils/node_pie_rules.py`
- Test: `tests/test_node_pie_rules.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `SCHEMA_VERSION: int`; `FALLBACK_KEY = "__fallback__"`; `SLOT_COUNT = 8`; `SLOT_LABELS: tuple[str, ...]`; `normalise_rule(rule: dict) -> list[dict | None]`; `merge(defaults: dict, user: dict) -> dict`; `load_document(text: str, defaults: dict) -> tuple[dict, list[str]]`; `get_entries(rules: dict, node_idname: str) -> list[dict | None]`.
- Shipped default tables are added in Task 8; this task ships `DEFAULTS = {"GeometryNodeTree": {}, "ShaderNodeTree": {}}` so the merge logic has a home.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_node_pie_rules.py
import json

from utils import node_pie_rules as nr


def _entry(idname):
    return {"node": idname}


def test_slot_labels_are_pie_draw_order():
    assert nr.SLOT_LABELS == ("W", "E", "S", "N", "NW", "NE", "SW", "SE")


def test_normalise_pads_short_slot_lists_to_eight():
    slots = nr.normalise_rule({"slots": [_entry("A"), _entry("B")]})
    assert len(slots) == nr.SLOT_COUNT
    assert slots[0] == {"node": "A"}
    assert slots[2:] == [None] * 6


def test_normalise_truncates_overlong_slot_lists():
    slots = nr.normalise_rule({"slots": [_entry("A")] * 12})
    assert len(slots) == nr.SLOT_COUNT


def test_normalise_drops_entries_without_a_node_field():
    slots = nr.normalise_rule({"slots": [{"text": "oops"}, _entry("B")]})
    assert slots[0] is None
    assert slots[1] == {"node": "B"}


def test_user_rule_replaces_shipped_rule_wholesale():
    defaults = {"GeometryNodeMeshCube": {"slots": [_entry("A"), _entry("B")]}}
    user = {"GeometryNodeMeshCube": {"slots": [_entry("Z")]}}
    merged = nr.merge(defaults, user)
    slots = nr.get_entries(merged, "GeometryNodeMeshCube")
    assert slots[0] == {"node": "Z"}
    assert slots[1] is None


def test_user_may_add_rules_for_unknown_node_types():
    merged = nr.merge({}, {"GeometryNodeFooBar": {"slots": [_entry("Z")]}})
    assert nr.get_entries(merged, "GeometryNodeFooBar")[0] == {"node": "Z"}


def test_empty_slot_list_forces_the_fallback():
    merged = nr.merge({"X": {"slots": [_entry("A")]}}, {"X": {"slots": []}})
    assert nr.get_entries(merged, "X") is None


def test_unknown_node_type_returns_none():
    assert nr.get_entries({}, "GeometryNodeNope") is None


def test_load_document_applies_user_rules_over_defaults():
    defaults = {"X": {"slots": [_entry("A")]}}
    text = json.dumps({"version": nr.SCHEMA_VERSION, "tree_type": "GeometryNodeTree",
                       "rules": {"X": {"slots": [_entry("Z")]}}})
    rules, warnings = nr.load_document(text, defaults)
    assert nr.get_entries(rules, "X")[0] == {"node": "Z"}
    assert warnings == []


def test_load_document_reports_a_newer_schema_but_still_loads():
    defaults = {}
    text = json.dumps({"version": nr.SCHEMA_VERSION + 5,
                       "rules": {"X": {"slots": [_entry("Z")]}}})
    rules, warnings = nr.load_document(text, defaults)
    assert nr.get_entries(rules, "X")[0] == {"node": "Z"}
    assert any("version" in w for w in warnings)


def test_malformed_json_degrades_to_defaults_with_a_warning():
    defaults = {"X": {"slots": [_entry("A")]}}
    rules, warnings = nr.load_document("{not json", defaults)
    assert nr.get_entries(rules, "X")[0] == {"node": "A"}
    assert warnings


def test_empty_file_degrades_to_defaults_without_crashing():
    defaults = {"X": {"slots": [_entry("A")]}}
    rules, warnings = nr.load_document("   ", defaults)
    assert nr.get_entries(rules, "X")[0] == {"node": "A"}


def test_non_dict_document_degrades_to_defaults():
    defaults = {"X": {"slots": [_entry("A")]}}
    rules, warnings = nr.load_document("[1, 2, 3]", defaults)
    assert nr.get_entries(rules, "X")[0] == {"node": "A"}
    assert warnings
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_node_pie_rules.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'utils.node_pie_rules'`

- [ ] **Step 3: Write minimal implementation**

```python
# utils/node_pie_rules.py
"""Rule store for the node-editor pie: shipped defaults, user overrides, merge.

Pure data handling, no bpy, so pytest covers the parts that can be wrong. The
bpy side (`operators/node_pie/store.py`) only supplies file contents and
surfaces the warnings this module returns.
"""
from __future__ import annotations

import json

SCHEMA_VERSION = 1
SLOT_COUNT = 8
#: Blender's pie draw order; `slots` is indexed in this order.
SLOT_LABELS = ("W", "E", "S", "N", "NW", "NE", "SW", "SE")
FALLBACK_KEY = "__fallback__"

# Filled in by the shipped default tables; see `DEFAULTS` at the bottom.
DEFAULTS: dict[str, dict] = {"GeometryNodeTree": {}, "ShaderNodeTree": {}}


def normalise_rule(rule) -> list[dict | None]:
    """Return a rule's slots as exactly SLOT_COUNT entries, padded with None.

    Entries without a `node` field are dropped to None rather than raising —
    this data reaches a draw callback, where an exception would break the pie.
    """
    if not isinstance(rule, dict):
        return [None] * SLOT_COUNT
    slots = rule.get("slots")
    if not isinstance(slots, list):
        return [None] * SLOT_COUNT
    out: list[dict | None] = []
    for entry in slots[:SLOT_COUNT]:
        if isinstance(entry, dict) and isinstance(entry.get("node"), str):
            out.append(entry)
        else:
            out.append(None)
    return out + [None] * (SLOT_COUNT - len(out))


def merge(defaults: dict, user: dict) -> dict:
    """User rules replace shipped rules per node type, wholesale.

    Whole-entry replacement (rather than per-slot) means an addon update can
    never half-overwrite a rule the user edited.
    """
    merged = dict(defaults)
    if isinstance(user, dict):
        for key, rule in user.items():
            if isinstance(key, str) and isinstance(rule, dict):
                merged[key] = rule
    return merged


def get_entries(rules: dict, node_idname: str) -> list[dict | None] | None:
    """Slots for `node_idname`, or None when the fallback pie should be drawn."""
    rule = rules.get(node_idname)
    if rule is None:
        return None
    slots = normalise_rule(rule)
    if not any(slots):
        return None
    return slots


def load_document(text: str, defaults: dict) -> tuple[dict, list[str]]:
    """Parse a user preset file and layer it over `defaults`.

    Returns `(rules, warnings)`. Any failure degrades to the shipped defaults
    with a warning; the user never ends up with a dead pie because a file was
    hand-edited badly.
    """
    warnings: list[str] = []
    if not text or not text.strip():
        return dict(defaults), warnings
    try:
        doc = json.loads(text)
    except (ValueError, UnicodeDecodeError) as exc:
        return dict(defaults), [f"node pie preset is not valid JSON: {exc}"]
    if not isinstance(doc, dict):
        return dict(defaults), ["node pie preset is not a JSON object"]
    version = doc.get("version", SCHEMA_VERSION)
    if isinstance(version, int) and version > SCHEMA_VERSION:
        warnings.append(
            f"node pie preset version {version} is newer than supported "
            f"{SCHEMA_VERSION}; loading anyway"
        )
    rules = doc.get("rules")
    if not isinstance(rules, dict):
        warnings.append("node pie preset has no 'rules' object")
        return dict(defaults), warnings
    return merge(defaults, rules), warnings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_node_pie_rules.py -v`
Expected: PASS, 13 tests

- [ ] **Step 5: Commit**

```bash
git add utils/node_pie_rules.py tests/test_node_pie_rules.py
git commit -m "feat(node-pie): rule store merge and degradation"
```

---

### Task 5: bpy store and node-type catalog

**Files:**
- Create: `operators/node_pie/__init__.py`, `operators/node_pie/store.py`, `operators/node_pie/catalog.py`
- Test: manual, inside Blender (headless coverage of the logic already exists from Task 4)

**Interfaces:**
- Consumes: `utils.node_pie_rules` (Task 4).
- Produces:
  - `store.preset_path(tree_type: str) -> str`
  - `store.rules_for(tree_type: str) -> dict` (loads and caches on first use)
  - `store.get_entries(tree_type: str, node_idname: str) -> list | None`
  - `store.save(tree_type: str, rules: dict) -> str` (returns the written path)
  - `store.reload(tree_type: str | None = None) -> None`
  - `store.warn_once(message: str) -> None`
  - `catalog.items(tree_type: str) -> list[tuple[str, str, str]]`
  - `catalog.clear() -> None`
- Look at `prefs/iops_prefs.py:113-116` for the established preset-path idiom (`bpy.utils.script_path_user()` + `presets/IOPS/...`) and reuse it.

- [ ] **Step 1: Write the module**

```python
# operators/node_pie/store.py
"""File-backed rule store for the node pie.

Reads `scripts/presets/IOPS/node_pies/<tree_type>.json` over the shipped
defaults and caches the result per tree type. All parsing lives in
`utils/node_pie_rules.py`; this module only does files, caching and warnings.
"""
import json
import os

import bpy

from ...utils import node_pie_rules as nr

_cache: dict[str, dict] = {}
_warned: set[str] = set()

TREE_TYPES = ("GeometryNodeTree", "ShaderNodeTree")


def warn_once(message: str) -> None:
    """Print a warning at most once per session — this runs near draw code."""
    if message not in _warned:
        _warned.add(message)
        print(f"IOPS Node Pie: {message}")


def preset_dir() -> str:
    return os.path.join(bpy.utils.script_path_user(), "presets", "IOPS", "node_pies")


def preset_path(tree_type: str) -> str:
    return os.path.join(preset_dir(), f"{tree_type}.json")


def rules_for(tree_type: str) -> dict:
    """Merged rules for a tree type, loaded from disk on first use."""
    if tree_type in _cache:
        return _cache[tree_type]
    defaults = nr.DEFAULTS.get(tree_type, {})
    path = preset_path(tree_type)
    text = ""
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
        except (IOError, UnicodeDecodeError) as exc:
            warn_once(f"could not read {path}: {exc}")
    rules, warnings = nr.load_document(text, defaults)
    for warning in warnings:
        warn_once(warning)
    _cache[tree_type] = rules
    return rules


def get_entries(tree_type: str, node_idname: str):
    return nr.get_entries(rules_for(tree_type), node_idname)


def set_rules(tree_type: str, rules: dict) -> None:
    """Replace the in-memory rules — edits apply to the next pie open."""
    _cache[tree_type] = rules


def save(tree_type: str, rules: dict) -> str:
    """Write the whole tree-type document; returns the path written."""
    path = preset_path(tree_type)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    doc = {"version": nr.SCHEMA_VERSION, "tree_type": tree_type, "rules": rules}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(doc, handle, indent=2)
    set_rules(tree_type, rules)
    return path


def reload(tree_type=None) -> None:
    """Drop cached rules so the next read comes from disk."""
    if tree_type is None:
        _cache.clear()
    else:
        _cache.pop(tree_type, None)
```

```python
# operators/node_pie/catalog.py
"""Which node types can actually be created in a given node tree.

`NodeClass.poll(ntree)` is NOT usable for this: in Blender 5.2.2 it returns
False for ShaderNodeMath, ShaderNodeMix, ShaderNodeValToRGB, NodeReroute,
NodeGroupInput and NodeFrame inside a GeometryNodeTree, all of which create
fine. The only reliable test is to create the node in a scratch tree and see
whether it raises. ~600 node classes, so this runs once per tree type per
session, lazily, and only for the `Add New Node…` search.
"""
import bpy

_cache: dict[str, list[tuple[str, str, str]]] = {}


def clear() -> None:
    _cache.clear()


def _node_classes():
    seen = set()
    stack = list(bpy.types.Node.__subclasses__())
    while stack:
        cls = stack.pop()
        name = getattr(cls, "bl_rna", None) and cls.bl_rna.identifier
        if not name or name in seen:
            continue
        seen.add(name)
        stack.extend(cls.__subclasses__())
        yield name, cls


def items(tree_type: str) -> list[tuple[str, str, str]]:
    """(identifier, label, description) for every node creatable in `tree_type`.

    The returned list is kept in a module-level cache; Blender frees dynamic
    enum item strings that nothing holds a reference to, which crashes mid-draw.
    """
    if tree_type in _cache:
        return _cache[tree_type]

    scratch = bpy.data.node_groups.new("IOPS_NodePie_Probe", tree_type)
    found = []
    try:
        for idname, cls in _node_classes():
            try:
                node = scratch.nodes.new(idname)
            except (RuntimeError, TypeError):
                continue
            label = getattr(cls, "bl_label", "") or idname
            found.append((idname, label, idname))
            scratch.nodes.remove(node)
    finally:
        bpy.data.node_groups.remove(scratch)

    found.sort(key=lambda item: item[1].lower())
    _cache[tree_type] = found
    return found
```

```python
# operators/node_pie/__init__.py
"""Node-editor contextual pie: rule store, catalog and spawn operators."""
from . import catalog, store  # noqa: F401
from .ops import classes as _op_classes

classes = _op_classes
```

- [ ] **Step 2: Verify in Blender**

Run (adjust the Blender path to the Steam install used for this repo):

```bash
blender --background --factory-startup --python-expr "import bpy; bpy.ops.preferences.addon_enable(module='InteractionOps')"
```

Expected: no traceback. (`operators/node_pie/__init__.py` imports `ops`, created in Task 6 — do Step 2 after Task 6 if it runs first in a fresh session; the commit below covers only these three files.)

- [ ] **Step 3: Commit**

```bash
git add operators/node_pie/
git commit -m "feat(node-pie): file-backed rule store and probed node catalog"
```

---

### Task 6: Spawn operator and search picker

**Files:**
- Create: `operators/node_pie/ops.py`
- Modify: `__init__.py` (register the new classes)

**Interfaces:**
- Consumes: `utils.node_pie_planner` (Tasks 1-3), `store` and `catalog` (Task 5).
- Produces: `IOPS_OT_NodeSpawnConnected` (`iops.node_spawn_connected`, props: `node_idname: StringProperty`, `entry_json: StringProperty`), `IOPS_OT_NodePieAddSearch` (`iops.node_pie_add_search`), and `classes` tuple for registration.

- [ ] **Step 1: Write the module**

```python
# operators/node_pie/ops.py
"""Spawn a node already wired to the active one, then hand it to a grab."""
import json

import bpy

from ...utils import node_pie_planner as pl
from . import catalog, store


def _socket_descs(sockets):
    return tuple(
        pl.SocketDesc(name=s.name, type=s.type, index=i,
                      enabled=s.enabled, hide=s.hide)
        for i, s in enumerate(sockets)
    )


def _node_desc(node):
    return pl.NodeDesc(
        bl_idname=node.bl_idname,
        location=tuple(node.location),
        width=node.width,
        inputs=_socket_descs(node.inputs),
        outputs=_socket_descs(node.outputs),
    )


def _downstream(ntree, active):
    out = []
    for link in ntree.links:
        if link.from_node is not active:
            continue
        out.append(pl.LinkDesc(
            from_node=active.name,
            from_socket=list(active.outputs).index(link.from_socket),
            to_node=link.to_node.name,
            to_socket=list(link.to_node.inputs).index(link.to_socket),
            to_socket_type=link.to_socket.type,
            to_node_location=tuple(link.to_node.location),
        ))
    return tuple(out)


def _apply_entry_props(node, entry, report):
    for key, value in (entry.get("props") or {}).items():
        try:
            setattr(node, key, value)
        except (AttributeError, TypeError, ValueError) as exc:
            report({'INFO'}, f"node pie: could not set {key}: {exc}")
    for key, value in (entry.get("inputs") or {}).items():
        socket = None
        if isinstance(key, str) and key.isdigit():
            key = int(key)
        if isinstance(key, int):
            if 0 <= key < len(node.inputs):
                socket = node.inputs[key]
        else:
            socket = node.inputs.get(key)
        if socket is None:
            continue
        try:
            socket.default_value = value
        except (AttributeError, TypeError, ValueError) as exc:
            report({'INFO'}, f"node pie: could not set input {key}: {exc}")


class IOPS_OT_NodeSpawnConnected(bpy.types.Operator):
    """Add a node connected to the active one"""

    bl_idname = "iops.node_spawn_connected"
    bl_label = "Spawn Connected Node"
    bl_options = {'REGISTER', 'UNDO'}

    node_idname: bpy.props.StringProperty(name="Node", default="")
    entry_json: bpy.props.StringProperty(name="Entry", default="")

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return (
            space is not None
            and space.type == 'NODE_EDITOR'
            and space.edit_tree is not None
        )

    def execute(self, context):
        ntree = context.space_data.edit_tree
        active = ntree.nodes.active

        try:
            entry = json.loads(self.entry_json) if self.entry_json else {}
        except ValueError:
            entry = {}
        idname = self.node_idname or entry.get("node", "")

        try:
            new = ntree.nodes.new(idname)
        except (RuntimeError, TypeError) as exc:
            self.report({'WARNING'}, f"cannot add {idname}: {exc}")
            return {'CANCELLED'}

        _apply_entry_props(new, entry, self.report)

        if active is None or active is new:
            new.location = context.space_data.cursor_location
        else:
            plan = pl.plan_spawn(
                _node_desc(active), _node_desc(new),
                downstream=_downstream(ntree, active),
                from_socket=entry.get("from_socket"),
            )
            new.location = plan.location
            for link in plan.links_to_remove:
                for existing in list(ntree.links):
                    if (existing.from_node is active
                            and existing.to_node.name == link.to_node):
                        ntree.links.remove(existing)
            for from_key, from_idx, to_key, to_idx in plan.links_to_add:
                from_node = active if from_key == "ACTIVE" else new
                to_node = new if to_key == "NEW" else ntree.nodes.get(to_key)
                if to_node is None:
                    continue
                ntree.links.new(from_node.outputs[from_idx],
                                to_node.inputs[to_idx])
            if plan.warning:
                self.report({'INFO'}, plan.warning)

        for node in ntree.nodes:
            node.select = False
        new.select = True
        ntree.nodes.active = new

        bpy.ops.transform.translate('INVOKE_DEFAULT')
        return {'FINISHED'}


def _catalog_items(self, context):
    space = context.space_data
    tree = space.edit_tree if space else None
    if tree is None:
        return [('NONE', "None", "")]
    return catalog.items(tree.bl_idname) or [('NONE', "None", "")]


class IOPS_OT_NodePieAddSearch(bpy.types.Operator):
    """Search every node type valid in this editor"""

    bl_idname = "iops.node_pie_add_search"
    bl_label = "Add New Node"
    bl_property = "node_type"
    bl_options = {'REGISTER', 'UNDO'}

    node_type: bpy.props.EnumProperty(name="Node", items=_catalog_items)

    @classmethod
    def poll(cls, context):
        return IOPS_OT_NodeSpawnConnected.poll(context)

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if self.node_type == 'NONE':
            return {'CANCELLED'}
        return bpy.ops.iops.node_spawn_connected(node_idname=self.node_type)


classes = (
    IOPS_OT_NodeSpawnConnected,
    IOPS_OT_NodePieAddSearch,
)
```

- [ ] **Step 2: Register the classes**

In the repo root `__init__.py`, import alongside the other operator imports and add both classes to the registration tuple, following the pattern used for `operators/falloff` (search `mesh_falloff` to find it).

- [ ] **Step 3: Verify in Blender**

```bash
blender --background --factory-startup --python tests/smoke_register.py
```

Expected: exits 0 (the smoke test gains assertions in Task 7).

- [ ] **Step 4: Commit**

```bash
git add operators/node_pie/ops.py __init__.py
git commit -m "feat(node-pie): spawn-connected operator and node search"
```

---

### Task 7: Pie menu, call operator, Node Editor keymap

**Files:**
- Create: `ui/iops_pie_node.py`
- Modify: `utils/functions.py:680-716` (keymap routing), `prefs/hotkeys_default.py:62-65` (default binding), `__init__.py` (registration), `tests/smoke_register.py`

**Interfaces:**
- Consumes: `store.get_entries` (Task 5), `iops.node_spawn_connected` / `iops.node_pie_add_search` (Task 6), `nr.SLOT_LABELS` (Task 4).
- Produces: `IOPS_MT_Pie_Node`, `IOPS_OT_Call_Pie_Node` (`iops.call_pie_node`, `is_bindable = True`).

- [ ] **Step 1: Write the menu**

```python
# ui/iops_pie_node.py
"""Contextual pie for the Geometry Nodes and Shader editors.

One tree-type-agnostic menu: it reads the active node at draw time and asks the
rule store what to offer. Slot order is Blender's pie order (W, E, S, N, NW,
NE, SW, SE) and matches the `slots` list index in the preset JSON.
"""
import json

import bpy
from bpy.types import Menu

from ..operators.node_pie import store
from ..utils import node_pie_rules as nr

SUPPORTED_TREES = ("GeometryNodeTree", "ShaderNodeTree")


def _node_label(entry):
    if entry.get("text"):
        return entry["text"]
    cls = getattr(bpy.types, entry["node"], None)
    return getattr(cls, "bl_label", entry["node"])


class IOPS_MT_Pie_Node(Menu):
    bl_idname = "IOPS_MT_Pie_Node"
    bl_label = "IOPS Node Pie"

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return (
            space is not None
            and space.type == 'NODE_EDITOR'
            and space.edit_tree is not None
            and space.edit_tree.bl_idname in SUPPORTED_TREES
        )

    def draw(self, context):
        pie = self.layout.menu_pie()
        tree = context.space_data.edit_tree
        active = tree.nodes.active

        entries = None
        if active is not None:
            entries = store.get_entries(tree.bl_idname, active.bl_idname)
        if entries is None:
            entries = store.get_entries(tree.bl_idname, nr.FALLBACK_KEY) \
                or [None] * nr.SLOT_COUNT

        for index, entry in enumerate(entries):
            if entry is None:
                pie.separator()
                continue
            if entry["node"] == "__search__":
                pie.operator("iops.node_pie_add_search",
                             text=entry.get("text", "Add New Node"),
                             icon=entry.get("icon", 'VIEWZOOM'))
                continue
            if not hasattr(bpy.types, entry["node"]):
                store.warn_once(
                    f"slot {nr.SLOT_LABELS[index]} names unknown node "
                    f"{entry['node']}"
                )
                pie.separator()
                continue
            op = pie.operator("iops.node_spawn_connected",
                              text=_node_label(entry),
                              icon=entry.get("icon", 'NONE'))
            op.node_idname = entry["node"]
            op.entry_json = json.dumps(entry)


class IOPS_OT_Call_Pie_Node(bpy.types.Operator):
    """IOPS Node Pie"""

    bl_idname = "iops.call_pie_node"
    bl_label = "IOPS Node Pie"
    is_bindable = True

    @classmethod
    def poll(cls, context):
        return IOPS_MT_Pie_Node.poll(context)

    def execute(self, context):
        bpy.ops.wm.call_menu_pie(name="IOPS_MT_Pie_Node")
        return {'FINISHED'}
```

- [ ] **Step 2: Route the keymap**

In `utils/functions.py`, `keymap_name_for_idname()` currently falls through to `"Window"` for anything unmatched. Add, before the final `return "Window"`:

```python
    if "iops.node" in idname:
        return "Node Editor"
```

and in `register_keymaps()` extend the space-type map and the pre-created keymap list:

```python
    km_space_types = {"3D View": "VIEW_3D", "Node Editor": "NODE_EDITOR"}
    ...
    for name in ("Window", "Mesh", "Object Mode", "UV Editor", "3D View",
                 "Node Editor"):
        items_for(name)
```

- [ ] **Step 3: Ship a default binding**

In `prefs/hotkeys_default.py`, next to the other `call_pie` lines (around line 62-65):

```python
    ("iops.call_pie_node", "Q", "PRESS", True, True, True, False),
```

- [ ] **Step 4: Register**

Add `IOPS_MT_Pie_Node` and `IOPS_OT_Call_Pie_Node` to the imports and registration tuple in the repo root `__init__.py`, beside `IOPS_MT_Pie_Menu` / `IOPS_OT_Call_Pie_Menu` (line ~206 and ~508).

- [ ] **Step 5: Extend the smoke test**

In `tests/smoke_register.py`, add to the operator loop and after the keymap assertions:

```python
for op_name in ("node_spawn_connected", "node_pie_add_search", "call_pie_node"):
    assert hasattr(bpy.ops.iops, op_name), "missing operator: iops.%s" % op_name

assert hasattr(bpy.types, "IOPS_MT_Pie_Node"), "node pie menu not registered"

km = bpy.context.window_manager.keyconfigs.addon.keymaps.get("Node Editor")
assert km is not None, "addon 'Node Editor' keymap missing"
assert km.space_type == "NODE_EDITOR", "Node Editor keymap has wrong space_type"
assert any(
    kmi.idname == "iops.call_pie_node" for kmi in km.keymap_items
), "iops.call_pie_node not bound in Node Editor keymap"
```

- [ ] **Step 6: Run the smoke test**

```bash
blender --background --factory-startup --python tests/smoke_register.py
```

Expected: exits 0, no assertion errors.

- [ ] **Step 7: Commit**

```bash
git add ui/iops_pie_node.py utils/functions.py prefs/hotkeys_default.py __init__.py tests/smoke_register.py
git commit -m "feat(node-pie): pie menu, call operator, Node Editor keymap"
```

---

### Task 8: Shipped default tables + in-Blender validation

**Files:**
- Modify: `utils/node_pie_rules.py`
- Create: `tools/verify_node_pie_defaults.py`
- Test: `tests/test_node_pie_rules.py`

**Interfaces:**
- Consumes: `normalise_rule`, `SLOT_COUNT`, `FALLBACK_KEY` (Task 4).
- Produces: populated `DEFAULTS["GeometryNodeTree"]` and `DEFAULTS["ShaderNodeTree"]`.

All ids below were verified present in Blender 5.2.2 on 2026-09-18. `ShaderNodeMath`, `ShaderNodeVectorMath`, `ShaderNodeMix`, `ShaderNodeValToRGB`, `ShaderNodeMapRange`, `ShaderNodeSeparateXYZ`, `ShaderNodeCombineXYZ` and `ShaderNodeTexNoise` are valid in **both** tree types. `ShaderNodeTexCoord`, `ShaderNodeBsdfPrincipled` and `ShaderNodeOutputMaterial` are shader-only.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_node_pie_rules.py

def test_defaults_cover_both_tree_types():
    assert nr.DEFAULTS["GeometryNodeTree"]
    assert nr.DEFAULTS["ShaderNodeTree"]


def test_every_default_rule_normalises_to_eight_slots():
    for tree_type, rules in nr.DEFAULTS.items():
        for node_idname, rule in rules.items():
            slots = nr.normalise_rule(rule)
            assert len(slots) == nr.SLOT_COUNT, (tree_type, node_idname)
            assert any(slots), (tree_type, node_idname)


def test_fallback_rules_offer_the_search_slot():
    for tree_type, rules in nr.DEFAULTS.items():
        slots = nr.normalise_rule(rules[nr.FALLBACK_KEY])
        assert any(s and s["node"] == "__search__" for s in slots), tree_type


def test_shader_only_nodes_are_absent_from_geometry_defaults():
    shader_only = {"ShaderNodeTexCoord", "ShaderNodeBsdfPrincipled",
                   "ShaderNodeOutputMaterial", "ShaderNodeMixShader",
                   "ShaderNodeAddShader", "ShaderNodeBump",
                   "ShaderNodeDisplacement", "ShaderNodeNormalMap"}
    for node_idname, rule in nr.DEFAULTS["GeometryNodeTree"].items():
        for slot in nr.normalise_rule(rule):
            if slot:
                assert slot["node"] not in shader_only, node_idname


def test_geometry_only_nodes_are_absent_from_shader_defaults():
    for node_idname, rule in nr.DEFAULTS["ShaderNodeTree"].items():
        for slot in nr.normalise_rule(rule):
            if slot and slot["node"].startswith("GeometryNode"):
                raise AssertionError(f"{node_idname} offers {slot['node']}")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_node_pie_rules.py -v`
Expected: FAIL on `test_defaults_cover_both_tree_types` — `DEFAULTS` values are empty dicts.

- [ ] **Step 3: Write the tables**

```python
# append to utils/node_pie_rules.py, replacing the empty DEFAULTS stub

def _slots(*entries):
    """Build a rule from (node, text) pairs or bare node idnames."""
    out = []
    for entry in entries:
        if entry is None:
            out.append(None)
        elif isinstance(entry, dict):
            out.append(entry)
        elif isinstance(entry, tuple):
            out.append({"node": entry[0], "text": entry[1]})
        else:
            out.append({"node": entry})
    return {"slots": out}


SEARCH_SLOT = {"node": "__search__", "text": "Add New Node", "icon": "VIEWZOOM"}

# --- Geometry Nodes -------------------------------------------------------

GEO_CHAIN = _slots(
    ("GeometryNodeSetPosition", "Set Position"),
    ("GeometryNodeTransform", "Transform"),
    ("GeometryNodeJoinGeometry", "Join"),
    ("GeometryNodeSetMaterial", "Set Material"),
    ("GeometryNodeMergeByDistance", "Merge by Distance"),
    ("GeometryNodeSubdivisionSurface", "Subdivide"),
    ("GeometryNodeSetShadeSmooth", "Shade Smooth"),
    ("GeometryNodeInstanceOnPoints", "Instance on Points"),
)

GEO_POINTS = _slots(
    ("GeometryNodeInstanceOnPoints", "Instance on Points"),
    ("GeometryNodeSetPosition", "Set Position"),
    ("GeometryNodeStoreNamedAttribute", "Store Attribute"),
    ("GeometryNodePointsToVertices", "Points to Vertices"),
    ("GeometryNodeJoinGeometry", "Join"),
    ("GeometryNodeDeleteGeometry", "Delete"),
    ("GeometryNodeProximity", "Proximity"),
    ("GeometryNodeAttributeStatistic", "Statistic"),
)

GEO_FIELD = _slots(
    ("ShaderNodeMath", "Math"),
    ("ShaderNodeVectorMath", "Vector Math"),
    ("ShaderNodeSeparateXYZ", "Separate XYZ"),
    ("ShaderNodeCombineXYZ", "Combine XYZ"),
    ("ShaderNodeMapRange", "Map Range"),
    ("ShaderNodeMix", "Mix"),
    ("GeometryNodeCaptureAttribute", "Capture"),
    ("GeometryNodeStoreNamedAttribute", "Store Attribute"),
)

GEO_RAYCAST = _slots(
    ("GeometryNodeCaptureAttribute", "Capture"),
    ("GeometryNodeSetPosition", "Set Position"),
    ("GeometryNodeStoreNamedAttribute", "Store Attribute"),
    ("ShaderNodeMath", "Math"),
    ("ShaderNodeVectorMath", "Vector Math"),
    ("ShaderNodeSeparateXYZ", "Separate XYZ"),
    ("GeometryNodeSwitch", "Switch"),
    ("GeometryNodeProximity", "Proximity"),
)

GEO_FALLBACK = _slots(
    ("GeometryNodeSetPosition", "Set Position"),
    ("GeometryNodeTransform", "Transform"),
    SEARCH_SLOT,
    ("GeometryNodeJoinGeometry", "Join"),
    ("GeometryNodeSwitch", "Switch"),
    ("GeometryNodeStoreNamedAttribute", "Store Attribute"),
    ("GeometryNodeCaptureAttribute", "Capture"),
    ("GeometryNodeRealizeInstances", "Realize"),
)

GEO_GEOMETRY_NODES = (
    "GeometryNodeMeshCube", "GeometryNodeMeshLine", "GeometryNodeMeshBoolean",
    "GeometryNodeExtrudeMesh", "GeometryNodeDualMesh",
    "GeometryNodeCurveToMesh", "GeometryNodeMeshToCurve",
    "GeometryNodeResampleCurve", "GeometryNodeFillCurve",
    "GeometryNodeSeparateGeometry", "GeometryNodeDeleteGeometry",
    "GeometryNodeConvexHull", "GeometryNodeBoundBox",
    "GeometryNodeScaleElements", "GeometryNodeFlipFaces",
    "GeometryNodeTriangulate", "GeometryNodeSplitEdges",
    "GeometryNodeSubdivisionSurface", "GeometryNodeMergeByDistance",
    "GeometryNodeSetShadeSmooth", "GeometryNodeSetMaterial",
    "GeometryNodeTransform", "GeometryNodeSetPosition",
    "GeometryNodeJoinGeometry", "GeometryNodeRealizeInstances",
    "GeometryNodeInstanceOnPoints", "GeometryNodeSetID",
    "GeometryNodeSwitch",
)

GEO_FIELD_NODES = (
    "GeometryNodeInputPosition", "GeometryNodeInputNormal",
    "GeometryNodeInputIndex", "GeometryNodeProximity",
    "GeometryNodeAttributeStatistic", "GeometryNodeSampleIndex",
    "GeometryNodeCaptureAttribute",
)

# --- Shader ---------------------------------------------------------------

SHD_SHADER = _slots(
    ("ShaderNodeOutputMaterial", "Material Output"),
    ("ShaderNodeMixShader", "Mix Shader"),
    ("ShaderNodeAddShader", "Add Shader"),
    None, None, None, None, None,
)

SHD_COLOR = _slots(
    ("ShaderNodeValToRGB", "Color Ramp"),
    ("ShaderNodeMix", "Mix"),
    ("ShaderNodeMath", "Math"),
    ("ShaderNodeHueSaturation", "Hue/Sat"),
    ("ShaderNodeBrightContrast", "Bright/Contrast"),
    ("ShaderNodeInvert", "Invert"),
    ("ShaderNodeSeparateColor", "Separate Color"),
    ("ShaderNodeBump", "Bump"),
)

SHD_VECTOR = _slots(
    ("ShaderNodeMapping", "Mapping"),
    ("ShaderNodeSeparateXYZ", "Separate XYZ"),
    ("ShaderNodeVectorMath", "Vector Math"),
    ("ShaderNodeTexNoise", "Noise"),
    ("ShaderNodeTexVoronoi", "Voronoi"),
    ("ShaderNodeTexImage", "Image"),
    ("ShaderNodeBump", "Bump"),
    ("ShaderNodeNormalMap", "Normal Map"),
)

SHD_VALUE = _slots(
    ("ShaderNodeMapRange", "Map Range"),
    ("ShaderNodeMath", "Math"),
    ("ShaderNodeMix", "Mix"),
    ("ShaderNodeValToRGB", "Color Ramp"),
    ("ShaderNodeClamp", "Clamp"),
    ("ShaderNodeFloatCurve", "Float Curve"),
    ("ShaderNodeCombineXYZ", "Combine XYZ"),
    ("ShaderNodeMixShader", "Mix Shader"),
)

SHD_TEX_NOISE = _slots(
    ("ShaderNodeValToRGB", "Color Ramp"),
    ("ShaderNodeMapRange", "Map Range"),
    ("ShaderNodeBump", "Bump"),
    {"node": "ShaderNodeMath", "text": "Multiply", "props": {"operation": "MULTIPLY"}},
    ("ShaderNodeMix", "Mix"),
    ("ShaderNodeDisplacement", "Displacement"),
    ("ShaderNodeSeparateColor", "Separate Color"),
    ("ShaderNodeMapping", "Mapping"),
)

SHD_TEX_IMAGE = _slots(
    ("ShaderNodeValToRGB", "Color Ramp"),
    ("ShaderNodeMix", "Mix"),
    ("ShaderNodeNormalMap", "Normal Map"),
    ("ShaderNodeBump", "Bump"),
    ("ShaderNodeSeparateColor", "Separate Color"),
    ("ShaderNodeHueSaturation", "Hue/Sat"),
    ("ShaderNodeMath", "Math"),
    ("ShaderNodeDisplacement", "Displacement"),
)

SHD_FALLBACK = _slots(
    ("ShaderNodeBsdfPrincipled", "Principled"),
    ("ShaderNodeTexImage", "Image"),
    SEARCH_SLOT,
    ("ShaderNodeTexNoise", "Noise"),
    ("ShaderNodeMapping", "Mapping"),
    ("ShaderNodeTexCoord", "Texture Coord"),
    ("ShaderNodeMix", "Mix"),
    ("ShaderNodeMath", "Math"),
)

SHD_SHADER_NODES = (
    "ShaderNodeBsdfPrincipled", "ShaderNodeBsdfDiffuse", "ShaderNodeBsdfGlass",
    "ShaderNodeEmission", "ShaderNodeBsdfTransparent", "ShaderNodeMixShader",
    "ShaderNodeAddShader",
)

SHD_COLOR_NODES = (
    "ShaderNodeTexVoronoi", "ShaderNodeTexChecker", "ShaderNodeRGB",
    "ShaderNodeValToRGB", "ShaderNodeMix", "ShaderNodeHueSaturation",
    "ShaderNodeBrightContrast", "ShaderNodeGamma", "ShaderNodeInvert",
    "ShaderNodeRGBCurve", "ShaderNodeCombineColor", "ShaderNodeAttribute",
    "ShaderNodeObjectInfo",
)

SHD_VECTOR_NODES = (
    "ShaderNodeTexCoord", "ShaderNodeMapping", "ShaderNodeNewGeometry",
    "ShaderNodeNormalMap", "ShaderNodeBump", "ShaderNodeCombineXYZ",
    "ShaderNodeVectorTransform",
)

SHD_VALUE_NODES = (
    "ShaderNodeMath", "ShaderNodeValue", "ShaderNodeFresnel",
    "ShaderNodeLayerWeight", "ShaderNodeMapRange", "ShaderNodeClamp",
    "ShaderNodeFloatCurve", "ShaderNodeSeparateXYZ", "ShaderNodeSeparateColor",
)

DEFAULTS = {
    "GeometryNodeTree": {
        **dict.fromkeys(GEO_GEOMETRY_NODES, GEO_CHAIN),
        **dict.fromkeys(GEO_FIELD_NODES, GEO_FIELD),
        "GeometryNodeDistributePointsOnFaces": GEO_POINTS,
        "GeometryNodePointsToVertices": GEO_POINTS,
        "GeometryNodeRaycast": GEO_RAYCAST,
        FALLBACK_KEY: GEO_FALLBACK,
    },
    "ShaderNodeTree": {
        **dict.fromkeys(SHD_SHADER_NODES, SHD_SHADER),
        **dict.fromkeys(SHD_COLOR_NODES, SHD_COLOR),
        **dict.fromkeys(SHD_VECTOR_NODES, SHD_VECTOR),
        **dict.fromkeys(SHD_VALUE_NODES, SHD_VALUE),
        "ShaderNodeTexNoise": SHD_TEX_NOISE,
        "ShaderNodeTexImage": SHD_TEX_IMAGE,
        FALLBACK_KEY: SHD_FALLBACK,
    },
}
```

Note: `_slots` and the tables must be defined *before* any module-level use of `DEFAULTS`, and the empty-dict stub from Task 4 must be removed so it cannot shadow the real table.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_node_pie_rules.py tests/test_node_pie_planner.py -v`
Expected: PASS, all tests

- [ ] **Step 5: Write the in-Blender validator**

```python
# tools/verify_node_pie_defaults.py
"""Assert every shipped node-pie default is creatable in its tree type.

Run: blender --background --factory-startup --python tools/verify_node_pie_defaults.py
Exits non-zero (via AssertionError) listing every id that cannot be created.
Must be run whenever an id is added to utils/node_pie_rules.py — poll() lies,
so creation is the only honest check.
"""
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import node_pie_rules as nr  # noqa: E402

bad = []
for tree_type, rules in nr.DEFAULTS.items():
    scratch = bpy.data.node_groups.new("IOPS_VerifyDefaults", tree_type)
    try:
        for node_idname, rule in rules.items():
            for index, slot in enumerate(nr.normalise_rule(rule)):
                if not slot or slot["node"] == "__search__":
                    continue
                try:
                    node = scratch.nodes.new(slot["node"])
                    scratch.nodes.remove(node)
                except (RuntimeError, TypeError) as exc:
                    bad.append(
                        f"{tree_type}/{node_idname} slot "
                        f"{nr.SLOT_LABELS[index]}: {slot['node']} ({exc})"
                    )
    finally:
        bpy.data.node_groups.remove(scratch)

assert not bad, "invalid default node ids:\n  " + "\n  ".join(bad)
print("node pie defaults OK")
```

- [ ] **Step 6: Run the validator**

```bash
blender --background --factory-startup --python tools/verify_node_pie_defaults.py
```

Expected: prints `node pie defaults OK`. If it lists ids, remove or correct them in `utils/node_pie_rules.py` and re-run until clean — do not proceed with a failing validator.

- [ ] **Step 7: Commit**

```bash
git add utils/node_pie_rules.py tests/test_node_pie_rules.py tools/verify_node_pie_defaults.py
git commit -m "feat(node-pie): shipped default tables and validator"
```

---

### Task 9: Prefs tab

**Files:**
- Create: `prefs/node_pie_prefs.py`
- Modify: `prefs/addon_preferences.py:112-120` (tabs enum), `:762-775` (tab row), and the tab-body dispatch near `:1321`; `__init__.py` (register operators)

**Interfaces:**
- Consumes: `store` (Task 5), `catalog` (Task 5), `nr.SLOT_LABELS` / `normalise_rule` (Tasks 4, 8).
- Produces: `draw_node_pie_tab(prefs, layout, context)`; operators `iops.node_pie_save`, `iops.node_pie_reload`, `iops.node_pie_reset_rule`, `iops.node_pie_reset_all`, `iops.node_pie_add_rule`, `iops.node_pie_remove_rule`, `iops.node_pie_set_slot`, `iops.node_pie_clear_slot`; property definitions to add to the addon preferences class.

- [ ] **Step 1: Add the preference properties**

In `prefs/addon_preferences.py`, next to the other preference properties:

```python
    node_pie_tree_type: bpy.props.EnumProperty(
        name="Tree",
        items=[("GeometryNodeTree", "Geometry Nodes", ""),
               ("ShaderNodeTree", "Shader", "")],
        default="GeometryNodeTree",
    )
    # Dynamic EnumProperty values are not persisted to userpref.blend, so the
    # selected rule is backed by a real StringProperty — same reasoning as
    # `theme_preset` / `theme_preset_name` in prefs/theme.py.
    node_pie_rule_name: bpy.props.StringProperty(default="__fallback__",
                                                 options={"HIDDEN"})
```

Add `("NODEPIE", "NODE PIE", "")` to the `tabs` enum items.

- [ ] **Step 2: Write the tab module**

```python
# prefs/node_pie_prefs.py
"""NODE PIE tab: edit which nodes each pie slot spawns.

Slot edits go straight into the in-memory store (so the next pie open shows
them) and are written to scripts/presets/IOPS/node_pies/<tree>.json on Save.
Per-slot `props`/`inputs` are shown read-only — they are JSON-only in v1.
"""
import bpy

from ..operators.node_pie import catalog, store
from ..utils import node_pie_rules as nr


def _rules(prefs):
    return dict(store.rules_for(prefs.node_pie_tree_type))


def _current_rule_key(prefs):
    rules = _rules(prefs)
    key = prefs.node_pie_rule_name
    if key in rules:
        return key
    return nr.FALLBACK_KEY


def _write_slot(prefs, index, node_idname):
    tree_type = prefs.node_pie_tree_type
    rules = _rules(prefs)
    key = _current_rule_key(prefs)
    slots = nr.normalise_rule(rules.get(key, {}))
    slots[index] = {"node": node_idname} if node_idname else None
    rules[key] = {"slots": slots}
    store.set_rules(tree_type, rules)


class IOPS_OT_NodePieSetSlot(bpy.types.Operator):
    """Set the node this pie slot spawns"""

    bl_idname = "iops.node_pie_set_slot"
    bl_label = "Set Slot"
    bl_property = "node_type"

    slot_index: bpy.props.IntProperty(default=0, options={"HIDDEN"})
    node_type: bpy.props.EnumProperty(
        name="Node",
        items=lambda self, context: catalog.items(
            context.preferences.addons["InteractionOps"].preferences.node_pie_tree_type
        ),
    )

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        prefs = context.preferences.addons["InteractionOps"].preferences
        _write_slot(prefs, self.slot_index, self.node_type)
        return {'FINISHED'}


class IOPS_OT_NodePieClearSlot(bpy.types.Operator):
    """Empty this pie slot"""

    bl_idname = "iops.node_pie_clear_slot"
    bl_label = "Clear Slot"

    slot_index: bpy.props.IntProperty(default=0, options={"HIDDEN"})

    def execute(self, context):
        prefs = context.preferences.addons["InteractionOps"].preferences
        _write_slot(prefs, self.slot_index, "")
        return {'FINISHED'}


class IOPS_OT_NodePieSave(bpy.types.Operator):
    """Write these rules to the user preset file"""

    bl_idname = "iops.node_pie_save"
    bl_label = "Save"

    def execute(self, context):
        prefs = context.preferences.addons["InteractionOps"].preferences
        path = store.save(prefs.node_pie_tree_type,
                          store.rules_for(prefs.node_pie_tree_type))
        self.report({'INFO'}, f"Saved {path}")
        return {'FINISHED'}


class IOPS_OT_NodePieReload(bpy.types.Operator):
    """Re-read the user preset file, discarding unsaved edits"""

    bl_idname = "iops.node_pie_reload"
    bl_label = "Reload"

    def execute(self, context):
        prefs = context.preferences.addons["InteractionOps"].preferences
        store.reload(prefs.node_pie_tree_type)
        return {'FINISHED'}


class IOPS_OT_NodePieResetRule(bpy.types.Operator):
    """Drop this rule back to the shipped default"""

    bl_idname = "iops.node_pie_reset_rule"
    bl_label = "Reset Rule"

    def execute(self, context):
        prefs = context.preferences.addons["InteractionOps"].preferences
        tree_type = prefs.node_pie_tree_type
        rules = _rules(prefs)
        key = _current_rule_key(prefs)
        shipped = nr.DEFAULTS.get(tree_type, {}).get(key)
        if shipped is None:
            rules.pop(key, None)
        else:
            rules[key] = shipped
        store.set_rules(tree_type, rules)
        return {'FINISHED'}


class IOPS_OT_NodePieResetAll(bpy.types.Operator):
    """Drop every rule for this tree type back to the shipped defaults"""

    bl_idname = "iops.node_pie_reset_all"
    bl_label = "Reset All"

    def execute(self, context):
        prefs = context.preferences.addons["InteractionOps"].preferences
        tree_type = prefs.node_pie_tree_type
        store.set_rules(tree_type, dict(nr.DEFAULTS.get(tree_type, {})))
        return {'FINISHED'}


class IOPS_OT_NodePieAddRule(bpy.types.Operator):
    """Start a rule for another node type"""

    bl_idname = "iops.node_pie_add_rule"
    bl_label = "Add Rule"
    bl_property = "node_type"

    node_type: bpy.props.EnumProperty(
        name="Node",
        items=lambda self, context: catalog.items(
            context.preferences.addons["InteractionOps"].preferences.node_pie_tree_type
        ),
    )

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        prefs = context.preferences.addons["InteractionOps"].preferences
        rules = _rules(prefs)
        rules.setdefault(self.node_type, {"slots": [None] * nr.SLOT_COUNT})
        store.set_rules(prefs.node_pie_tree_type, rules)
        prefs.node_pie_rule_name = self.node_type
        return {'FINISHED'}


class IOPS_OT_NodePieRemoveRule(bpy.types.Operator):
    """Delete this rule"""

    bl_idname = "iops.node_pie_remove_rule"
    bl_label = "Remove Rule"

    def execute(self, context):
        prefs = context.preferences.addons["InteractionOps"].preferences
        rules = _rules(prefs)
        key = _current_rule_key(prefs)
        if key != nr.FALLBACK_KEY:
            rules.pop(key, None)
            prefs.node_pie_rule_name = nr.FALLBACK_KEY
            store.set_rules(prefs.node_pie_tree_type, rules)
        return {'FINISHED'}


def draw_node_pie_tab(prefs, layout, context):
    layout.row(align=True).prop(prefs, "node_pie_tree_type", expand=True)

    rules = _rules(prefs)
    key = _current_rule_key(prefs)

    row = layout.row(align=True)
    row.label(text=f"Rule: {key}", icon='NODE')
    row.operator("iops.node_pie_add_rule", text="", icon='ADD')
    row.operator("iops.node_pie_remove_rule", text="", icon='REMOVE')

    keys = sorted(k for k in rules if k != nr.FALLBACK_KEY)
    grid = layout.box().grid_flow(columns=3, even_columns=True)
    for name in [nr.FALLBACK_KEY] + keys:
        op_row = grid.row()
        op_row.alert = (name == key)
        op_row.operator("iops.node_pie_pick_rule", text=name).rule_name = name

    box = layout.box()
    slots = nr.normalise_rule(rules.get(key, {}))
    for index, slot in enumerate(slots):
        row = box.row(align=True)
        row.label(text=nr.SLOT_LABELS[index], icon='DOT')
        text = slot["node"] if slot else "—"
        if slot and slot.get("text"):
            text = f"{slot['text']}  ({slot['node']})"
        row.operator("iops.node_pie_set_slot", text=text).slot_index = index
        if slot and (slot.get("props") or slot.get("inputs")):
            sub = row.row()
            sub.enabled = False
            preset = slot.get("props") or slot.get("inputs")
            sub.label(text=", ".join(f"{k}={v}" for k, v in preset.items()))
        row.operator("iops.node_pie_clear_slot", text="", icon='X') \
            .slot_index = index

    row = layout.row(align=True)
    row.operator("iops.node_pie_save", icon='FILE_TICK')
    row.operator("iops.node_pie_reload", icon='FILE_REFRESH')
    row.operator("iops.node_pie_reset_rule", icon='LOOP_BACK')
    row.operator("iops.node_pie_reset_all", icon='TRASH')


class IOPS_OT_NodePiePickRule(bpy.types.Operator):
    """Edit this rule"""

    bl_idname = "iops.node_pie_pick_rule"
    bl_label = "Pick Rule"

    rule_name: bpy.props.StringProperty(default=nr.FALLBACK_KEY)

    def execute(self, context):
        prefs = context.preferences.addons["InteractionOps"].preferences
        prefs.node_pie_rule_name = self.rule_name
        return {'FINISHED'}


classes = (
    IOPS_OT_NodePieSetSlot,
    IOPS_OT_NodePieClearSlot,
    IOPS_OT_NodePieSave,
    IOPS_OT_NodePieReload,
    IOPS_OT_NodePieResetRule,
    IOPS_OT_NodePieResetAll,
    IOPS_OT_NodePieAddRule,
    IOPS_OT_NodePieRemoveRule,
    IOPS_OT_NodePiePickRule,
)
```

- [ ] **Step 3: Hook the tab**

In `prefs/addon_preferences.py`, add the tab button beside the others (near line 770):

```python
        tabs_row.prop_enum(self, "tabs", "NODEPIE")
```

and the body near the other `if self.tabs == ...` blocks (near line 1321):

```python
        if self.tabs == "NODEPIE":
            from .node_pie_prefs import draw_node_pie_tab
            draw_node_pie_tab(self, layout, context)
```

- [ ] **Step 4: Register the operators**

Add `prefs/node_pie_prefs.py`'s `classes` to the registration in the repo root `__init__.py`.

- [ ] **Step 5: Verify**

```bash
blender --background --factory-startup --python tests/smoke_register.py
python -m pytest tests/ -v
```

Expected: smoke test exits 0; pytest passes.

Then in the GUI: Preferences → Add-ons → InteractionOps → NODE PIE. Set a slot, open the pie in the Geometry Nodes editor and confirm the change is live; Save; restart; confirm it persisted.

- [ ] **Step 6: Commit**

```bash
git add prefs/node_pie_prefs.py prefs/addon_preferences.py __init__.py
git commit -m "feat(node-pie): prefs tab for editing pie slots"
```

---

### Task 10: Docs and squash

**Files:**
- Create: `docs/operators/op_node_pie.md`
- Modify: `mkdocs.yml` (nav), `docs/operators.md` (index list)

- [ ] **Step 1: Write the operator doc**

Follow the shape of `docs/operators/op_mesh_falloff_tools.md`. Cover: what the pie does, the default `Ctrl+Alt+Shift+Q` binding in the Node Editor, how the active node decides the contents, the `Add New Node…` search, splice behaviour, where the preset JSON lives (`scripts/presets/IOPS/node_pies/<tree_type>.json`), the slot-order table (W, E, S, N, NW, NE, SW, SE), the entry fields table from the spec, and the v1 limit that `props`/`inputs` are JSON-only.

- [ ] **Step 2: Add it to the nav**

In `mkdocs.yml`, add under the operators nav section (near line 134):

```yaml
          - Node Editor Pie: operators/op_node_pie.md
```

and add the matching line to `docs/operators.md`.

- [ ] **Step 3: Run the full check**

```bash
python -m pytest tests/ -v
blender --background --factory-startup --python tests/smoke_register.py
blender --background --factory-startup --python tools/verify_node_pie_defaults.py
python -m ruff check .
```

Expected: all pass.

- [ ] **Step 4: Squash into one commit**

Per repo convention one feature is one commit. Count the task commits made on this branch (`git log --oneline master..HEAD`), then:

```bash
git reset --soft HEAD~<n>
git add -A
git commit
```

with the message:

```
feat(node-pie): contextual pie menus for node editors

Pie in the Geometry Nodes and Shader editors keyed on the active node's
bl_idname. Picking a slot spawns the node, links it to the active node's
output, splices it into existing downstream links and starts a grab.
Shipped defaults are overridable per node type by user JSON under
scripts/presets/IOPS/node_pies/, editable in the NODE PIE prefs tab.

Node validity is probed by creation, not Node.poll(), which misreports in
Blender 5.2.2.
```

plus the two attribution lines used on this branch.

- [ ] **Step 5: Report what still needs live checking**

Tell the user which viewport checks remain theirs: pie contents against the active node in both editors, chaining several spawns, grab-cancel keeping the link, splice on an output with multiple consumers, prefs Save → restart → Reload.

---

## Self-Review Notes

- **Spec coverage:** goals → Tasks 6, 7; rule schema/merge/degradation → Task 4; planner (sockets, splice, placement) → Tasks 1-3; catalog → Task 5; menu and keymap → Task 7; prefs UI → Task 9; defaults + validator → Task 8; testing → Tasks 1-4, 7, 8; docs → Task 10.
- **Known deviation from the spec:** the spec's `operators/node_pie/rules.py` + `planner.py` became `utils/node_pie_rules.py` + `utils/node_pie_planner.py` so the headless tests can import them (`operators/` is not an importable package outside Blender). The spec was updated to match.
- **Interface consistency:** `store.get_entries(tree_type, node_idname)` (bpy side) wraps `nr.get_entries(rules, node_idname)` (pure side) — the two signatures differ deliberately and are used as written in Tasks 5, 7 and 9.
- **Link tuple shape** is the 4-tuple `(from_node_key, from_socket_index, to_node_key, to_socket_index)` everywhere, with `"ACTIVE"` and `"NEW"` as the two reserved keys; Task 3's tests and Task 6's applier agree on it.
