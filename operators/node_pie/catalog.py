"""Which node types can actually be created in a given node tree.

`NodeClass.poll(ntree)` is NOT usable for this: in Blender 5.2.2 it returns
False for ShaderNodeMath, ShaderNodeMix, ShaderNodeValToRGB, NodeReroute,
NodeGroupInput and NodeFrame inside a GeometryNodeTree, all of which create
fine. The only reliable test is to create the node in a scratch tree and see
whether it raises. ~600 node classes, so this runs once per tree type per
session, lazily, and only for the `Add New Node…` search.
"""
import bpy

from . import store

_cache: dict[str, list[tuple[str, str, str]]] = {}


def clear() -> None:
    _cache.clear()


def _node_classes():
    seen = set()
    stack = list(bpy.types.Node.__subclasses__())
    while stack:
        cls = stack.pop()
        name = getattr(cls, "bl_rna", None) and cls.bl_rna.identifier
        if not name or name in seen:
            continue
        seen.add(name)
        stack.extend(cls.__subclasses__())
        yield name, cls


def items(tree_type: str) -> list[tuple[str, str, str]]:
    """(identifier, label, description) for every node creatable in `tree_type`.

    The returned list is kept in a module-level cache; Blender frees dynamic
    enum item strings that nothing holds a reference to, which crashes mid-draw.
    """
    if tree_type in _cache:
        return _cache[tree_type]

    scratch = bpy.data.node_groups.new("IOPS_NodePie_Probe", tree_type)
    found = []
    try:
        for idname, _cls in _node_classes():
            try:
                node = scratch.nodes.new(idname)
            except (RuntimeError, TypeError):
                continue
            found.append((idname, store.label_for(idname), idname))
            scratch.nodes.remove(node)
    finally:
        bpy.data.node_groups.remove(scratch)

    found.sort(key=lambda item: item[1].lower())
    _cache[tree_type] = found
    return found
