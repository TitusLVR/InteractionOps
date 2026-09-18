# Node Editor Pie

Contextual pie menu for the Geometry Nodes editor and the Shader editor when it is showing a material, keyed on the exact type of the active node: `iops.call_pie_node` opens it, `iops.node_spawn_connected` fires when a slot is picked, `iops.node_pie_add_search` backs the fallback pie's search slot. It does not appear for World or Line Style shading (the Shader editor's other two `space.shader_type` values), nor in the Compositor or texture-node editors.

Building a node graph is mostly repetition: add a node, find it in a menu, place it, drag a wire. The node that comes next is usually predictable from the node you're standing on — a Noise Texture is normally followed by a Color Ramp, a mesh primitive by Set Position or Transform. The pie collapses that sequence into one keypress plus one direction: pick a slot and the node spawns already wired in, spliced into anything already downstream of the active node, and handed straight to a grab.

**Hotkey:** <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>Q</kbd> in the Node Editor. Rebindable in *Preferences › iOps › Keymaps*.

## What decides the contents

The pie reads the current tree's type (`GeometryNodeTree` or `ShaderNodeTree`, the latter only for a material) and the active node's exact `bl_idname`, then looks up a rule for that node type:

- A matching rule with at least one filled slot draws its 8 entries as `iops.node_spawn_connected` buttons.
- **No active node, or nothing selected** (Blender leaves `nodes.active` pointing at the last active node even after Select All > None, so a deselect is treated the same as no active node), a node type with **no rule**, or a rule whose `"slots"` are all empty draws the **fallback pie** instead — a handful of generally-useful nodes plus an **Add New Node…** slot.
- **Add New Node…** opens a search over every node type Blender can actually create in the current tree. That catalog is built by attempting creation in a scratch node group and catching the failure, not by trusting `Node.poll()`, which misreports several node types (`ShaderNodeMath`, `ShaderNodeMix`, `ShaderNodeValToRGB`, `NodeReroute` and others) in Blender 5.2.2. The ~600-class probe only runs the first time a search is opened for a given tree type, per session.

## What happens when you pick a slot

- The node is created. If there is an active node, it is wired from the first enabled, non-hidden output of the active node (or the slot's `from_socket` override, if it resolves) into the first compatible input on the new node.
- **No active node, or nothing selected:** the new node is simply placed at the 2D cursor — nothing is linked or spliced.
- **Splice:** if that output already fed other nodes downstream, each of those existing links is rerouted through a compatible output of the *new* node instead of the active node's — so dropping a node into the middle of a chain doesn't break what was downstream of it. All downstream consumers move, not just the first. If the new node has no output compatible with a given downstream link, that one link is left exactly as it was — it is not spliced or removed — and iOps reports it rather than creating a type-mismatched link.
- If the new node has no compatible input at all, it still spawns and is placed — just unlinked, with an info report. A pie press never comes back with nothing.
- If the *active* node has no usable output at all, the same applies in reverse: the new node still spawns and is placed, unlinked, with an INFO report.
- The node is placed next to the active node (or, when spliced, roughly midway along the wire if there's room) and handed to a grab (`transform.translate`, invoked modally). Cancelling the grab (<kbd>Esc</kbd> / <kbd>RMB</kbd>) only cancels the move — the node stays at its placed position with its links intact.
- The new node becomes the sole selection and the active node, so the next pie press continues the chain from it.

## User presets

Shipped defaults live in the addon. A per-user override file, one per tree type, lives at:

```
scripts/presets/IOPS/node_pies/<tree_type>.json
```

i.e. `GeometryNodeTree.json` and `ShaderNodeTree.json`. A rule you add there for a node type **replaces the shipped rule for that type wholesale** — there is no per-slot merging, so an addon update can never half-overwrite an edit you made. Setting `"slots": []` for a type forces the fallback pie for it. A slot naming an unknown `bl_idname` (version mismatch, missing addon) is dropped at draw time with a one-time console warning rather than breaking the pie; malformed JSON degrades to the shipped defaults with a one-time warning. An empty or whitespace-only file is treated as "no overrides yet" and quietly uses the shipped defaults — no warning, by design.

### Slot order

`slots` is an 8-entry list, indexed in Blender's own pie draw order:

| Index | Direction |
| --- | --- |
| 0 | W |
| 1 | E |
| 2 | S |
| 3 | N |
| 4 | NW |
| 5 | NE |
| 6 | SW |
| 7 | SE |

`null` leaves a slot empty (drawn as a separator in the pie). Lists shorter than 8 are padded with `null`.

### Entry fields

| Field | Type | Meaning |
| --- | --- | --- |
| `node` | string, required | `bl_idname` of the node to spawn |
| `text` | string, optional | Pie button label; defaults to the node's Blender UI name |
| `icon` | string, optional | Blender icon identifier for the button |
| `props` | object, optional | Attributes set on the new node (e.g. `operation`, `data_type`, `domain`) |
| `inputs` | object, optional | Input socket default values, keyed by socket name or by index given as a string (e.g. `"1"`) |
| `from_socket` | string or int, optional | Which output of the *active* node to link from, overriding the default first-enabled-output pick; a name or index that doesn't resolve on the active node falls back to the default instead of failing |

## Preferences — Node Editor Pie section

*Preferences › iOps › Preferences*, in the **Node Editor Pie** rollout, edits the rule store directly; edits apply the next time the pie opens, whether or not they've been saved to disk.

- **Geometry Nodes / Shader** toggle — which tree type's rules are being edited.
- Rule list — `__fallback__` pinned first, then every node type with a rule. **+** starts a rule for another node type via the same catalog search as Add New Node; **−** makes the selected node type fall back to the generic pie (writes `"slots": []` for it) — it does **not** restore the shipped default; use **Reset Rule** for that.
- Eight slot rows, labelled `W E S N NW NE SW SE` — each has a node-type search field and an **X** to clear it. A slot carrying `props` or `inputs` shows them as a dimmed, read-only summary next to it; those two fields are edited only by hand in the JSON, not here.
- **Save** writes only the rules that differ from the shipped defaults for the current tree type to its preset file — a node type you never touched is never frozen into your file, so a future addon update can still reach it. A rule you emptied with **−** (`"slots": []`) counts as different and is written. **Reload** re-reads that file from disk, discarding unsaved in-memory edits. **Reset Rule** drops the selected rule back to its shipped default. **Reset All** drops every rule for the current tree type back to the shipped defaults.

## v1 limits

- Geometry Nodes editors, and Shader editors showing a material, only — the Compositor, World/Line Style shading and texture-node editors are not covered.
- Multi-selection is ignored; the pie always acts on the active node alone.
- `props` and `inputs` can only be set by hand-editing the preset JSON. There is no UI for them yet.

## Tips

- A node type absent from both the shipped tables and your preset file always gets the fallback pie — that's expected, not a bug; add a rule for it if you want something more specific.
- Because a user rule replaces a shipped one wholesale, copying just the slots you want to change is not enough — write out all 8 slots for that node type in your JSON, or use the prefs UI, which always writes the full 8.
