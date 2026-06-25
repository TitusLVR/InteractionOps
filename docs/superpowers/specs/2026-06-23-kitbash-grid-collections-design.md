# KitBash Grid — Collection Mode

## Goal

Extend `IOPS_OT_KitBash_Grid` (operators/object_kitbash_grid.py) so it can arrange
**collections** as single units, in addition to its existing per-object behavior.
Each collection is treated as one rigid unit: its compound bounding box drives
sorting/placement, and all its objects move together preserving internal layout.

## Mode switch

New property:

```python
operate_on: EnumProperty(
    items=[('OBJECTS', "Objects", ...), ('COLLECTIONS', "Collections", ...)],
    default='OBJECTS')
```

Shown first in the dialog `draw()`. When `OBJECTS`, behavior is unchanged
(mesh/empty path as today).

## Collecting collections (COLLECTIONS mode)

- Iterate `context.selected_objects`; for each, gather `obj.users_collection`.
- Build a deduplicated, order-stable set of collections.
- The active object's collection is the starting unit (analogous to the current
  active object: it defines the placement reference point). If the active object
  belongs to several collections, pick its first that is in the set.
- An object may live in multiple collections. Each object is moved at most once.
  If collection object-sets overlap, emit a `report({'WARNING'}, ...)` but proceed.

## Collection bbox helper

New `get_collection_bbox_data(coll, depsgraph)`:

- Use `coll.all_objects` (already includes nested sub-collections, recursively).
- Consider `MESH` objects only; compute world-space compound bbox.
- Return the same dict shape as the existing helpers:
  `min, max, center, dim, volume, world_bbox_center_offset, obj_origin`.
  `obj_origin` = bbox center (collections have no transform of their own).
- If no valid mesh objects: return `None` (collection is skipped).

Returning the same dict shape lets the existing sorting, alignment, and placement
code be reused unchanged — the "unit" is just a collection instead of an object.

## Moving a collection

Placement computes the desired world position of the alignment point, then:

```
delta = target_align_world - current_align_world
```

Apply `delta` only to the collection's **root** objects — objects whose parent is
`None` or whose parent is not in `coll.all_objects`. Translate via
`obj.matrix_world.translation += delta`; children follow their parents, so internal
layout is preserved and parent hierarchies are handled correctly. Track moved
objects in a set to guarantee each is moved once across overlapping collections.

## Other adjustments

- `invoke()`: auto grid-columns count uses number of collections in COLLECTIONS mode.
- `NAME` / `NAME_INV` sort uses `coll.name` in COLLECTIONS mode.
- Cursor-update steps re-read the collection bbox via `get_collection_bbox_data`
  (mirrors the existing per-object re-read after each move).

## Out of scope (YAGNI)

- No change to object/empty mode.
- No Outliner-selection source.
- No special handling of collection instances as transform objects.
- No support for arranging overlapping-membership collections rigidly (warned only).
