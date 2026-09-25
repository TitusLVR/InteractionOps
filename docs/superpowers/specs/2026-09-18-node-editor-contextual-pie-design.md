# Contextual Pie Menus for Node Editors — Design

Date: 2026-09-18
Status: approved design, ready for implementation plan

## Problem

Building node graphs means repeatedly: add node, find it in a menu, place it,
drag a wire. The node that comes next is highly predictable from the node you
are standing on — a Noise Texture is usually followed by a Color Ramp, a mesh
primitive by Set Position or Transform. A pie menu keyed on the active node can
collapse that whole sequence into one keypress plus one direction.

## Goals

- Pie menu in the Geometry Nodes and Shader (material) editors whose contents
  depend on the active node's exact type.
- Picking a slot spawns the node, links it to the active node, splices it into
  any existing downstream links, and hands it to a grab so it lands where the
  user wants.
- Chaining: after a spawn the new node is active, so the next pie press
  continues the chain.
- Popular defaults ship with the addon; the user can override any of them.
- Unknown node types still give a useful pie, with a search over every node type
  valid in the current tree.

## Non-goals (v1)

- Compositor, world/line-style shader trees, texture node trees.
- Spawning node groups or multi-node macros.
- Acting on multi-selection (active node only).
- Editing per-slot node property presets (`props` / `inputs`) from the UI;
  those are JSON-only in v1.

## Verified API facts

Checked against Blender 5.2.2 LTS on 2026-09-18. These drove design decisions
and must not be re-derived from memory during implementation.

- **`NodeClass.poll(ntree)` cannot be trusted to decide validity.** It returns
  `False` for `ShaderNodeMath`, `ShaderNodeMix`, `ShaderNodeValToRGB`,
  `NodeReroute`, `NodeGroupInput`, `NodeFrame` in a `GeometryNodeTree`, all of
  which create fine. The reliable test is to attempt creation in a scratch node
  group of that tree type and catch `RuntimeError`. Verified true negatives:
  `ShaderNodeTexCoord` / `ShaderNodeBsdfPrincipled` / `ShaderNodeOutputMaterial`
  raise in a geometry tree, `GeometryNodeSetPosition` raises in a shader tree.
- `bpy.types.Node` has ~600 subclasses, so the creation probe runs once per tree
  type per session, lazily on first use, and is cached in a module dict.
- `node.width` is valid immediately after `nodes.new()` (140 for
  `GeometryNodeSetPosition`); `node.dimensions` is `(0.0, 0.0)` until the node
  has been drawn. Placement math may use `width` only.
- `NodeSocket.type` enum includes `VALUE, INT, BOOLEAN, VECTOR, ROTATION,
  MATRIX, STRING, RGBA, SHADER, OBJECT, IMAGE, GEOMETRY, COLLECTION, TEXTURE,
  MATERIAL, MENU, BUNDLE, CLOSURE, ...`.
- `links.new()` does not reject a type-mismatched link; Blender marks it invalid
  afterwards (`link.is_valid`). Socket compatibility is therefore our own
  concern — it decides which link is *good*, not which link is *possible*.

## Architecture

Pure logic lives in `utils/` and bpy-side code in `operators/`, matching the
existing `utils/falloff_core.py` + `operators/falloff/` split — that is what
lets the headless tests import it (`tests/` add the repo root to `sys.path` and
`from utils import ...`; `operators/` is not an importable package outside
Blender).

```
utils/node_pie_rules.py         pure: schema validation, merge, lookup, shipped defaults
utils/node_pie_planner.py       pure: dataclasses, socket compatibility, plan_spawn
operators/node_pie/__init__.py  package init, register/unregister
operators/node_pie/store.py     bpy-side: preset paths, JSON load/save, in-memory store
operators/node_pie/catalog.py   creation-probed catalog of valid node types per tree
operators/node_pie/ops.py       iops.node_spawn_connected, iops.node_pie_add_search
ui/iops_pie_node.py             IOPS_MT_Pie_Node + IOPS_OT_Call_Pie_Node
prefs/node_pie_prefs.py         NODE PIE tab UI
tools/verify_node_pie_defaults.py  in-Blender validation of the shipped tables
```

Flow:

1. Hotkey (Node Editor keymap) fires `iops.call_pie_node`.
2. `IOPS_MT_Pie_Node.draw` reads `context.space_data.edit_tree.bl_idname` and
   `context.active_node.bl_idname`, asks `store.get_entries()`.
