"""Spawn a node already wired to the active one, then hand it to a grab."""
import json

import bpy

from ...utils import node_pie_planner as pl
from . import catalog, store


def _socket_descs(sockets):
    return tuple(
        pl.SocketDesc(name=s.name, type=s.type, index=i,
                      enabled=s.enabled, hide=s.hide)
        for i, s in enumerate(sockets)
    )


def _node_desc(node):
    return pl.NodeDesc(
        bl_idname=node.bl_idname,
        location=tuple(node.location),
        width=node.width,
        inputs=_socket_descs(node.inputs),
        outputs=_socket_descs(node.outputs),
    )


def _downstream(ntree, active):
    out = []
    for link in ntree.links:
        # `==`, never `is`: bpy_struct attribute access hands back a fresh
        # Python wrapper each time, so `link.from_node is active` is False
        # even for the same node. `==` compares the underlying data pointer.
        if link.from_node != active:
            continue
        out.append(pl.LinkDesc(
            from_node=active.name,
            from_socket=list(active.outputs).index(link.from_socket),
            to_node=link.to_node.name,
            to_socket=list(link.to_node.inputs).index(link.to_socket),
            to_socket_type=link.to_socket.type,
            to_node_location=tuple(link.to_node.location),
        ))
    return tuple(out)


def _matches_link_desc(existing, active, link):
    """True when `existing` is the exact link a `LinkDesc` describes.

    Exact match on all three addresses — from-socket index, to_node name,
    to-socket index — not just `to_node`. A node can have several outputs, so
    matching on `to_node` alone would also remove sibling links that happen to
    land on the same downstream node from a *different* output socket: real
    data loss in the user's graph.
    """
    # `!=` rather than `is not`: see `_downstream`.
    if existing.from_node != active:
        return False
    if existing.to_node.name != link.to_node:
        return False
    from_idx = list(active.outputs).index(existing.from_socket)
    to_idx = list(existing.to_node.inputs).index(existing.to_socket)
    return from_idx == link.from_socket and to_idx == link.to_socket


def _resolve(ntree, ref, active, new):
    """Turn a plan's node reference into a real node, or None.

    `is` is the right test here — `pl.ACTIVE` / `pl.NEW` are ordinary Python
    singletons, not bpy structs. Anything else is a node *name*, and it is
    looked up as one: that is what keeps a node the user happened to call
    `NEW` from resolving to the node being spawned.
    """
    if ref is pl.ACTIVE:
        return active
    if ref is pl.NEW:
        return new
    return ntree.nodes.get(ref)


def _entry_dict(entry, key):
    """A dict field of an entry, or {}.

    `normalise_rule` already drops a non-dict `props`/`inputs`, but this
    operator's `entry_json` is a plain string property, so it is a second way
    in that never passed through the rule store. `.items()` on a non-dict
    raises AttributeError straight out of `execute()`.
    """
    value = entry.get(key)
    return value if isinstance(value, dict) else {}


def _apply_entry_props(node, entry, report):
    for key, value in _entry_dict(entry, "props").items():
        try:
            setattr(node, key, value)
        except (AttributeError, TypeError, ValueError) as exc:
            report({'INFO'}, f"node pie: could not set {key}: {exc}")
    for key, value in _entry_dict(entry, "inputs").items():
        socket = None
        if isinstance(key, str) and key.isdigit():
            key = int(key)
        if isinstance(key, int):
            if 0 <= key < len(node.inputs):
                socket = node.inputs[key]
        else:
            socket = node.inputs.get(key)
        if socket is None:
            continue
        try:
            socket.default_value = value
        except (AttributeError, TypeError, ValueError) as exc:
            report({'INFO'}, f"node pie: could not set input {key}: {exc}")


def plan_for(ntree, active, new, entry):
    """Describe `active` and `new` to the pure planner and return its plan."""
    return pl.plan_spawn(
        _node_desc(active), _node_desc(new),
        downstream=_downstream(ntree, active),
        from_socket=entry.get("from_socket"),
    )


def apply_plan(ntree, plan, active, new):
    """Move and rewire `new` per `plan`. Makes no decisions of its own.

    Split out of the operator so the graph editing — where the identity bug
    that disabled the whole splice lived — is callable, and therefore
    testable, without an operator context. Removals run before additions so
    a spliced input socket is free when its replacement link is made.
    """
    new.location = plan.location
    for link in plan.links_to_remove:
        for existing in list(ntree.links):
            if _matches_link_desc(existing, active, link):
                ntree.links.remove(existing)
    for from_key, from_idx, to_key, to_idx in plan.links_to_add:
        from_node = _resolve(ntree, from_key, active, new)
        to_node = _resolve(ntree, to_key, active, new)
        if from_node is None or to_node is None:
            continue
        ntree.links.new(from_node.outputs[from_idx], to_node.inputs[to_idx])


class IOPS_OT_NodeSpawnConnected(bpy.types.Operator):
    """Add a node connected to the active one"""

    bl_idname = "iops.node_spawn_connected"
    bl_label = "Spawn Connected Node"
    bl_options = {'REGISTER', 'UNDO'}

    node_idname: bpy.props.StringProperty(name="Node", default="")
    entry_json: bpy.props.StringProperty(name="Entry", default="")

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return (
            space is not None
            and space.type == 'NODE_EDITOR'
            and space.edit_tree is not None
        )

    def execute(self, context):
        ntree = context.space_data.edit_tree
        # Gated: `nodes.active` outlives a deselect-all, see
        # `store.active_if_selected`. Without this the new node would
        # silently wire onto a node the pie itself just treated as absent.
        active = store.active_if_selected(ntree.nodes)

        try:
            entry = json.loads(self.entry_json) if self.entry_json else {}
        except ValueError:
            entry = {}
        if not isinstance(entry, dict):
            entry = {}
        idname = self.node_idname or entry.get("node", "")

        try:
            new = ntree.nodes.new(idname)
        except (RuntimeError, TypeError) as exc:
            self.report({'WARNING'}, f"cannot add {idname}: {exc}")
            return {'CANCELLED'}

        _apply_entry_props(new, entry, self.report)

        if active is None:
            new.location = context.space_data.cursor_location
        else:
            plan = plan_for(ntree, active, new, entry)
            apply_plan(ntree, plan, active, new)
            if plan.warning:
                self.report({'INFO'}, plan.warning)

        for node in ntree.nodes:
            node.select = False
        new.select = True
        ntree.nodes.active = new

        bpy.ops.transform.translate('INVOKE_DEFAULT')
        return {'FINISHED'}


def _catalog_items(self, context):
    space = context.space_data
    tree = space.edit_tree if space else None
    if tree is None:
        return [('NONE', "None", "")]
    return catalog.items(tree.bl_idname) or [('NONE', "None", "")]


class IOPS_OT_NodePieAddSearch(bpy.types.Operator):
    """Search every node type valid in this editor"""

    bl_idname = "iops.node_pie_add_search"
    bl_label = "Add New Node"
    bl_property = "node_type"
    bl_options = {'REGISTER', 'UNDO'}

    node_type: bpy.props.EnumProperty(name="Node", items=_catalog_items)

    @classmethod
    def poll(cls, context):
        return IOPS_OT_NodeSpawnConnected.poll(context)

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if self.node_type == 'NONE':
            return {'CANCELLED'}
        return bpy.ops.iops.node_spawn_connected(node_idname=self.node_type)


classes = (
    IOPS_OT_NodeSpawnConnected,
    IOPS_OT_NodePieAddSearch,
)
