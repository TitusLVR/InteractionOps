"""Material slot removal with explicit face / spline re-indexing.

Mesh.materials.pop() shifts face indices by its own rule in Object Mode and
not at all in Edit Mode (the bmesh keeps its indices), so every removal here
reads the indices first, pops, then writes the planned indices back. Slot
plans come from utils/materials_core.py (plan_slot_collapse, plan_removal).
"""
import bmesh
import bpy

from ...utils import materials_core as core
from . import common

OBJECT_LINKED = "object-linked slots"


def data_users():
    """{data pointer: [objects]} over every object in the file."""
    users = {}
    for obj in bpy.data.objects:
        data = obj.data
        if data is not None and hasattr(data, "materials"):
            users.setdefault(data.as_pointer(), []).append(obj)
    return users


def slot_skip_reason(data, users):
    """None when the slots of `data` can be removed safely, else a report
    label. Object-linked slots on any user would be misaligned by a data
    slot removal, so such data is left alone."""
    if common.is_linked(data):
        return "Linked"
    if isinstance(data, bpy.types.TextCurve):
        return "Text"
    if isinstance(data, bpy.types.Curve) and data.is_editmode:
        return "Curve in Edit Mode"
    if not isinstance(data, (bpy.types.Mesh, bpy.types.Curve)):
        return users[0].bl_rna.properties["type"].enum_items[
            users[0].type].name if users else type(data).__name__
    for obj in users:
        if any(s.link == "OBJECT" for s in obj.material_slots):
            return OBJECT_LINKED
    return None


def get_indices(data):
    if isinstance(data, bpy.types.Mesh):
        if data.is_editmode:
            return [f.material_index for f in bmesh.from_edit_mesh(data).faces]
        idx = [0] * len(data.polygons)
        if idx:
            data.polygons.foreach_get("material_index", idx)
        return idx
    return [s.material_index for s in data.splines]


def _set_indices(data, idx):
    if isinstance(data, bpy.types.Mesh):
        if data.is_editmode:
            bm = bmesh.from_edit_mesh(data)
            for f, i in zip(bm.faces, idx):
                f.material_index = i
            bmesh.update_edit_mesh(data, loop_triangles=False,
                                   destructive=False)
        elif idx:
            data.polygons.foreach_set("material_index", idx)
            data.update()
        return
    for s, i in zip(data.splines, idx):
        s.material_index = i


def used_indices(data):
    return set(get_indices(data))


def apply_removal(data, removed, remap):
    """Pop the slots in `removed` and re-index faces / splines by `remap`.
    Returns the number of slots removed."""
    if not removed:
        return 0
    idx = get_indices(data)
    for i in sorted(removed, reverse=True):
        data.materials.pop(index=i)
    if not data.materials:
        # popping the last slot leaves the users' object-level slot arrays
        # at length 1; clear() resizes them to 0
        data.materials.clear()
    _set_indices(data, core.remap_indices(idx, remap))
    return len(removed)


def slot_keys(data):
    return [common.material_key(m) if m is not None else None
            for m in data.materials]


def cleanup_slots(data, collapse=True, drop_empty=False):
    """Collapse repeated materials and / or drop empty slots on `data`.
    Returns (repeats removed, empty slots removed). The caller checks
    slot_skip_reason() first."""
    keys = slot_keys(data)
    removed, remap = core.plan_slot_collapse(
        keys, drop_empty=drop_empty, collapse_repeats=collapse)
    empties = sum(1 for i in removed if keys[i] is None)
    apply_removal(data, removed, remap)
    return len(removed) - empties, empties


def needs_cleanup(data, collapse=True, drop_empty=False):
    keys = slot_keys(data)
    removed, _remap = core.plan_slot_collapse(
        keys, drop_empty=drop_empty, collapse_repeats=collapse)
    return bool(removed)


def remove_slots(data, removed):
    """Remove the slots in `removed`; faces / splines of a removed slot go
    to the first remaining slot (0), the others follow their slot."""
    return apply_removal(
        data, removed, core.plan_removal(len(data.materials), removed))


def empty_slot_count(data):
    return sum(1 for m in data.materials if m is None)


def cleanup_many(datas, collapse=True, drop_empty=False, changed=None):
    """cleanup_slots() over unique data. Returns (repeats removed, empty
    removed, {skip label: count}); data with nothing to do is not counted
    as skipped. Pointers of changed data are added to `changed` (a set)."""
    users = data_users()
    repeats = empties = 0
    skipped = {}
    seen = set()
    for data in datas:
        key = data.as_pointer()
        if key in seen:
            continue
        seen.add(key)
        if not needs_cleanup(data, collapse, drop_empty):
            continue
        reason = slot_skip_reason(data, users.get(key, []))
        if reason is not None:
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        r, e = cleanup_slots(data, collapse, drop_empty)
        if changed is not None:
            changed.add(key)
        repeats += r
        empties += e
    return repeats, empties, skipped