3. A match draws 8 slots, each an `iops.node_spawn_connected` button.
   No match draws the `__fallback__` rule, whose S slot is `Add New Node…`.
4. `Add New Node…` invokes a search popup over `catalog.items(tree_type)` and
   then calls the same spawn operator.
5. `ops` builds a plan via `plan_spawn()`, applies it, selects and
   activates the new node, and invokes `transform.translate`.

## Rule store

### Schema

`scripts/presets/IOPS/node_pies/<tree_type>.json`, one file per tree type
(`GeometryNodeTree.json`, `ShaderNodeTree.json`):

```json
{
  "version": 1,
  "tree_type": "GeometryNodeTree",
  "rules": {
    "__fallback__": { "slots": [ "...7 entries plus the Add New Node… slot..." ] },
    "GeometryNodeMeshCube": {
      "slots": [
        {"node": "GeometryNodeSetPosition", "text": "Set Position"},
        {"node": "ShaderNodeMath", "text": "Multiply",
         "props": {"operation": "MULTIPLY"}, "inputs": {"1": 2.0}},
        null, null, null, null, null, null
      ]
    }
  }
}
```

Entry fields:

| field         | type              | meaning |
|---------------|-------------------|---------|
| `node`        | str, required     | `bl_idname` of the node to spawn |
| `text`        | str, optional     | pie button label; defaults to the node's UI name |
| `icon`        | str, optional     | Blender icon id |
| `props`       | dict, optional    | attributes set on the new node (`operation`, `data_type`, `domain`) |
| `inputs`      | dict, optional    | input socket default values, keyed by socket name or index-as-string |
| `from_socket` | str/int, optional | which output of the *active* node to link from |

### Slot order

Blender's pie draw order is W, E, S, N, NW, NE, SW, SE. `slots` is a list
indexed 0-7 in that order. `null` leaves a slot empty. Lists shorter than 8 are
padded with `null`. The prefs UI labels rows by direction so the index order
never has to be memorised.

### Merge and degradation

- Shipped defaults live in `utils/node_pie_rules.py` as Python data; the user JSON is layered
  on top at load.
- A user rule for a node type **replaces** the shipped rule for that type
  wholesale — no per-slot merging, so an addon update cannot half-overwrite a
  user edit.
- `"slots": []` for a type forces the fallback pie for that type.
- The user may add rules for node types absent from the defaults.
- An entry naming an unknown `bl_idname` (Blender version change, missing
  addon) is dropped at draw time with a one-time console warning. Draw callbacks
  must never raise.
- `version` higher than known: load anyway, report once.
- Malformed or empty JSON: fall back to shipped defaults, report once. Same
  defensive posture as the existing `iops_prefs_user.json` loader.

## Spawn planner

Split so that everything that can be wrong is testable without Blender.

`node_pie_planner.plan_spawn(active, entry, new_node_desc, downstream) -> SpawnPlan`
operates on dataclasses (`NodeDesc`, `SocketDesc`, `LinkDesc`) and returns
`SpawnPlan(location, links_to_add, links_to_remove, props, inputs, warning)`.
`ops.apply_plan(ntree, plan)` touches `bpy` and makes no decisions.

### Socket selection

- **Source**: `entry.from_socket` if given, else the first output of the active
  node that is `enabled` and not `hide`.
- **Target**: the first enabled input on the new node whose type is compatible.
- **Compatibility**: exact type match wins. Failing that, the implicit-convert
  group `{VALUE, INT, BOOLEAN, VECTOR, ROTATION, RGBA}` is mutually compatible.
  `GEOMETRY, SHADER, OBJECT, COLLECTION, MATERIAL, IMAGE, STRING, MENU,
  TEXTURE, MATRIX, BUNDLE, CLOSURE` link only to their own type.
- No compatible input: the node is still spawned, placed and grabbed, unlinked,
  with an `INFO` report. Never a hard failure.

### Splice

If the source socket already has links, then after wiring `active -> new`, for
every existing link `L` from that socket:

- pick the new node's output for `L`: exact type match with `L.to_socket` first,
  else the first output that `is_compatible` with it
- if such an output exists, add `new.<that output> -> L.to_socket` and remove `L`
- if none exists, **leave `L` alone** — it stays connected to the active node —
  and name its node in the plan's warning

A link is only ever removed when a replacement for it is added. The earlier
draft of this design removed `L` unconditionally and fell back to the new
node's first output regardless of type, which silently severed a user's graph
when the spawned node had no usable output (a Material Output, say) and wired
type-mismatched links when it had the wrong ones. Implementation review caught
both; the shipped planner is the version described here.

