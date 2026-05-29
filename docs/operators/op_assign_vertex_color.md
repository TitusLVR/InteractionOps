# Assign Vertex Color

Writes a flat color into a mesh's color attribute, either on the selected vertices in Edit Mode or on every vertex/corner of selected mesh objects in Object Mode. The color source is the `Scene.IOPS.iops_vertex_color` picker, with quick override toggles for solid black, grey, and white. Missing color attributes are created on the fly using the chosen domain and data type.

## Assign Vertex Color

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.mesh_assign_vertex_color</span>
<span class="mode">Mode: Object / Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

### Overview
A single-shot color writer for the active color attribute. It bridges the gap between Blender's vertex paint workflow and a simple "fill selected with this color" action that survives mode switches. In Edit Mesh it only touches selected geometry; in Object Mode it fills every element of the attribute on each selected mesh.

If the target object has no color attribute, a new one is created using `Color Attribute Name`, `Attribute Type`, and `Domain` from the operator props. Newly created attributes are made active.

### Usage
- Requires an active mesh object. In Edit Mesh, vertices must be selected to receive color; in Object Mode, every element of the attribute is filled.
- No default keymap binding — invoke via menu/search or a custom shortcut.
- Pick a color in the F6 redo panel (or via the Scene IOPS color slot) and run the operator. Use one of the `Fill Black / Grey / White` toggles for a quick override; those flags reset to off after each run.

### Properties
| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `use_active_color` | Bool | `True` | Write to the mesh's active color attribute. If unset, uses `col_attr_name`. |
| `col_attr_name` | String | `Color` | Name of the color attribute to create or target when not using the active one. |
| `fill_color_black` | Bool | `False` | One-shot override: fill with `(0, 0, 0, 1)`. Auto-resets after execution. |
| `fill_color_white` | Bool | `False` | One-shot override: fill with `(1, 1, 1, 1)`. Auto-resets after execution. |
| `fill_color_grey` | Bool | `False` | One-shot override: fill with `(0.5, 0.5, 0.5, 1)`. Auto-resets after execution. |
| `domain` | Enum | `POINT` | Domain for newly created attributes. Items: `POINT` (Point), `CORNER` (Corner). |
| `attr_type` | Enum | `FLOAT_COLOR` | Data type for newly created attributes. Items: `FLOAT_COLOR` (Float Color), `BYTE_COLOR` (Byte Color). |

The base color comes from `context.scene.IOPS.iops_vertex_color`. The fill toggles take precedence in order black > grey > white.

### Notes
- Edit Mesh path: iterates selected vertices for POINT-domain attributes; for CORNER-domain it fills every loop of any face that has at least one selected vert.
- Object Mode path: fills the entire attribute data array, regardless of vertex selection state.
- All selected mesh objects are processed, not just the active one. If an object lacks the target attribute, one is created and set active.
- The fill flags (`fill_color_black/grey/white`) are mutated to `False` inside `execute()` after a run, so reopening the redo panel will not stick on a previous override.
- A `WARNING` is reported if the active object is not a mesh and the mode is neither Edit nor Object.

---

## Assign Vertex Color Alpha (bl_idname: iops.mesh_assign_vertex_color_alpha)

<div class="iops-meta" markdown="1">
<span class="key">bl_idname: iops.mesh_assign_vertex_color_alpha</span>
<span class="mode">Mode: Edit Mesh</span>
<span>Context: VIEW_3D</span>
<span class="modal">Modal: no</span>
<span class="hud">HUD: no</span>
</div>

### Overview
Writes only the alpha channel of the active color attribute on selected vertices, leaving RGB untouched. Useful when alpha is used as a mask, weight, or AO channel and you don't want to disturb existing color data.

### Usage
- Requires an active mesh object in Edit Mode.
- No default keymap binding.
- The operator temporarily switches to Object Mode to read selection state, applies the alpha, then returns to Edit Mode.

### Properties
| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `vertex_color_alpha` | Float | `1.0` | Alpha value to write. Range `0.0` (transparent) – `1.0` (solid). |

### Notes
- If the mesh has no color attribute, a new one named `Color` of type `FLOAT_COLOR` on the `CORNER` domain is created before writing.
- If there is no active color attribute but at least one exists, the first attribute becomes active and is used.
- POINT domain: alpha is written per selected vertex. CORNER domain: alpha is written for every loop whose vertex is selected.
- Wrapped in a try/except — on failure the operator attempts to restore Edit Mode and reports an `ERROR`.

## Related
- [Vertex Color Picker / scene IOPS color](../index.md) — supplies `scene.IOPS.iops_vertex_color`.
