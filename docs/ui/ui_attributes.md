# Attributes Panel

List a mesh's generic attributes and vertex groups, type a value straight onto the selection the way the Item tab edits a vertex position, preview an attribute in the viewport, and run a few attribute tools Blender does not have. Anything added through geometry nodes, Python or the Properties editor shows up without any naming convention.

**Where:** *N panel › iOps › iOps Attributes*, in Object Mode and Edit Mode with a mesh active. No hotkey.

## The list

One row per attribute: domain icon (vertex / edge / face / corner), name, then domain and data type dimmed like Blender's own list (`Vertex - Float`, `Edge - Integer`, `Face Corner - Color`) and the element count in Object Mode. Vertex groups appear as rows typed `Vertex Group`. The highlighted row is the active attribute: it is also made active in *Properties › Data › Attributes*, so *Mesh › Set Attribute* and the panel agree.

| Button | What it does |
| --- | --- |
| **Hidden / Built-in / Vertex Groups** toggles | Show `.`-prefixed attributes, the built-ins that have their own UI (position, crease, bevel weight, sharp, material index, UV maps, colour attributes), and vertex groups |
| **+** | New attribute: name, type, domain, default value |
| **−** | Remove the active attribute or vertex group |
| **Duplicate** | Copy the active attribute with its data (`name.copy`) |
| **Refresh** | Rebuild the list (normally automatic) |
| **▾** menu | Set / Reset on selection, Convert, and the tools below |
| Double-click a name | Rename in place |

A lock on a row means bmesh has no layer for that type (INT8, FLOAT2, quaternion, matrix, 2D ints): it can be read in Edit Mode and edited in Object Mode. STRING attributes are read-only.

## Value editor

The panel is one frame (filter toggles and the list) with an element frame inside it for the active row: a `Type` line (`Vertex  Index 12`; `Index 12 (16 selected)` when several are selected, `all (98)` in Object Mode, `none` with nothing selected), then the attribute name and its value field. Under the frame a full-width **Preview** toggle button, then the collapsible **Preview Settings** sub-panel. The field shows the value of the **active element** of that row's domain. Typing a value, or dragging the field, writes it to **every selected element** of that domain: one selected vertex changes only itself, select all and type 45 and every vertex reads 45. Geometry-nodes modifiers on the object refresh immediately. One typed value or one drag is one undo step.

- With no active element of that domain the first selected one is shown.
- Nothing selected: the field is disabled.
- Object Mode: the field shows the first element's value and writes every element. **Set All** / **Reset All** live in the menu.
- Vertex group rows read and write weights; a selected vertex not in the group reads 0 and is added on write.

## Tools (▾ menu)

Each tool is one undo step and works on the selected elements of the attribute's domain in Edit Mode, on every element in Object Mode. Entries that do not fit the active row's type are greyed with the reason in the tooltip.

| Tool | What it does |
| --- | --- |
| **Set on Selection… / Reset on Selection** | Write a typed value, or the type's default, to the selected, unselected or all elements |
| **Convert Type / Domain…** | Blender's attribute conversion on the active row (Object Mode) |
| **Gradient on Chain…** | Select a chain of vertices (a path or a loop) and interpolate between the chain's end values or two typed values, linear or eased. Point and edge attributes. This is how a tilt ramp along a track gets made in one click |
| **Math…** | Add, Multiply, Clamp, Invert, Remap (min..max of the selection to A..B), Round |
| **Smooth…** | Laplacian smoothing over the selected elements, N iterations with a factor |
| **Randomize…** | Seeded random values between min and max |
| **Copy / Swap…** | Copy into another attribute of the same domain, converting float / int / bool and picking a vector component; **Swap** exchanges the two |
| **Vertex Group to Attribute… / Attribute to Vertex Group…** | Copy weights into a float attribute (default name `<group>.attr`, since an attribute and a vertex group cannot share a name) and back, weights clamped to 0..1 and every vertex assigned. Non-destructive both ways. The other tools only ever touch a group's existing members |
| **Select by Value…** | Select elements equal / not equal / less / greater / in range, or equal to the active element, with a tolerance. Extend or replace the selection |

## Preview

The preview draws the **active row** on every element of its domain, selected or not, in the iOps theme colours. The full-width **Preview** button under the frame turns it on; it is off by default and off again whenever a file is opened (the toggle is a session overlay, not file data). On, it follows the list: click another row and the viewport shows that attribute. Off, it costs nothing.

The **Show** checkboxes in Preview Settings combine: Labels can be on together with a fill. The three fills are exclusive on the geometry, so when several are ticked Heatmap wins, then Colour, then Greyscale.

| Checkbox | What you see |
| --- | --- |
| **Labels** | The raw value as text on a dark box next to each vertex, edge midpoint, face centre or corner; floats use the **Decimals** setting, vectors print their components, **Text Size** is in pixels. Selected elements use the theme's Active colour |
| **Heatmap** | Any numeric attribute through a blue → red ramp from the mesh's minimum to its maximum; the `min … max` range is shown as **Range** in Preview Settings |
| **Colour / Greyscale** | Colour attributes shaded onto the geometry as stored or as luminance; disabled for any other attribute type |

**Selected Only** (Edit Mode) limits labels, fills and the heatmap range to the selected elements; in Object Mode the whole mesh is previewed and the checkbox is disabled.

Labels are skipped above the **Preview Label Limit** (*Preferences › iOps › Attributes Panel*, default 2000 elements); the colour modes still draw. The preview respects the viewport's overlay toggle and clipping region, keeps its last picture while a modal tool (G / R / S, loop cut) runs, and switches off when the active object is no longer a mesh.

## Tips

- Hidden elements are never written to and never labelled.
- In multi-object Edit Mode the list and the fields follow the active object; writes and tools reach every edit mesh that has the same attribute.
- Selection-set layers (`.iops_ss_*`) are never listed, even with **Hidden** on.