All downstream consumers that can be spliced move to the new node, not only the
first. Existing nodes are never repositioned. Cycle protection is left to
Blender's own detection.

### Placement

- Plain: `new.location = active.location + (active.width + 40, 0)`.
- Splice: if the nearest downstream node is at least `active.width + new.width +
  80` to the right, place midway between the two so the node lands on the wire;
  otherwise use the plain offset.
- `dimensions` is never read (it is `(0, 0)` before first draw).

### After spawn

- New node becomes the only selected node and the active node — this is what
  makes chaining work.
- `bpy.ops.transform.translate('INVOKE_DEFAULT')`. The node starts at its offset
  rather than under the cursor, so the grab is relative; cancelling leaves the
  node at the offset with its links intact.
- Operator is `bl_options = {'REGISTER', 'UNDO'}`.

## Catalog

`catalog.items(tree_type)` returns `(identifier, name, description)` tuples for
every node type creatable in that tree type.

- Built by walking `bpy.types.Node.__subclasses__()` recursively and attempting
  `scratch_tree.nodes.new(idname)` in a temporary node group of the target type,
  catching `RuntimeError`. The scratch group is removed afterwards.
- Built lazily on first use, cached in a module-level dict keyed by tree type,
  cleared on addon reload.
- Enum item strings are held in that module-level cache so Blender cannot free
  them mid-draw (the standard dynamic-enum lifetime trap).
