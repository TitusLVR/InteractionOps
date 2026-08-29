# Assign Vertex Color

Fills a colour into the mesh's colour attribute: on the selected vertices in Edit Mesh mode, or on the whole mesh for every selected object in Object mode. Pick the colour in the iOps Vertex Color widget, or use the one-click Black / Grey / White fills. A colour attribute is created if the mesh has none.

**Hotkey:** Not bound by default — assign a key in *Preferences › iOps › Keymaps*, or run it from the iOps pie / operator search. Also available: iOps Pie › Set Vertex Color (with White / Grey / Black), Vertex Color widget › Set Color.

## Options
- **Use Active Color** — write to the active colour attribute; otherwise to the named one.
- **Color Attribute Name / Domain / Type** — used when a new attribute has to be created.
- **Fill Black / Grey / White** — one-shot overrides of the picked colour.

## Set Vertex Alpha
Writes only the alpha channel on the selected vertices, leaving RGB untouched — handy when alpha is a mask or AO channel. Edit Mesh mode. Available from iOps Pie › Set Vertex Alpha and the Vertex Color widget › Set Alpha.

- **Alpha** — value from 0 (transparent) to 1 (solid).

## Fill RGB channel
The widget's **Fill RGB** rows set (=), add (+) or subtract (−) a single R, G or B channel on the selection while keeping the other channels and alpha.

## Tips
- **Preview VC** in the widget shows the raw vertex colours of the whole scene in the viewport; toggle it off to restore your shading.
