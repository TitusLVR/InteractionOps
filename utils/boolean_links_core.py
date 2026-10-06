"""Pure helpers for the boolean / mirror link selectors — no bpy imports.

Objects are duck-typed: anything with a `.modifiers` sequence whose items
carry `.type` plus the Boolean (`object`, `operand_type`, `collection`)
or Mirror (`mirror_object`) pointer fields. Results are lists in first-
seen order with duplicates removed, and never contain a source object.
"""


def _unique(seq):
    seen = set()
    out = []
    for item in seq:
        key = id(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _boolean_operand_objects(md):
    """Objects a single Boolean modifier reads from (object or every
    member of its operand collection)."""
    if md.type != "BOOLEAN":
        return ()
    if getattr(md, "operand_type", "OBJECT") == "COLLECTION":
        coll = getattr(md, "collection", None)
        return tuple(coll.all_objects) if coll is not None else ()
    obj = getattr(md, "object", None)
    return (obj,) if obj is not None else ()


def boolean_operands(sources):
    """Every object the Boolean modifiers on `sources` cut with."""
    sources = list(sources)
    source_ids = {id(s) for s in sources}
    found = []
    for src in sources:
        for md in getattr(src, "modifiers", ()):
            found.extend(o for o in _boolean_operand_objects(md)
                         if id(o) not in source_ids)
    return _unique(found)


def boolean_users(objects, targets):
    """Objects among `objects` whose Boolean modifiers use any of
    `targets` as an operand (directly or via an operand collection)."""
    target_ids = {id(t) for t in targets}
    users = []
    for obj in objects:
        if id(obj) in target_ids:
            continue
        for md in getattr(obj, "modifiers", ()):
            if any(id(o) in target_ids for o in _boolean_operand_objects(md)):
                users.append(obj)
                break
    return users


def mirror_objects(sources):
    """Every mirror object referenced by Mirror modifiers on `sources`."""
    sources = list(sources)
    source_ids = {id(s) for s in sources}
    found = []
    for src in sources:
        for md in getattr(src, "modifiers", ()):
            if md.type != "MIRROR":
                continue
            mo = getattr(md, "mirror_object", None)
            if mo is not None and id(mo) not in source_ids:
                found.append(mo)
    return _unique(found)


def local_view_of(space):
    """`space` if it is a 3D View currently in local view, else None."""
    if space is None or getattr(space, "type", None) != "VIEW_3D":
        return None
    return space if getattr(space, "local_view", None) is not None else None
