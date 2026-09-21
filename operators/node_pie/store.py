"""File-backed rule store for the node pie.

Reads `scripts/presets/IOPS/node_pies/<tree_type>.json` over the shipped
defaults and caches the result per tree type. All parsing lives in
`utils/node_pie_rules.py`; this module only does files, caching and warnings.
"""
import json
import os

import bpy

from ...utils import node_pie_rules as nr

_cache: dict[str, dict] = {}
_warned: set[str] = set()
_label_cache: dict[str, str] = {}

#: Re-exported so bpy-side callers need not import the pure module.
TREE_TYPES = nr.TREE_TYPES


def label_for(idname: str) -> str:
    """Blender's friendly name for a node `bl_idname`, e.g. "Set Position"
    for "GeometryNodeSetPosition".

    `bl_label` looks like the obvious source, but for Blender's built-in
    node types it is instance-only: `getattr(bpy.types.GeometryNodeSetPosition,
    "bl_label", None)` is None, and `bl_label` does not even appear in
    `dir()` of the class — it only resolves on an actual node instance.
    `bl_rna.name` carries the same string and *is* available on the class
    itself, so that is checked first, with `bl_label` kept as a fallback
    for any custom Node subclass that sets it but has no `bl_rna.name` for
    whatever reason.

    Falls back to `idname` itself whenever the type is not registered in
    the running Blender (a rule can name a node type this Blender does not
    have) or neither of those resolves to a usable string — this is
    reachable from draw callbacks, which must never raise. Cached at
    module scope since draw callbacks call this every redraw.
    """
    cached = _label_cache.get(idname)
    if cached is not None:
        return cached
    cls = getattr(bpy.types, idname, None)
    rna = getattr(cls, "bl_rna", None) if cls is not None else None
    label = getattr(rna, "name", None) if rna is not None else None
    if not (isinstance(label, str) and label):
        label = getattr(cls, "bl_label", None) if cls is not None else None
    result = label if isinstance(label, str) and label else idname
    _label_cache[idname] = result
    return result


def warn_once(message: str) -> None:
    """Print a warning at most once per session — this runs near draw code."""
    if message not in _warned:
        _warned.add(message)
        print(f"IOPS Node Pie: {message}")


def preset_dir() -> str | None:
    """The user preset directory, or None when Blender has no user scripts path.

    `bpy.utils.script_path_user()` can return None (e.g. under some portable
    or sandboxed configurations); joining onto that would raise TypeError,
    and this is reachable from a pie draw callback, where an exception
    breaks the UI. Callers treat None as "no user preset file exists".
    """
    base = bpy.utils.script_path_user()
    if base is None:
        warn_once("no user scripts path available; using shipped node pie defaults")
        return None
    return os.path.join(base, "presets", "IOPS", "node_pies")


def preset_path(tree_type: str) -> str | None:
    directory = preset_dir()
    if directory is None:
        return None
    return os.path.join(directory, f"{tree_type}.json")


def rules_for(tree_type: str) -> dict:
    """Merged rules for a tree type, loaded from disk on first use."""
    if tree_type in _cache:
        return _cache[tree_type]
    defaults = nr.DEFAULTS.get(tree_type, {})
    path = preset_path(tree_type)
    text = ""
    if path is not None and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
        except (OSError, UnicodeDecodeError) as exc:
            warn_once(f"could not read {path}: {exc}")
    rules, warnings = nr.load_document(text, defaults)
    for warning in warnings:
        warn_once(warning)
    _cache[tree_type] = rules
    return rules


def get_entries(tree_type: str, node_idname: str):
    return nr.get_entries(rules_for(tree_type), node_idname)


def active_if_selected(nodes):
    """`nodes.active`, but only when that node is actually selected.

    `nodes.active` survives Select All > None — Blender does not clear it —
    so right after a deselect the tree still reports whatever node was
    active before. Treating that stale reference as real would show the pie
    for a node the user can no longer see selected, or wire a freshly
    spawned node onto it. Both the pie draw and the spawn operator go
    through this so the two never disagree. `getattr` guards a
    removed/invalid node reference; this is reachable from a draw callback,
    which must never raise.
    """
    active = nodes.active
    if active is not None and not getattr(active, "select", False):
        return None
    return active


def set_rules(tree_type: str, rules: dict) -> None:
    """Replace the in-memory rules — edits apply to the next pie open."""
    _cache[tree_type] = rules


def save(tree_type: str, rules: dict) -> str:
    """Write the whole tree-type document; returns the path written.

    Raises RuntimeError, rather than joining onto a bogus path, when there
    is no user scripts path to write into.
    """
    path = preset_path(tree_type)
    if path is None:
        raise RuntimeError(
            "cannot save node pie preset: no user scripts path available"
        )
    os.makedirs(os.path.dirname(path), exist_ok=True)
    doc = {"version": nr.SCHEMA_VERSION, "tree_type": tree_type, "rules": rules}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(doc, handle, indent=2)
    set_rules(tree_type, rules)
    return path


def reload(tree_type=None) -> None:
    """Drop cached rules so the next read comes from disk."""
    if tree_type is None:
        _cache.clear()
    else:
        _cache.pop(tree_type, None)


def reset() -> None:
    """Forget everything held for the session — rules and warning suppression.

    Both survive a disable/enable of the addon in the same session, because
    module globals do. Without this a reload keeps serving stale rules and
    stays silent about warnings the user has never actually seen.
    """
    _cache.clear()
    _warned.clear()