- Used only by the `Add New Node…` search popup
  (`wm.invoke_search_popup` over the spawn operator's dynamic enum), so the
  600-class probe never runs during a normal matched pie.

## Menu and keymap

- `IOPS_MT_Pie_Node` is a single tree-type-agnostic menu that reads rules at
  draw time. No per-tree-type menu classes.
- `IOPS_OT_Call_Pie_Node` (`iops.call_pie_node`, `is_bindable = True`) mirrors
  `IOPS_OT_Call_Pie_Menu`, registered in the `Node Editor` keymap through the
  existing hotkey system. Per the addon's hotkey rules: registered once, and
  unregister touches only addon-owned keymap items.
- `poll`: `space_data.type == 'NODE_EDITOR'` and `edit_tree` is a
  `GeometryNodeTree` or `ShaderNodeTree`.

## Prefs UI

New `NODE PIE` tab in the existing `tabs` enum in `prefs/addon_preferences.py`;
the drawing lives in `prefs/node_pie_prefs.py` so `addon_preferences.py` (1300+
lines) does not grow another inline editor. Follows the `theme.py` /
`widget_composer.py` precedent.

Layout:

1. Tree type toggle — Geometry Nodes / Shader.
2. Rule selector — dynamic enum of node types with rules, `__fallback__` pinned
   first; `+` opens a catalog search to start a rule, `-` deletes a rule (that
   type reverts to its shipped default, or to fallback if it has none).
3. Eight slot rows labelled `W E S N NW NE SW SE`: node-type search field,
   optional label override, `X` to clear.
4. `Save` (write the whole tree-type JSON) · `Reload` (re-read disk, discard
   unsaved) · `Reset Rule` · `Reset All`.

Behaviour: the pie reads the in-memory store, so edits apply on the next pie
open; `Save` makes them survive a restart; `Reload` is the undo.

Slots carrying `props` / `inputs` show them as a dimmed summary
(`operation=MULTIPLY`) and are editable only in the JSON.

Both dynamic enums (tree type, rule) are backed by real `StringProperty`s via
get/set, because Blender does not persist dynamic `EnumProperty` values to
userpref.blend — the same pattern and reasoning as `theme_preset` in
`prefs/theme.py`.

## Shipped defaults

Built from shared list constants so the source stays small while the keys stay
exact:

```python
DEFAULTS["GeometryNodeTree"] = {
    **dict.fromkeys(GEO_GEOMETRY_NODES, GEO_CHAIN),
    "GeometryNodeRaycast": GEO_RAYCAST,
    "__fallback__": GEO_FALLBACK,
}
```

Lists (all ids verified present in Blender 5.2.2 and creatable in their tree
type):

- `GEO_CHAIN` — SetPosition, Transform, JoinGeometry, SetMaterial,
  MergeByDistance, SubdivisionSurface, SetShadeSmooth, InstanceOnPoints.
  Applied to the ~30 geometry-output node types (primitives, boolean, extrude,
  dual mesh, curve conversions, separate/delete, convex hull, bounding box...).
- `GEO_POINTS` — for DistributePointsOnFaces / PointsToVertices:
  InstanceOnPoints, SetPosition, StoreNamedAttribute, PointsToVertices,
  JoinGeometry, DeleteGeometry, Proximity, AttributeStatistic.
- `GEO_FIELD` — for field/value outputs (InputPosition, InputNormal, InputIndex,
  Proximity): ShaderNodeMath, ShaderNodeVectorMath, ShaderNodeSeparateXYZ,
  ShaderNodeCombineXYZ, ShaderNodeMapRange, ShaderNodeMix, CaptureAttribute,
  StoreNamedAttribute.
- `GEO_FALLBACK` — SetPosition, Transform, JoinGeometry, Switch,
  StoreNamedAttribute, CaptureAttribute, RealizeInstances, plus `Add New Node…`
  in slot S.
- `SHD_SHADER` — for SHADER outputs (Principled, Diffuse, Glass, Emission,
  Transparent): OutputMaterial, MixShader, AddShader.
- `SHD_COLOR` — for color/texture outputs: ValToRGB, ShaderNodeMix,
  ShaderNodeMath, HueSaturation, BrightContrast, Invert, SeparateColor, Bump.
- `SHD_VECTOR` — for TexCoord, Mapping, NewGeometry, NormalMap: Mapping,
  SeparateXYZ, VectorMath, TexNoise, TexVoronoi, TexImage, Bump, NormalMap.
- `SHD_VALUE` — for Math, Value, Fresnel, LayerWeight, MapRange: MapRange,
  ShaderNodeMath, ShaderNodeMix, ValToRGB, Clamp, FloatCurve, CombineXYZ,
  MixShader.
- `SHD_FALLBACK` — BsdfPrincipled, TexImage, TexNoise, Mapping, TexCoord,
  ShaderNodeMix, ShaderNodeMath, plus `Add New Node…` in slot S.

Hand-tuned exceptions: `ShaderNodeTexNoise` (ValToRGB first, then MapRange,
Bump, Math x Multiply, Mix, Displacement, SeparateColor, Mapping),
`ShaderNodeTexImage` (ValToRGB, Mix, NormalMap, Bump, SeparateColor,
HueSaturation, Math, Displacement), `GeometryNodeRaycast` (CaptureAttribute,
SetPosition, StoreNamedAttribute, Math, VectorMath, SeparateXYZ, Switch,
Proximity), `GeometryNodeCaptureAttribute`, `GeometryNodeSwitch`.

Every id in the shipped tables is validated by
`tools/verify_node_pie_defaults.py` (run inside Blender), which asserts each
entry is creatable in the tree type it is registered under. Ids must never be
added to the tables without running it.

## Testing

Headless (`pytest`, bpy-free, matching the existing `tests/conftest.py` setup):

- `tests/test_node_pie_rules.py` — user JSON beats shipped defaults
  whole-entry; `"slots": []` forces fallback; short lists pad to 8; unknown
  `version` loads with a report; unknown `bl_idname` slot is dropped rather than
  raised; malformed and empty JSON degrade to defaults.
- `tests/test_node_pie_planner.py` — socket compatibility matrix (exact types,
  implicit-convert group, exact-only types); source/target selection including
  `from_socket` and hidden/disabled sockets; splice plans for 0, 1 and N
  downstream links; no-compatible-input still yields a placement with no links;
  placement math for plain and spliced cases.
- `tests/smoke_register.py` — new classes register and unregister cleanly.

In Blender, owned by the user:

- Pie opens and reads the correct active node in both editors.
- Chaining several spawns in a row.
- Grab-cancel leaves the node placed and linked.
- Splice on an output with multiple consumers.
- Prefs Save → restart → Reload round-trip.
- `tools/verify_node_pie_defaults.py` passes.

## Risks

- **Catalog probe cost.** 600 creation attempts on first `Add New Node…` use.
  Mitigated by lazy build and session cache; if it proves slow, the probe can be
  narrowed by `bl_idname` prefix before it is attempted.
- **Scratch node group leakage.** The probe creates and removes a temporary node
  group; an exception mid-probe must not leave it behind. Wrapped in
  `try/finally`.
- **Transform in an unexpected context.** `transform.translate` is invoked from
  the pie's execute; if the node editor is not under the cursor the modal will
  not start. Guarded by the operator poll and an area check.
