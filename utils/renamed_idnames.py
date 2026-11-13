"""Operator idnames that changed, and the migration of saved data that names them.

Pure Python (no bpy), unit-testable standalone. The saved hotkeys file and the
Edit Pie slots in the prefs JSON store operator idnames as text; a renamed
operator would lose its binding or its pie slot. Each loader passes what it
read through these functions, in memory only: the files are rewritten with the
new idnames the next time the user saves them.
"""
from __future__ import annotations

# Old idname -> new idname.
RENAMED_IDNAMES = {
    "iops.mesh_smart_inset": "iops.mesh_inset",
    "iops.mesh_smart_edge_slide": "iops.mesh_edge_slide",
}


def migrate_idname(idname):
    """The current idname for ``idname``: the new one if it was renamed, otherwise unchanged (non-strings too)."""
    if not isinstance(idname, str):
        return idname
    return RENAMED_IDNAMES.get(idname, idname)


def migrate_key_rows(keys):
    """Saved hotkey rows (``[idname, key, value, ctrl, alt, shift, oskey]``) with renamed idnames replaced.

    A row under an old idname takes the new idname and keeps its binding. When the
    rows already hold the new idname as well, that row wins and the old one is
    dropped. Rows are copied as lists; anything that is not a list or tuple
    starting with a string passes through untouched, order is kept, and the
    input is not changed.
    """
    def _is_row(row):
        return isinstance(row, (list, tuple)) and row and isinstance(row[0], str)

    present = {row[0] for row in keys if _is_row(row)}
    out = []
    for row in keys:
        if not _is_row(row):
            out.append(row)
            continue
        new = RENAMED_IDNAMES.get(row[0])
        if new is None:
            out.append(list(row))
        elif new not in present:
            out.append([new, *row[1:]])
    return out


def migrate_operator_call(text):
    """An Edit Pie custom-slot call (``"iops.mesh_smart_inset"`` or ``"iops.mesh_smart_inset(x=1)"``) with
    a renamed idname replaced; any other text is returned unchanged."""
    if not isinstance(text, str):
        return text
    stripped = text.strip()
    for old, new in RENAMED_IDNAMES.items():
        if stripped == old or stripped.startswith(old + "("):
            return new + stripped[len(old):]
    return text
