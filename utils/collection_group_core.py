"""Pure helpers for grouping duplicate-named objects (no bpy).

Blender appends ``.NNN`` to names that collide. ``base_key`` strips exactly
that suffix, so ``box``, ``box.000`` and ``box.001`` share the key ``box``
while ``box_lid`` stays a distinct key: underscores are part of the name.
"""

import re

_NUMERIC_SUFFIX = re.compile(r"^(.+)\.\d+$")


def base_key(name):
    """Return ``name`` without a trailing Blender ``.NNN`` numeric suffix."""
    match = _NUMERIC_SUFFIX.match(name)
    return match.group(1) if match else name


def group_duplicates(names):
    """Map base key -> list of names (input order) for keys with 2+ members.

    Keys are returned in sorted order so callers create collections
    deterministically.
    """
    groups = {}
    for name in names:
        groups.setdefault(base_key(name), []).append(name)
    return {key: groups[key] for key in sorted(groups) if len(groups[key]) > 1}
